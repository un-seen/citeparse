"""citeparse refs.txt [--bibtex] [--verify]     parse one reference per line ('-' = stdin)
citeparse check refs.txt [--json]             flag references that point to no real work"""
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


def _lines(path):
    return [l.strip() for l in (sys.stdin if path == "-" else open(path, encoding="utf-8")) if l.strip()]


def main_check(argv):
    from .check import check, report
    ap = argparse.ArgumentParser(prog="citeparse check", description="Flag references that point to no real work.")
    ap.add_argument("file", help="one reference per line, or '-' for stdin")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--mailto", help="your email, sent to Crossref and OpenAlex so they can reach you")
    ap.add_argument("--json", action="store_true", help="one JSON result per line")
    a = ap.parse_args(argv)
    lines = _lines(a.file)
    res = check(Parser(a.model).parse(lines), lines, a.mailto)
    if a.json:
        for r in res:
            print(json.dumps(r, ensure_ascii=False))
    else:
        print(report(res))
    sys.exit(1 if any(r["verdict"] in ("mismatch", "bad_doi") for r in res) else 0)


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "check":
        return main_check(sys.argv[2:])
    ap = argparse.ArgumentParser(prog="citeparse", epilog="To flag fake or wrong references: citeparse check refs.txt")
    ap.add_argument("file"); ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--verify", action="store_true", help="look each reference up on Crossref")
    ap.add_argument("--mailto", help="your email, sent to Crossref's polite pool")
    ap.add_argument("--bibtex", action="store_true")
    a = ap.parse_args()
    lines = _lines(a.file)
    items = Parser(a.model).parse(lines)
    for i, (raw, it) in enumerate(zip(lines, items)):
        if a.verify:
            it["_check"] = verify(it, raw, a.mailto)
        print(bibtex(it, i) if a.bibtex else json.dumps(it, ensure_ascii=False))


if __name__ == "__main__":
    main()
