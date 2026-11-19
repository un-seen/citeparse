# citeparse

citeparse turns reference strings into structured records. It reads one reference per line and writes CSL-JSON or BibTeX. A small local model does the work, so nothing leaves your machine unless you ask it to check a record against Crossref.

**Try it in your browser:** [huggingface.co/spaces/hedwigai/citeparse](https://huggingface.co/spaces/hedwigai/citeparse). The model runs on the page, so nothing you paste is uploaded.

```bash
pip install citeparse
citeparse refs.txt            # CSL-JSON, one record per line
citeparse refs.txt --bibtex   # BibTeX
citeparse check refs.txt      # flag references that point to no real work
```

```python
from citeparse import Parser

p = Parser()  # hedwigai/citeparse-32m; pass "hedwigai/citeparse-150m" for the larger model
p.parse('K. He, X. Zhang, S. Ren, and J. Sun, "Deep residual learning for image recognition," '
        'in Proc. CVPR, 2016, pp. 770-778. doi:10.1109/CVPR.2016.90')
# {'author': [{'family': 'He', 'given': 'K.'}, ...], 'title': 'Deep residual learning for image recognition',
#  'container-title': 'CVPR', 'issued': {'date-parts': [[2016]]}, 'page': '770-778', 'DOI': '10.1109/CVPR.2016.90'}
```

## Checking a reference list

`citeparse check` looks for citations that point to no real work, such as references invented by a language model. Each reference is parsed on your machine. Its DOI is then looked up on Crossref and DataCite; a reference without one is searched on Crossref, and on OpenAlex when there is budget. A match needs the title, a surname and the year to agree.

```
$ citeparse check refs.txt
  1  ok         K. He, X. Zhang, S. Ren, and J. Sun, "Deep residual learning for image recognition," in Pr
  2  NOT FOUND  Smith, J. A., & Patel, R. (2021). Recursive attention gating for low-resource legal summar
                no published work with a close title; check it by hand
  3  MISMATCH   Hinton, G. (2015). Deep residual learning for image recognition. Nature, 521, 436-444. htt
                the DOI's record has a different author: "Deep Residual Learning for Image Recognition"
  4  BAD DOI    Lee, M., & Gomez, T. (2020). Neural citation graphs for clinical trial retrieval. Bioinfor
                DOI 10.1093/bioinformatics/btz99999 is not registered
```

How well does it work? We ran it on 100 real references from the benchmark below, with their DOIs removed so that each had to be found by search, and on 83 fakes made by putting one reference's title on another's authors and year. Crossref was the only index (no OpenAlex key).

| | Matched (ok) | Check by hand (not found) | Accused (mismatch or bad DOI) |
|---|---|---|---|
| 100 real references | 89 | 11 | 0 |
| 83 fakes | 3 | 80 | 0 |

No real reference was accused. The 11 left to check by hand are mostly old physics references with no title, an Italian law chapter, a Russian book and one reference whose title is miswritten. The script is `train/eval_check.py`.

The command exits with status 1 when a reference is a mismatch or has an unregistered DOI, so it can run in CI over a paper's bibliography. "Not found" is a prompt to look by hand, not proof of a fake: theses, reports and old books are often missing from every index. Pass `--mailto you@example.org` so Crossref can reach you, and set `OPENALEX_API_KEY` for OpenAlex, whose free budget without a key is small and shared by your network.

## Use it from an agent (MCP)

```bash
pip install "citeparse[mcp]"
claude mcp add citeparse -- citeparse-mcp
```

The server offers two tools, `parse_references` (CSL-JSON or BibTeX) and `check_references`. Then ask your agent to "check the references in paper.tex".

## How good is it?

We scored it on 700 real references taken from Crossref. Each one cites a DOI, so the cited work's own Crossref record is the answer key. None of these DOIs were in our training data. We gave GROBID the same DOI rule that citeparse uses, so the DOI column is equal and the rest of the gap comes from the models.

| Parser | Fields right | References fully right | Title | Container | Volume | Issue | First page | DOI |
|---|---|---|---|---|---|---|---|---|
| GROBID 0.8.1 (CRF) | 0.911 | 71.1% | 0.882 | 0.805 | 0.908 | 0.803 | 0.953 | 0.994 |
| citeparse-32m | 0.939 | 80.3% | 0.921 | 0.858 | 0.956 | 0.841 | 0.968 | 0.988 |
| citeparse-150m | **0.952** | **83.4%** | **0.934** | **0.878** | **0.966** | **0.861** | **0.982** | **0.994** |

GROBID still wins on its own held-out citations (0.943 against 0.890 for citeparse-150m). Those citations come from the same sources as GROBID's training data. We report both results.

"Fields right" is the share of the 3,138 fields in the set that come out exactly right. A journal also counts as right when it matches its short title.

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
