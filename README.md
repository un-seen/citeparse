# citeparse

citeparse turns reference strings into structured records. It reads one reference per line and writes CSL-JSON or BibTeX. A small local model does the work, so nothing leaves your machine unless you ask it to check a record against Crossref.

```bash
pip install citeparse
citeparse refs.txt            # CSL-JSON, one record per line
citeparse refs.txt --bibtex   # BibTeX
citeparse refs.txt --verify --mailto you@example.org   # also look each one up on Crossref
```

```python
from citeparse import Parser

p = Parser()  # hedwigai/citeparse-32m; pass "hedwigai/citeparse-150m" for the larger model
p.parse('K. He, X. Zhang, S. Ren, and J. Sun, "Deep residual learning for image recognition," '
        'in Proc. CVPR, 2016, pp. 770-778. doi:10.1109/CVPR.2016.90')
# {'author': [{'family': 'He', 'given': 'K.'}, ...], 'title': 'Deep residual learning for image recognition',
#  'container-title': 'CVPR', 'issued': {'date-parts': [[2016]]}, 'page': '770-778', 'DOI': '10.1109/CVPR.2016.90'}
```

## How good is it?

We scored it on 700 real references taken from Crossref. Each one cites a DOI, so the cited work's own Crossref record is the answer key. None of these DOIs were in our training data. We gave GROBID the same DOI rule that citeparse uses, so the DOI column is equal and the rest of the gap comes from the models.

| Parser | All fields | References fully right | Title | Container | Volume | Issue | First page | DOI |
|---|---|---|---|---|---|---|---|---|
| GROBID 0.8.1 (CRF) | 0.911 | 71.1% | 0.882 | 0.805 | 0.908 | 0.803 | 0.953 | 0.994 |
| citeparse-32m | 0.939 | 80.3% | 0.921 | 0.858 | 0.956 | 0.841 | 0.968 | 0.988 |
| citeparse-150m | **0.952** | **83.4%** | **0.934** | **0.878** | **0.966** | **0.861** | **0.982** | **0.994** |

GROBID still wins on its own held-out citations (0.943 against 0.890 for citeparse-150m). Those citations come from the same sources as GROBID's training data. We report both results.

Speed on CPU (8 threads): citeparse-32m parses about 118 references a second, and citeparse-150m about 20.

## Fields

AUTHOR, EDITOR, TITLE, CONTAINER, DATE, VOLUME, ISSUE, PAGES, PUBLISHER, LOCATION, EDITION, DOI, URL, ISBN, IDENTIFIER, NOTE. Names are split into family and given parts. DOIs are read with a regular expression, because a DOI has a fixed shape; the model's DOI span is used only when the text has no well-formed DOI.

## Models and data

- [hedwigai/citeparse-32m](https://huggingface.co/hedwigai/citeparse-32m): the default, from `jhu-clsp/ettin-encoder-32m`.
- [hedwigai/citeparse-150m](https://huggingface.co/hedwigai/citeparse-150m): from `jhu-clsp/ettin-encoder-150m`.
- [hedwigai/citeparse-wild-700](https://huggingface.co/datasets/hedwigai/citeparse-wild-700): the benchmark above.

The models were trained on GROBID's citation corpus (Apache-2.0), with its evaluation files and any reference that also appears in them removed, and on Crossref records (CC0) written out in 11 citation styles. The code to rebuild the data, train and benchmark is in `train/`.

## License

Apache-2.0 for the code and the models.
