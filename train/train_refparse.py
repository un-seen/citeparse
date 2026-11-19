"""Token-classification reference parser.
usage: train_refparse.py BASE OUT [--synthetic synth.jsonl] [--epochs 2] [--bs 32] [--lr 5e-5]
Trains on synthetic Crossref renders + GROBID corpus (files hashed into train/test); evaluates field-level on
GROBID's evaluation set and the held-out corpus files."""
import argparse, json, random, re, hashlib, os, sys
from collections import defaultdict, Counter
import numpy as np, torch
from transformers import (AutoTokenizer, AutoModelForTokenClassification, TrainingArguments, Trainer,
                          DataCollatorForTokenClassification)
from datasets import Dataset

LABELS = ["AUTHOR", "EDITOR", "TITLE", "CONTAINER", "PUBLISHER", "LOCATION", "DATE", "VOLUME", "ISSUE",
          "PAGES", "DOI", "URL", "ISBN", "EDITION", "IDENTIFIER", "NOTE"]
TAGS = ["O"] + [f"{p}-{l}" for l in LABELS for p in ("B", "I")]
T2I = {t: i for i, t in enumerate(TAGS)}


def merge_lists(row):
    """Join adjacent AUTHOR (or EDITOR) spans separated only by separators into one list span, as GROBID does."""
    t, sp = row["text"], sorted(row["spans"])
    out = []
    for s, e, l in sp:
        if out and out[-1][2] == l and l in ("AUTHOR", "EDITOR") and re.fullmatch(r"[\s,;&.]*(and|&|und|et)?[\s,;&.]*", t[out[-1][1]:s]):
            out[-1][1] = e
        else:
            out.append([s, e, l])
    return {**row, "spans": out}


def is_test_file(src):
    return int(hashlib.md5(src.encode()).hexdigest(), 16) % 10 == 0


def encode(rows, tok, maxlen=256):
    enc = tok([r["text"] for r in rows], truncation=True, max_length=maxlen, return_offsets_mapping=True)
    labels = []
    for r, offs in zip(rows, enc["offset_mapping"]):
        lab, prev = [], None
        for (a, b) in offs:
            if a == b:
                lab.append(-100); continue
            # skip leading whitespace in token
            while a < b and r["text"][a].isspace():
                a += 1
            tag = "O"; cur = None
            for i, (s, e, l) in enumerate(r["spans"]):
                if s <= a < e:
                    cur = i; tag = ("I-" if prev == i else "B-") + l; break
            prev = cur
            lab.append(T2I[tag])
        labels.append(lab)
    enc.pop("offset_mapping")
    return Dataset.from_dict({**enc, "labels": labels})


def norm(s):
    s = s.lower()
    s = re.sub(r"^(https?://(dx\.)?doi\.org/|doi:\s*)", "", s)
    return re.sub(r"[\W_]+", "", s)


def fields_from_spans(text, spans):
    f = defaultdict(list)
    for s, e, l in spans:
        f[l].append(text[s:e])
    return {k: norm(" ".join(v)) for k, v in f.items()}


def predict_spans(model, tok, texts, bs=64, maxlen=256):
    model.eval(); out = []
    dev = next(model.parameters()).device
    for i in range(0, len(texts), bs):
        chunk = texts[i:i + bs]
        enc = tok(chunk, truncation=True, max_length=maxlen, return_offsets_mapping=True, padding=True, return_tensors="pt")
        offs = enc.pop("offset_mapping")
        with torch.no_grad():
            logits = model(**{k: v.to(dev) for k, v in enc.items()}).logits
        pred = logits.argmax(-1).cpu().numpy()
        for t, p, o in zip(chunk, pred, offs.numpy()):
            spans = []
            for tag_i, (a, b) in zip(p, o):
                if a == b:
                    continue
                tag = TAGS[tag_i]
                if tag == "O":
                    continue
                l = tag[2:]
                if spans and spans[-1][2] == l and (tag.startswith("I-") or re.fullmatch(r"\s*", t[spans[-1][1]:a])) and a - spans[-1][1] <= 2:
                    spans[-1][1] = b
                else:
                    spans.append([a, b, l])
            out.append(spans)
    return out


