"""citeparse refs.txt [--model hedwigai/citeparse-32m] [--verify] [--bibtex]  (one reference per line; '-' = stdin)"""
import argparse, json, sys
from . import Parser, verify, DEFAULT_MODEL


def bibtex(item, i):
    typ = "article" if item.get("volume") or item.get("issue") else "inproceedings" if item.get("container-title") else "misc"
    names = " and ".join(f"{a['family']}, {a.get('given','')}".strip(", ") if "family" in a else "others"
                         for a in item.get("author", []))
    year = (item.get("issued", {}).get("date-parts") or [[None]])[0][0]
    fam = (item.get("author") or [{}])[0].get("family", "ref")
    f = {"author": names, "title": item.get("title"), "journal" if typ == "article" else "booktitle": item.get("container-title"),
         "year": year, "volume": item.get("volume"), "number": item.get("issue"), "pages": item.get("page"),
         "publisher": item.get("publisher"), "doi": item.get("DOI")}
    body = ",\n".join(f"  {k} = {{{v}}}" for k, v in f.items() if v)
    return f"@{typ}{{{fam}{year or ''}_{i},\n{body}\n}}"


def main():
    ap = argparse.ArgumentParser(prog="citeparse")
    ap.add_argument("file"); ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--verify", action="store_true", help="look each reference up on Crossref")
    ap.add_argument("--mailto", help="your email, sent to Crossref's polite pool")
    ap.add_argument("--bibtex", action="store_true")
    a = ap.parse_args()
    lines = [l.strip() for l in (sys.stdin if a.file == "-" else open(a.file, encoding="utf-8")) if l.strip()]
    items = Parser(a.model).parse(lines)
    for i, (raw, it) in enumerate(zip(lines, items)):
        if a.verify:
            it["_check"] = verify(it, raw, a.mailto)
        print(bibtex(it, i) if a.bibtex else json.dumps(it, ensure_ascii=False))


if __name__ == "__main__":
    main()
