"""Check a reference list for citations that point to no real work.

Each reference is parsed, then looked up: by its DOI on Crossref when it has one, otherwise by its text on
Crossref and then OpenAlex. A record counts as a match only when its title is close and, where the reference
gives them, its first author and year agree too.

Verdicts:
  ok         a published record matches the title, first author and year
  mismatch   the DOI resolves, or a record matches the title, but the authors, year or title disagree
  bad_doi    the DOI is not registered anywhere we can see
  not_found  no record comes close; check it by hand (many real theses, reports and old books are not indexed)
"""
from __future__ import annotations

import json
import os
import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from difflib import SequenceMatcher

from . import __version__

VERDICTS = ("ok", "mismatch", "bad_doi", "not_found")


def _norm(x: str) -> str:
    x = unicodedata.normalize("NFKD", x or "").encode("ascii", "ignore").decode()
    return re.sub(r"[\W_]+", " ", x.lower()).strip()


def _sim(a: str, b: str) -> float:
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return 0.0
    # A reference often shortens a long title or drops its subtitle.
    short, long_ = sorted((a, b), key=len)
    if len(short) >= 25 and long_.startswith(short):
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def _year(item: dict):
    try:
        return int((item.get("issued", {}).get("date-parts") or [[None]])[0][0])
    except (TypeError, ValueError):
        return None


def _family(item: dict) -> str:
    for a in item.get("author") or []:
        if a.get("family"):
            return _norm(a["family"])
    return ""


class _Client:
    def __init__(self, mailto: str | None, timeout: int, openalex_key: str | None = None):
        self.ua = {"User-Agent": f"citeparse/{__version__} (https://github.com/un-seen/citeparse"
                                 + (f"; mailto:{mailto}" if mailto else "") + ")"}
        self.mailto, self.timeout = mailto, timeout
        self.openalex_key = openalex_key or os.environ.get("OPENALEX_API_KEY")
        self.down: set[str] = set()  # services that told us to come back much later

    def get(self, url: str, tries: int = 4):
        """JSON from url; {"_status": code} for a 4xx answer; None if the service did not answer."""
        host = urllib.parse.urlparse(url).netloc
        if host in self.down:
            return None
        for k in range(tries):
            try:
                req = urllib.request.Request(url, headers=self.ua)
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    return json.load(r)
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    try:
                        wait = float(e.headers.get("Retry-After") or 0)
                    except ValueError:
                        wait = 0
                    if wait > 60:  # a daily budget is spent: stop asking this service for the rest of the run
                        self.down.add(host)
                        return None
                elif e.code < 500:
                    return {"_status": e.code}
            except Exception:
                pass
            time.sleep(1.5 * 2 ** k)  # rate limit, server error or timeout: back off and retry
        return None

    def crossref_doi(self, doi: str):
        r = self.get("https://api.crossref.org/works/" + urllib.parse.quote(doi))
        if r and "message" in r:
            return _from_crossref(r["message"])
        if r and r.get("_status") == 404:
            # Not a Crossref DOI. DataCite (Zenodo, arXiv, figshare) registers many others.
            d = self.get("https://api.datacite.org/dois/" + urllib.parse.quote(doi))
            if d and "data" in d:
                a = d["data"]["attributes"]
                return {"title": " ".join(t.get("title", "") for t in a.get("titles", [])[:1]),
                        "families": [_norm(c.get("familyName") or c.get("name", "")) for c in a.get("creators", [])],
                        "year": a.get("publicationYear"), "doi": doi, "source": "datacite"}
            return "missing"
        return None  # network trouble: say nothing rather than call it fake

    def crossref_search(self, q: str):
        p = {"rows": 5, "query.bibliographic": q[:500]}
        if self.mailto:
            p["mailto"] = self.mailto
        r = self.get("https://api.crossref.org/works?" + urllib.parse.urlencode(p))
        return [_from_crossref(m) for m in (r or {}).get("message", {}).get("items", [])] if r else None

    def openalex_search(self, title: str):
        p = {"search": title[:300], "per-page": 5}
        if self.openalex_key:
            p["api_key"] = self.openalex_key
        elif self.mailto:
            p["mailto"] = self.mailto
        r = self.get("https://api.openalex.org/works?" + urllib.parse.urlencode(p))
        out = []
        for w in (r or {}).get("results", []):
            out.append({"title": w.get("title") or "", "year": w.get("publication_year"),
                        "families": [_norm((a.get("author") or {}).get("display_name", "").split(" ")[-1])
                                     for a in w.get("authorships", [])],
                        "doi": (w.get("doi") or "").replace("https://doi.org/", "") or None, "source": "openalex"})
        return out if r else None


def _from_crossref(m: dict) -> dict:
    y = None
    for k in ("published-print", "published-online", "issued", "created"):
        dp = (m.get(k) or {}).get("date-parts") or [[None]]
        if dp[0] and dp[0][0]:
            y = dp[0][0]
            break
    return {"title": " ".join(m.get("title") or []), "year": y,
            "families": [_norm(a.get("family") or a.get("name", "")) for a in m.get("author") or []],
            "volume": str(m.get("volume") or ""), "page": str(m.get("page") or "").split("-")[0],
            "doi": m.get("DOI"), "source": "crossref"}


