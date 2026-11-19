# Rebuilding citeparse

1. `python fetch_crossref.py` — random Crossref records (CC0) into crossref.jsonl.
2. `python grobid_convert.py <grobid>/grobid-trainer/resources/dataset/citation/corpus grobid_corpus.jsonl` and the same for `evaluation` into grobid_eval.jsonl.
3. `python train_refparse.py jhu-clsp/ettin-encoder-32m out/refparse-32m` — renders Crossref records in 11 styles (render.py), drops every GROBID evaluation reference from training, trains, and scores.
4. `python build_wild.py` then `python bench_wild.py out/refparse-32m` — the 700-reference wild benchmark. `bench_grobid.py` and `bench_wild.py` expect a GROBID 0.8.1 server on 127.0.0.1:8070 (`docker run -p 8070:8070 lfoppiano/grobid:0.8.1`).
