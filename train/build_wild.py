"""'In the wild' test set: unstructured reference strings that publishers deposited with Crossref, each linked to
the DOI it cites. Gold fields come from the cited DOI's Crossref record, kept only where the value is actually
present in the string. Cited DOIs that appear in our synthetic training records are dropped.
-> wild.jsonl rows {"text", "gold": {TITLE, CONTAINER, DATE, VOLUME, ISSUE, PAGES, DOI}, "container_alts": [...]}"""
import json, random, re, time, urllib.request, urllib.parse, sys
from concurrent.futures import ThreadPoolExecutor

UA = {"User-Agent": "reference-parser-benchmark/0.1"}
N = int(sys.argv[1]) if len(sys.argv) > 1 else 1500
norm = lambda s: re.sub(r"[\W_]+", "", (s or "").lower())


def get(url):
    for i in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                return json.load(r)["message"]
        except Exception:
            time.sleep(2 * (i + 1))
    return None


train_dois = {json.loads(l).get("DOI", "").lower() for l in open("crossref.jsonl")}
cands = []
R = random.Random(0)
while len(cands) < N * 3:
    m = get("https://api.crossref.org/works?filter=has-references:true,type:journal-article&sample=100&select=DOI,reference")
    for w in (m or {}).get("items", []):
        refs = [x for x in w.get("reference", []) if x.get("unstructured") and x.get("DOI")]
        R.shuffle(refs)
        for x in refs[:3]:  # at most 3 per citing paper, so one publisher's style doesn't dominate
            if x["DOI"].lower() not in train_dois and 30 < len(x["unstructured"]) < 600:
                cands.append(x)
    print("cands", len(cands), flush=True)


def gold(x):
    rec = get("https://api.crossref.org/works/" + urllib.parse.quote(x["DOI"]))
    if not rec:
        return None
    s = re.sub(r"<[^>]+>", "", x["unstructured"]); ns = norm(s)
    g, alts = {}, []
    t = " ".join(rec.get("title") or [])
    if t and norm(t) in ns: g["TITLE"] = norm(t)
    conts = (rec.get("container-title") or []) + (rec.get("short-container-title") or [])
    hits = [norm(c) for c in conts if c and norm(c) in ns]
    if hits: g["CONTAINER"] = max(hits, key=len); alts = hits
    dp = ((rec.get("issued") or {}).get("date-parts") or [[None]])[0]
    if dp and dp[0] and str(dp[0]) in s: g["DATE"] = str(dp[0])
    for k, f in (("volume", "VOLUME"), ("issue", "ISSUE")):
        v = rec.get(k)
        if v and re.search(r"(?<![\w])" + re.escape(v) + r"(?![\w])", s): g[f] = norm(v)
    p = (rec.get("page") or "").split("-")[0]
    if p and re.search(r"(?<!\d)" + re.escape(p) + r"(?!\d)", s): g["PAGES_FIRST"] = norm(p)
    if x["DOI"].lower() in s.lower(): g["DOI"] = norm(x["DOI"])
    if len(g) < 3:
        return None
    return {"text": s.strip(), "gold": g, "container_alts": alts, "doi": x["DOI"]}


with ThreadPoolExecutor(4) as ex:
    rows = [r for r in ex.map(gold, cands) if r]
R.shuffle(rows)
rows = rows[:N]
with open("wild.jsonl", "w") as f:
    for r in rows: f.write(json.dumps(r, ensure_ascii=False) + "\n")
from collections import Counter
print("rows", len(rows), Counter(k for r in rows for k in r["gold"]))
