"""Score GROBID's processCitation on the same held-out references, with the same field normaliser.
GROBID returns TEI fields, not character spans, so we compare normalised field strings directly."""
import json, re, sys, hashlib, urllib.request, urllib.parse
import xml.etree.ElementTree as ET
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from train_refparse import merge_lists, is_test_file, fields_from_spans, norm

NS = {}


def call(text):
    data = urllib.parse.urlencode({"citations": text, "consolidateCitations": "0"}).encode()
    for _ in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:8070/api/processCitation", data=data,
                                        headers={"Accept": "application/xml"}), timeout=60) as r:
                return r.read().decode()
        except Exception:
            pass
    return ""


def fields(xml):
    if not xml.strip():
        return {}
    xml = re.sub(r'\sxmlns="[^"]+"', "", xml)
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return {}
    f = {}
    a = root.find("analytic", NS); m = root.find("monogr", NS)
    def names(el):
        out = []
        for pn in el.findall(".//persName", NS) if el is not None else []:
            out.append(" ".join(x.text or "" for x in pn))
        return out
    auth = names(a) if a is not None and a.findall(".//author", NS) else names(m.find("author/..", NS) if m is not None else None)
    t_a = a.find("title", NS) if a is not None else None
    t_m = m.find("title", NS) if m is not None else None
    if t_a is not None and t_a.text:
        f["TITLE"] = t_a.text
        if t_m is not None and t_m.text: f["CONTAINER"] = t_m.text
    elif t_m is not None and t_m.text:
        f["CONTAINER" if t_m.get("level") in ("j", "s") else "TITLE"] = t_m.text
    imp = m.find("imprint", NS) if m is not None else None
    if imp is not None:
        d = imp.find("date", NS)
        if d is not None: f["DATE"] = d.get("when", d.text or "")[:4]
        for sc in imp.findall("biblScope", NS):
            u = sc.get("unit")
            if u == "volume": f["VOLUME"] = sc.text or ""
            if u == "issue": f["ISSUE"] = sc.text or ""
            if u == "page":
                f["PAGES"] = sc.text or (f"{sc.get('from','')}-{sc.get('to','')}".strip("-"))
        p = imp.find("publisher", NS)
        if p is not None: f["PUBLISHER"] = p.text or ""
    for idno in root.iter("idno"):
        if idno.get("type") == "DOI": f["DOI"] = idno.text or ""
    return {k: norm(v) for k, v in f.items() if v}, auth


def year(d):
    y = re.search(r"(1[5-9]\d\d|20\d\d)", d or ""); return y.group(1) if y else d


KEYS = ["TITLE", "CONTAINER", "DATE", "VOLUME", "ISSUE", "PAGES", "PUBLISHER", "DOI"]


def score(golds, preds):
    tp, fp, fn = Counter(), Counter(), Counter()
    for g, p in zip(golds, preds):
        for k in KEYS:
            same = k in g and k in p and (g[k] == p[k] or (k == "PAGES" and g[k].lstrip("0") == p[k].lstrip("0")))
            if same: tp[k] += 1
            else:
                if k in p: fp[k] += 1
                if k in g: fn[k] += 1
    res = {}
    for k in KEYS:
        pr = tp[k] / max(1, tp[k] + fp[k]); rc = tp[k] / max(1, tp[k] + fn[k])
        res[k] = round(2 * pr * rc / max(1e-9, pr + rc), 4)
    T, F, N = sum(tp.values()), sum(fp.values()), sum(fn.values())
    mp, mr = T / max(1, T + F), T / max(1, T + N)
    res["micro"] = round(2 * mp * mr / max(1e-9, mp + mr), 4)
    return res


if __name__ == "__main__":
    gc = [merge_lists(json.loads(l)) for l in open("grobid_corpus.jsonl")]
    rows = [r for r in gc if is_test_file(r["src"])]
    golds = []
    for r in rows:
        g = fields_from_spans(r["text"], r["spans"]); g.pop("AUTHOR", None); g.pop("EDITOR", None)
        if "DATE" in g: g["DATE"] = year(g["DATE"])
        golds.append(g)
    out = {}
    with ThreadPoolExecutor(8) as ex:
        xmls = list(ex.map(call, [r["text"] for r in rows]))
    out["grobid-0.8.1-crf"] = score(golds, [(fields(x) or ({}, []))[0] for x in xmls])
    import torch
    from transformers import AutoTokenizer, AutoModelForTokenClassification
    from train_refparse import predict_spans
    for m in sys.argv[1:]:
        tok = AutoTokenizer.from_pretrained(m); mod = AutoModelForTokenClassification.from_pretrained(m).cuda()
        preds = []
        for r, sp in zip(rows, predict_spans(mod, tok, [r["text"] for r in rows])):
            p = fields_from_spans(r["text"], sp); p.pop("AUTHOR", None); p.pop("EDITOR", None)
            if "DATE" in p: p["DATE"] = year(p["DATE"])
            preds.append(p)
        out[m] = score(golds, preds)
    for k, v in out.items():
        print(k, v)
    json.dump(out, open("bench_heldout.json", "w"), indent=1)
