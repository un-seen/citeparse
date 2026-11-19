"""citeparse: turn reference strings into CSL-JSON, and check them against Crossref.

    >>> from citeparse import Parser
    >>> p = Parser()                       # hedwigai/citeparse-32m by default
    >>> p.parse("[3] A. Vaswani et al., \"Attention is all you need,\" in NeurIPS, 2017, pp. 5998-6008.")
    {'author': [{'family': 'Vaswani', 'given': 'A.'}, {'literal': 'et al.'}], 'title': 'Attention is all you need', ...}
"""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from difflib import SequenceMatcher

__version__ = "0.1.0"
DEFAULT_MODEL = "hedwigai/citeparse-32m"

CSL_KEY = {"TITLE": "title", "CONTAINER": "container-title", "PUBLISHER": "publisher", "LOCATION": "publisher-place",
           "VOLUME": "volume", "ISSUE": "issue", "PAGES": "page", "DOI": "DOI", "URL": "URL", "ISBN": "ISBN",
           "EDITION": "edition", "NOTE": "note", "IDENTIFIER": "identifier"}
_ETAL = re.compile(r"^(et\.? al\.?|u\.\s*a\.|and others)$", re.I)


# ---------------------------------------------------------------- names
def split_names(s: str) -> list[dict]:
    """Split an author or editor list into CSL name objects. Handles 'Smith, J., Doe, A.', 'J. Smith, A. Doe and B. Roe',
    'Smith J, Doe A', 'Smith, John; Doe, Ann' and trailing 'et al.'."""
    s = re.sub(r"\s+", " ", s).strip().strip(",;:. ") + ("." if s.strip().endswith(".") else "")
    s = re.sub(r"\(eds?\.?\)|\beds?\.(?=\s|$)", "", s, flags=re.I).strip(" ,;")
    etal = False
    m = re.search(r",?\s*(et\.? al\.?|u\.\s*a\.|and others)\s*$", s, re.I)
    if m:
        etal, s = True, s[: m.start()].strip(" ,;")
    s = re.sub(r",?\s+(and|&|und|et)\s+", "; " if ";" in s else ", ", s)
    parts = [p.strip() for p in (s.split(";") if ";" in s else s.split(","))]
    parts = [p for p in parts if p]
    names = []

    def initials(x):  # 'J.', 'J. R.', 'JR', 'J.-P.', 'Ø.'
        toks = x.replace("-", " ").split()
        return bool(toks) and len(toks) <= 4 and all(
            re.fullmatch(r"[^\W\d_]{1,3}\.?|[^\W\d_]\.?[^\W\d_]\.?", t) and t.replace(".", "").isupper() for t in toks)

    def given_like(x):
        toks = x.split()
        return 1 <= len(toks) <= 3 and all(t[:1].isupper() for t in toks)

    i = 0
    while i < len(parts):
        p = parts[i]
        nxt = parts[i + 1] if i + 1 < len(parts) else None
        toks = p.split()
        if "," in p:                                                             # 'Smith, J.' inside a ';' list
            f, g = p.split(",", 1); names.append({"family": f.strip(), "given": g.strip()})
        elif nxt is not None and len(toks) == 1 and (initials(nxt) or (i == 0 and given_like(nxt))):
            names.append({"family": p, "given": nxt}); i += 2; continue          # 'Smith, J.' / 'Morris, Michael J.'
        elif len(toks) >= 2 and initials(" ".join(toks[1:])) and not initials(toks[0]):
            names.append({"family": toks[0], "given": " ".join(toks[1:])})     # 'Smith JR'
        elif len(toks) >= 2:
            k = len(toks) - 1                                                    # 'J. R. van der Berg'
            while k > 1 and toks[k - 1][:1].islower():
                k -= 1
            names.append({"family": " ".join(toks[k:]), "given": " ".join(toks[:k])})
        else:
            names.append({"literal": p})
        i += 1
    if etal:
        names.append({"literal": "et al."})
    return names


def _date(s: str) -> dict:
    y = re.search(r"\b(1[5-9]\d\d|20\d\d)\b", s)
    out = {"raw": s.strip()}
    if y:
        out["date-parts"] = [[int(y.group(1))]]
    return out


_DOI_RE = re.compile(r"10\.\d{4,9}/[^\s\"]+")


def find_doi(text: str) -> str | None:
    """The first well-formed DOI in `text`, bare or inside a doi.org URL or "doi:" prefix.

    No word boundary before "10.": a DOI glued to the digits in front of it
    ("...1995852402110.1002/mrm.1910340409") is still found. Trailing
    punctuation is dropped, and a closing bracket only when it has no opening
    one inside the DOI, so 10.1002/(SICI)1097-4636(199601)30:1<1::AID>3.0.CO;2-H
    keeps its own brackets. Plain text only: an HTML tag after a DOI is not cut."""
    m = _DOI_RE.search(text)
    if not m:
        return None
    d = m.group(0)
    pairs = {")": "(", "]": "[", "}": "{", ">": "<"}
    while d and d[-1] in ".,;:'’”" + "".join(pairs):
        o = pairs.get(d[-1])
        if o and d.count(o) >= d.count(d[-1]):
            break
        d = d[:-1]
    return d or None


def _doi(s: str) -> str | None:
    """A model span read as a DOI: kept only if it has a DOI's shape once its
    spaces are gone (a DOI broken across a line)."""
    return find_doi(re.sub(r"\s+", "", s))


