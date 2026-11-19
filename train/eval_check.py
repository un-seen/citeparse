"""Check-mode benchmark on citeparse-wild-700: real references (DOI removed) vs title-swapped fakes."""
import json, re, sys, collections
from citeparse import Parser
from citeparse.check import check
rows = [json.loads(l) for l in open("/home/shkr/oss-models/refparse/wild.jsonl")]
strip = lambda t: re.sub(r"(https?://(dx\.)?doi\.org/|doi:\s*|DOI:?\s*)?10\.\d{4,9}/\S+", "", t).strip(" .,;")
p = Parser()
real = [strip(r["text"]) for r in rows[:100]]
src = [strip(r["text"]) for r in rows[100:250]]
sp = p.spans(src)
def title(t, s):
    ts = [t[a:b] for a, b, l in s if l == "TITLE"]
    return ts[0] if ts else None
fakes = []
for i in range(100):
    a, b = i, i + 50          # put the title of reference b into reference a
    ta, tb = title(src[a], sp[a]), title(src[b], sp[b])
    if ta and tb and len(ta) > 15 and len(tb) > 15:
        fakes.append(src[a].replace(ta, tb, 1))
texts = real + fakes
res = check(p.parse(texts), texts, mailto=None)
R, F = res[:len(real)], res[len(real):]
cr, cf = collections.Counter(r["verdict"] for r in R), collections.Counter(r["verdict"] for r in F)
print("real", len(R), dict(cr)); print("fake", len(F), dict(cf))
print("real passed (ok):", round(cr["ok"]/len(R),3), " fakes flagged (not ok):", round(1-cf["ok"]/len(F),3))
json.dump({"real": R, "fake": F}, open("eval_check.json","w"), ensure_ascii=False, indent=1)