def _author_agrees(item: dict, raw: str, rec: dict) -> bool:
    """True when one of the record's surnames appears in the reference. Reading the raw text, not only the
    parsed names, copes with 've'/'und' between names, missing commas and all-caps lists."""
    words = set(_norm(raw).split())
    fams = [w for f in rec["families"] for w in f.split() if len(w) > 2]
    if not fams:
        return True
    if any(f in words for f in fams):
        return True
    fam = _family(item)  # a typo in the surname: compare the parsed first author with each surname
    return bool(fam) and any(SequenceMatcher(None, fam, f).ratio() >= 0.8 for f in fams)


def _compare(item: dict, rec: dict, raw: str = "") -> tuple[float, list[str]]:
    """Title similarity, and the fields that disagree."""
    s = _sim(item.get("title", ""), rec["title"])
    issues = []
    if not _author_agrees(item, raw, rec):
        issues.append("author")
    y, ry = _year(item), rec.get("year")
    if y and ry and abs(int(ry) - y) > 1:  # online-first and print years often differ by one
        issues.append("year")
    return s, issues


def check_one(item: dict, raw: str, client: _Client) -> dict:
    out = {"reference": raw, "title": item.get("title")}
    if item.get("DOI"):
        rec = client.crossref_doi(item["DOI"])
        if rec == "missing":
            return {**out, "verdict": "bad_doi", "why": f"DOI {item['DOI']} is not registered"}
        if rec:
            s, issues = _compare(item, rec, raw)
            if s < 0.75 and item.get("title"):
                issues = ["title"] + issues
            if not issues:
                return {**out, "verdict": "ok", "doi": rec["doi"], "matched_title": rec["title"]}
            return {**out, "verdict": "mismatch", "doi": rec["doi"], "matched_title": rec["title"],
                    "why": "the DOI belongs to a different work" if "title" in issues
                    else f"the DOI's record has a different {' and '.join(issues)}"}
    if not item.get("title"):
        # Physics and chemistry styles often give no title: 'Noble, J., Nature, 211, 1263 (1966)'.
        # Match on volume, first page, year and author instead.
        vol, page = str(item.get("volume") or ""), str(item.get("page") or "").split("-")[0].split("–")[0].strip()
        if not (vol and page):
            return {**out, "verdict": "not_found", "why": "no title, volume or page could be read; check it by hand"}
        recs = client.crossref_search(raw)
        if recs is None:
            return {**out, "verdict": "not_found", "why": "the lookup service did not answer; try again"}
        for rec in recs:
            if rec.get("volume") == vol and rec.get("page") == page:
                _, issues = _compare(item, rec, raw)
                if not issues:
                    return {**out, "verdict": "ok", "doi": rec["doi"], "matched_title": rec["title"], "source": "crossref"}
        return {**out, "verdict": "not_found", "why": "no record with this volume and first page; check it by hand"}
    best, best_s, best_issues, looked, missed = None, 0.0, [], False, False
    for search in (lambda: client.crossref_search(raw), lambda: client.openalex_search(item["title"])):
        recs = search()
        if recs is None:
            missed = True
            continue
        looked = True
        for rec in recs:
            s, issues = _compare(item, rec, raw)
            # Copies of one paper (preprint, reprint, chapter) share a title: prefer the copy that fully agrees.
            if (s >= 0.9 and not issues, s) > (best_s >= 0.9 and not best_issues, best_s):
                best, best_s, best_issues = rec, s, issues
        if best_s >= 0.9 and not best_issues:
            break
    if not looked:
        return {**out, "verdict": "not_found", "why": "the lookup services did not answer; try again"}
    if best is not None and best_s >= 0.9:
        if not best_issues:
            return {**out, "verdict": "ok", "doi": best["doi"], "matched_title": best["title"], "source": best["source"]}
        if missed:  # the other service might hold the copy that agrees: don't accuse on half the evidence
            return {**out, "verdict": "not_found", "closest_title": best["title"],
                    "why": "a lookup service did not answer, so this could not be confirmed; try again later"}
        return {**out, "verdict": "mismatch", "doi": best["doi"], "matched_title": best["title"], "source": best["source"],
                "why": f"a work with this title exists, but with a different {' and '.join(best_issues)}"}
    return {**out, "verdict": "not_found", "closest_title": best["title"] if best else None,
            "why": "no published work with a close title; check it by hand"}


def check(items: list[dict], raws: list[str], mailto: str | None = None, timeout: int = 20, workers: int = 4,
          openalex_key: str | None = None) -> list[dict]:
    """Check parsed references (items, from Parser.parse) against their raw strings. See the module docstring."""
    client = _Client(mailto, timeout, openalex_key)
    with ThreadPoolExecutor(workers) as ex:
        return list(ex.map(lambda p: check_one(p[0], p[1], client), zip(items, raws)))


def report(results: list[dict]) -> str:
    mark = {"ok": "ok       ", "mismatch": "MISMATCH ", "bad_doi": "BAD DOI  ", "not_found": "NOT FOUND"}
    lines = []
    for i, r in enumerate(results, 1):
        lines.append(f"{i:>3}  {mark[r['verdict']]}  {r['reference'][:90]}")
        if r.get("why"):
            lines.append(f"     {'':10} {r['why']}" + (f": \"{r['matched_title'][:80]}\"" if r.get("matched_title") and r["verdict"] == "mismatch" else ""))
    n = {v: sum(r["verdict"] == v for r in results) for v in VERDICTS}
    lines.append("")
    lines.append(f"{n['ok']} ok, {n['mismatch']} mismatched, {n['bad_doi']} with an unregistered DOI, "
                 f"{n['not_found']} not found, out of {len(results)}.")
    if n["not_found"]:
        lines.append("Not found is not proof of a fake: theses, reports and old books are often unindexed.")
    return "\n".join(lines)