def field_scores(gold_rows, pred_spans):
    tp, fp, fn = Counter(), Counter(), Counter()
    for r, ps in zip(gold_rows, pred_spans):
        g = fields_from_spans(r["text"], r["spans"]); p = fields_from_spans(r["text"], ps)
        for k in set(g) | set(p):
            if k in g and k in p and g[k] == p[k]:
                tp[k] += 1
            else:
                if k in p: fp[k] += 1
                if k in g: fn[k] += 1
    res = {}
    for k in sorted(set(tp) | set(fn)):
        pr = tp[k] / max(1, tp[k] + fp[k]); rc = tp[k] / max(1, tp[k] + fn[k])
        res[k] = {"p": round(pr, 4), "r": round(rc, 4), "f1": round(2 * pr * rc / max(1e-9, pr + rc), 4), "n": tp[k] + fn[k]}
    T, F, N = sum(tp.values()), sum(fp.values()), sum(fn.values())
    mp, mr = T / max(1, T + F), T / max(1, T + N)
    res["micro"] = {"p": round(mp, 4), "r": round(mr, 4), "f1": round(2 * mp * mr / max(1e-9, mp + mr), 4)}
    main = [k for k in ("AUTHOR", "TITLE", "CONTAINER", "DATE", "VOLUME", "ISSUE", "PAGES") if k in res]
    res["main_macro_f1"] = round(float(np.mean([res[k]["f1"] for k in main])), 4)
    return res


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("base"); ap.add_argument("out")
    ap.add_argument("--synthetic", default="synth.jsonl"); ap.add_argument("--nsynth", type=int, default=300000)
    ap.add_argument("--grobid_repeat", type=int, default=4)
    ap.add_argument("--epochs", type=float, default=2); ap.add_argument("--bs", type=int, default=32)
    ap.add_argument("--lr", type=float, default=5e-5); ap.add_argument("--eval_only", action="store_true")
    a = ap.parse_args()
    R = random.Random(0)
    gc = [merge_lists(json.loads(l)) for l in open("grobid_corpus.jsonl")]
    ge = [merge_lists(json.loads(l)) for l in open("grobid_eval.jsonl")]
    _n = lambda t: re.sub(r"\W+", "", t.lower())
    g_test0 = [r for r in gc if is_test_file(r["src"])]
    test_texts = {_n(r["text"]) for r in ge + g_test0}  # GROBID's eval set is copied inside its corpus
    g_train = [r for r in gc if not is_test_file(r["src"]) and _n(r["text"]) not in test_texts]
    g_test = [r for r in gc if is_test_file(r["src"])]
    tok = AutoTokenizer.from_pretrained(a.base if not a.eval_only else a.out)
    if not a.eval_only:
        syn = []
        for i, l in enumerate(open(a.synthetic)):
            if i >= a.nsynth: break
            syn.append(merge_lists(json.loads(l)))
        train_rows = syn + g_train * a.grobid_repeat
        R.shuffle(train_rows)
        print("train rows", len(train_rows), "grobid train", len(g_train), "grobid heldout", len(g_test), "eval", len(ge))
        ds = encode(train_rows, tok)
        model = AutoModelForTokenClassification.from_pretrained(a.base, num_labels=len(TAGS),
                    id2label=dict(enumerate(TAGS)), label2id=T2I)
        args = TrainingArguments(a.out + "_ckpt", per_device_train_batch_size=a.bs, learning_rate=a.lr,
                                 num_train_epochs=a.epochs, warmup_steps=0.05, lr_scheduler_type="cosine",
                                 weight_decay=0.01, bf16=True, logging_steps=100, save_strategy="no", report_to=[],
                                 dataloader_num_workers=2, seed=0)
        Trainer(model=model, args=args, train_dataset=ds,
                data_collator=DataCollatorForTokenClassification(tok)).train()
        model.save_pretrained(a.out); tok.save_pretrained(a.out)
    model = AutoModelForTokenClassification.from_pretrained(a.out).cuda()
    res = {}
    for name, rows in (("grobid_eval", ge), ("grobid_heldout", g_test)):
        res[name] = field_scores(rows, predict_spans(model, tok, [r["text"] for r in rows]))
        print(name, "micro", res[name]["micro"], "main_macro_f1", res[name]["main_macro_f1"])
    json.dump(res, open(os.path.join(a.out, "eval.json"), "w"), indent=1)