def to_csl(text: str, spans: list[tuple[int, int, str]]) -> dict:
    """Spans [(start, end, LABEL)] -> CSL-JSON item."""
    by = {}
    for s, e, l in spans:
        by.setdefault(l, []).append(text[s:e].strip())
    item: dict = {}
    if "AUTHOR" in by:
        item["author"] = [n for a in by["AUTHOR"] for n in split_names(a)]
    if "EDITOR" in by:
        item["editor"] = [n for a in by["EDITOR"] for n in split_names(a)]
    if "DATE" in by:
        item["issued"] = _date(by["DATE"][0])
    for l, k in CSL_KEY.items():
        if l in by:
            v = by[l][0] if l in ("TITLE", "CONTAINER", "DOI") else " ".join(by[l])
            v = v.strip(" ,;:").strip("\"“”'‘’")
            if l == "TITLE":
                v = v.rstrip(".")
            if l == "DOI":
                v = _doi(v)
                if not v:
                    continue
            if l == "PAGES":
                v = v.replace("–", "-").replace("—", "-").replace(" ", "")
            item[k] = v
    # A DOI has a fixed shape, so the regex reads it better than the model,
    # which tends to label only a fragment of a doi.org URL ("https", "10.").
    # The model's span is kept only when the text holds no well-formed DOI
    # (a DOI broken across a line, which _doi rejoins).
    d = find_doi(text)
    if d and not (item.get("DOI", "").startswith(d) and len(item["DOI"]) > len(d)):
        item["DOI"] = d
    return item


# ---------------------------------------------------------------- model
class Parser:
    def __init__(self, model: str = DEFAULT_MODEL, device: str | None = None, max_length: int = 256):
        import torch
        from transformers import AutoModelForTokenClassification, AutoTokenizer
        self.torch = torch
        self.tok = AutoTokenizer.from_pretrained(model)
        self.model = AutoModelForTokenClassification.from_pretrained(model).eval()
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.model.to(self.device)
        self.id2label = self.model.config.id2label
        self.max_length = max_length

    def spans(self, texts: list[str], batch_size: int = 32) -> list[list[tuple[int, int, str]]]:
        out = []
        for i in range(0, len(texts), batch_size):
            chunk = texts[i:i + batch_size]
            enc = self.tok(chunk, truncation=True, max_length=self.max_length, padding=True,
                           return_offsets_mapping=True, return_tensors="pt")
            offs = enc.pop("offset_mapping").tolist()
            with self.torch.no_grad():
                pred = self.model(**{k: v.to(self.device) for k, v in enc.items()}).logits.argmax(-1).tolist()
            for t, p, o in zip(chunk, pred, offs):
                sp: list[list] = []
                for tag_i, (a, b) in zip(p, o):
                    if a == b:
                        continue
                    tag = self.id2label[tag_i]
                    if tag == "O":
                        continue
                    lab = tag[2:]
                    if sp and sp[-1][2] == lab and (tag.startswith("I-") or not t[sp[-1][1]:a].strip()) and a - sp[-1][1] <= 2:
                        sp[-1][1] = b
                    else:
                        sp.append([a, b, lab])
                out.append([tuple(x) for x in sp])
        return out

    def parse(self, text: str | list[str], batch_size: int = 32):
        single = isinstance(text, str)
        texts = [text] if single else list(text)
        items = [to_csl(t, s) for t, s in zip(texts, self.spans(texts, batch_size))]
        return items[0] if single else items


# ---------------------------------------------------------------- Crossref check
def _sim(a: str, b: str) -> float:
    n = lambda x: re.sub(r"[\W_]+", " ", (x or "").lower()).strip()
    return SequenceMatcher(None, n(a), n(b)).ratio()


def verify(item: dict, raw: str | None = None, mailto: str | None = None, timeout: int = 20) -> dict:
    """Look the reference up on Crossref. Returns {'status': 'found'|'doi_mismatch'|'doi_unknown'|'not_found', ...}.
    'not_found' means no Crossref record matches the title closely; many real books, theses and preprints are
    missing from Crossref, so treat it as 'check by hand', not as proof of a fake."""
    ua = {"User-Agent": f"citeparse/{__version__}" + (f" (mailto:{mailto})" if mailto else "")}

    def get(url):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=ua), timeout=timeout) as r:
                return json.load(r)["message"]
        except Exception:
            return None

    title = item.get("title", "")
    if item.get("DOI"):
        rec = get("https://api.crossref.org/works/" + urllib.parse.quote(item["DOI"]))
        if rec is None:
            return {"status": "doi_unknown", "doi": item["DOI"]}
        t = " ".join(rec.get("title") or [])
        s = _sim(title, t)
        return {"status": "found" if s > 0.8 or not title else "doi_mismatch", "doi": item["DOI"],
                "crossref_title": t, "title_similarity": round(s, 3)}
    q = raw or " ".join(str(v) for v in [title, item.get("container-title", "")])
    rec = get("https://api.crossref.org/works?rows=3&query.bibliographic=" + urllib.parse.quote(q[:400]))
    best = max(((_sim(title, " ".join(r.get("title") or [])), r) for r in (rec or {}).get("items", [])),
               default=(0, None), key=lambda x: x[0])
    if best[1] is not None and best[0] > 0.85:
        return {"status": "found", "doi": best[1].get("DOI"), "crossref_title": " ".join(best[1].get("title") or []),
                "title_similarity": round(best[0], 3)}
    return {"status": "not_found", "title_similarity": round(best[0], 3)}
