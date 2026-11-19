"""Random Crossref records (CC0 metadata) by type -> crossref.jsonl"""
import json, time, urllib.request, sys, random
from concurrent.futures import ThreadPoolExecutor
UA = {"User-Agent": "reference-parser-research/0.1"}
# (type, calls of 100 random records)
PLAN = [("journal-article", 900), ("proceedings-article", 250), ("book-chapter", 200), ("book", 120),
        ("posted-content", 120), ("monograph", 40), ("report", 40), ("dissertation", 40), ("edited-book", 30),
        ("reference-entry", 20), ("dataset", 20), ("standard", 10)]
KEEP = ["DOI", "type", "title", "subtitle", "author", "editor", "container-title", "short-container-title", "publisher",
        "publisher-location", "issued", "published", "volume", "issue", "page", "article-number", "ISBN", "ISSN",
        "edition-number", "event", "institution", "URL", "language"]
def get(t):
    for i in range(5):
        try:
            u = f"https://api.crossref.org/works?filter=type:{t}&sample=100"
            with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=60) as r:
                return t, json.load(r)["message"]["items"]
        except Exception as e:
            time.sleep(3 * (i + 1))
    return t, []
jobs = [t for t, n in PLAN for _ in range(n)]
random.shuffle(jobs)
n = 0
with open("crossref.jsonl", "a") as f, ThreadPoolExecutor(3) as ex:
    for k, (t, items) in enumerate(ex.map(get, jobs)):
        for it in items:
            f.write(json.dumps({x: it[x] for x in KEEP if x in it}) + "\n"); n += 1
        if k % 50 == 0: print(k, len(jobs), n, flush=True)
