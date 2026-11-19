"""Field accuracy on wild.jsonl for GROBID and any of our models. usage: bench_wild.py [MODEL ...]"""
import json, re, sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from bench_grobid import call, fields as grobid_fields, year
from train_refparse import fields_from_spans, norm
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "citeparse"))
from citeparse import find_doi, to_csl

KEYS = ["TITLE", "CONTAINER", "DATE", "VOLUME", "ISSUE", "PAGES_FIRST", "DOI"]


def first_page(p):
    return norm(re.split(r"[-–—]", p or "")[0]).lstrip("0") if p else ""


def pred_from_raw(d):
    """d: field -> normalised string (as fields_from_spans / grobid_fields return)."""
    out = {k: d[k] for k in ("TITLE", "CONTAINER", "VOLUME", "ISSUE") if d.get(k)}
    if d.get("DATE"): out["DATE"] = year(d["DATE"])
    if d.get("PAGES"): out["PAGES_FIRST"] = d["PAGES"]  # already normalised; first page handled below
    if d.get("DOI"): out["DOI"] = re.sub(r"^(httpsdoiorg|httpdxdoiorg|doi)", "", d["DOI"])
    return out


def correct(k, g, p, row):
    if k not in p: return False
    if k == "CONTAINER": return p[k] in row["container_alts"]
    if k == "PAGES_FIRST": return p[k].lstrip("0").startswith(g.lstrip("0")) and len(p[k]) >= len(g.lstrip("0"))
    return p[k] == g


def score(rows, preds):
    hit, tot = Counter(), Counter()
    for r, p in zip(rows, preds):
        for k, g in r["gold"].items():
            tot[k] += 1; hit[k] += correct(k, g, p, r)
    res = {k: round(hit[k] / tot[k], 4) for k in KEYS if tot[k]}
    res["all_fields"] = round(sum(hit.values()) / sum(tot.values()), 4)
    res["refs_fully_right"] = round(sum(all(correct(k, g, p, r) for k, g in r["gold"].items()) for r, p in zip(rows, preds)) / len(rows), 4)
    return res, dict(tot)


if __name__ == "__main__":
    rows = [json.loads(l) for l in open("wild.jsonl")]
    # GROBID pages come raw; take the first page only
    with ThreadPoolExecutor(8) as ex:
        xs = list(ex.map(call, [r["text"] for r in rows]))
    gp = []
    for x in xs:
        d = (grobid_fields(x) or ({}, []))[0]
        m = re.search(r'<biblScope unit="page"(?: from="([^"]+)")?[^>]*>([^<]*)<', x or "")
        if m: d["PAGES"] = first_page(m.group(1) or m.group(2))
        else: d.pop("PAGES", None)
        gp.append(pred_from_raw(d))
    out = {}
    out["grobid-0.8.1-crf"], counts = score(rows, gp)
    # The same DOI regex citeparse uses, given to GROBID too, so the gap left is the model's
    gpr = []
    for r, p in zip(rows, gp):
        p = dict(p); d = find_doi(r["text"])
        if d: p["DOI"] = norm(d)
        gpr.append(p)
    out["grobid-0.8.1-crf+doi-regex"] = score(rows, gpr)[0]
    import torch
    from transformers import AutoTokenizer, AutoModelForTokenClassification
    from train_refparse import predict_spans
    for m in sys.argv[1:]:
        tok = AutoTokenizer.from_pretrained(m); mod = AutoModelForTokenClassification.from_pretrained(m).cuda()
        preds, preds_rx = [], []
        for r, sp in zip(rows, predict_spans(mod, tok, [r["text"] for r in rows])):
            raw = {}
            for s, e, l in sp:
                raw.setdefault(l, r["text"][s:e])
            d = {k: norm(v) for k, v in raw.items()}
            if "PAGES" in raw: d["PAGES"] = first_page(raw["PAGES"])
            preds.append(pred_from_raw(d))
            # citeparse's own DOI rule (to_csl): the regex over the text, the model's span as fallback
            doi = to_csl(r["text"], sp).get("DOI")
            d2 = {k: v for k, v in d.items() if k != "DOI"}
            if doi: d2["DOI"] = norm(doi)
            preds_rx.append(pred_from_raw(d2))
        out[m] = score(rows, preds)[0]
        out[m + "+doi-regex"] = score(rows, preds_rx)[0]
    print("n", len(rows), "fields", counts)
    for k, v in out.items(): print(k, v)
    json.dump({"n": len(rows), "counts": counts, "results": out}, open("bench_wild.json", "w"), indent=1)
