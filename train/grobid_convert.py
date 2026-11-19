"""GROBID TEI citation corpus -> {"text","spans"} rows with our labels. Usage: grobid_convert.py DIR out.jsonl"""
import sys, os, json, re
import xml.etree.ElementTree as ET
NS = "{http://www.tei-c.org/ns/1.0}"
def lab(el, has_a):
    tag = el.tag.replace(NS, ""); a = el.attrib
    t = a.get("type", ""); lv = a.get("level", ""); u = a.get("unit", "")
    if tag == "author": return "AUTHOR"
    if tag == "editor": return "EDITOR"
    if tag == "title":
        if lv == "a": return "TITLE"
        if lv == "m": return "CONTAINER" if has_a else "TITLE"
        return "CONTAINER"  # j, s
    if tag == "date": return "DATE"
    if tag == "biblScope":
        k = u or t
        return {"volume": "VOLUME", "vol": "VOLUME", "issue": "ISSUE", "page": "PAGES", "pp": "PAGES"}.get(k, "NOTE")
    if tag == "publisher": return "PUBLISHER"
    if tag == "pubPlace": return "LOCATION"
    if tag == "orgName": return "AUTHOR" if t == "collaboration" else "PUBLISHER"
    if tag == "idno":
        t = t.lower()
        return {"doi": "DOI", "isbn": "ISBN"}.get(t, "IDENTIFIER")
    if tag == "ptr": return "URL"
    if tag == "note": return "NOTE"
    if tag == "edition": return "EDITION"
    return None
def walk(el, buf, spans, has_a, top=True):
    if not top:
        l = lab(el, has_a)
    else:
        l = None
    start = len("".join(buf))
    if el.tag.replace(NS, "") == "lb":
        buf.append(" ")
    if el.text: buf.append(el.text)
    for ch in el:
        walk(ch, buf, spans, has_a, top=False)
        if ch.tail: buf.append(ch.tail)
    end = len("".join(buf))
    if l and end > start:
        spans.append([start, end, l])
def conv(path):
    raw = open(path, encoding="utf-8").read()
    raw = re.sub(r'xmlns="[^"]+"', "", raw, count=1)
    root = ET.fromstring(raw)
    out = []
    for b in root.iter("bibl"):
        has_a = any(t.attrib.get("level") == "a" for t in b.iter("title"))
        buf, spans = [], []
        walk(b, buf, spans, has_a)
        text = "".join(buf)
        # collapse whitespace while remapping
        new, mp = [], []
        prev_space = True
        for ch in text:
            mp.append(len(new))
            if ch.isspace():
                if not prev_space: new.append(" ")
                prev_space = True
            else:
                new.append(ch); prev_space = False
        mp.append(len(new))
        t2 = "".join(new).rstrip()
        sp = []
        for s, e, l in spans:
            s2, e2 = mp[s], min(mp[e], len(t2))
            while s2 < e2 and t2[s2] == " ": s2 += 1
            while e2 > s2 and t2[e2 - 1] == " ": e2 -= 1
            if e2 > s2: sp.append([s2, e2, l])
        sp = [x for x in sp if not any(y is not x and y[0] <= x[0] and x[1] <= y[1] and y[1]-y[0] > x[1]-x[0] for y in sp)]
        if t2: out.append({"text": t2, "spans": sorted(sp), "src": os.path.basename(path)})
    return out
if __name__ == "__main__":
    d, dst = sys.argv[1], sys.argv[2]
    rows = []
    for f in sorted(os.listdir(d)):
        if f.endswith(".xml"): rows += conv(os.path.join(d, f))
    with open(dst, "w") as o:
        for r in rows: o.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(len(rows))
