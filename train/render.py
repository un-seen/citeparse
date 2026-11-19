"""Render Crossref records as reference strings in many citation styles, with character spans per field.

Output rows: {"text": str, "spans": [[start, end, LABEL], ...], "style": str}
Labels: AUTHOR EDITOR TITLE CONTAINER PUBLISHER LOCATION DATE VOLUME ISSUE PAGES DOI URL ISBN EDITION IDENTIFIER NOTE
"""
import json, random, re, sys, unicodedata, html

LABELS = ["AUTHOR", "EDITOR", "TITLE", "CONTAINER", "PUBLISHER", "LOCATION", "DATE", "VOLUME", "ISSUE",
          "PAGES", "DOI", "URL", "ISBN", "EDITION", "IDENTIFIER", "NOTE"]
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December"]
SMALL = {"a", "an", "the", "and", "but", "or", "for", "nor", "on", "at", "to", "from", "by", "of", "in", "with", "via"}


def clean(s):
    if not s:
        return ""
    s = html.unescape(re.sub(r"<[^>]+>", "", s))
    return re.sub(r"\s+", " ", s).strip()


class Buf:
    def __init__(self):
        self.parts, self.spans, self.n = [], [], 0

    def add(self, s, label=None):
        if not s:
            return
        if label:
            self.spans.append([self.n, self.n + len(s), label])
        self.parts.append(s)
        self.n += len(s)

    def text(self):
        return "".join(self.parts)


# ---------- field formatting ----------
def initials(given, dots=True, space=True):
    out = []
    for part in re.split(r"\s+", given.strip()):
        if not part:
            continue
        sub = [p for p in part.split("-") if p]
        ini = "-".join(p[0] + ("." if dots else "") for p in sub if p[0].isalpha())
        if ini:
            out.append(ini)
    return (" " if space else "").join(out)


def fmt_name(a, mode, r):
    fam, giv = clean(a.get("family")), clean(a.get("given"))
    if not fam:
        return clean(a.get("name"))
    if not giv:
        return fam
    if mode == "Fam, G.":
        return f"{fam}, {initials(giv)}"
    if mode == "Fam G":
        return f"{fam} {initials(giv, dots=False, space=False)}"
    if mode == "G. Fam":
        return f"{initials(giv)} {fam}"
    if mode == "Given Fam":
        return f"{giv} {fam}"
    if mode == "Fam, Given":
        return f"{fam}, {giv}"
    if mode == "FAM, G.":
        return f"{fam.upper()}, {initials(giv)}"
    return f"{fam}, {initials(giv)}"


def name_list(people, mode, r, *, sep=", ", last=", & ", maxn=None, etal="et al.", first_mode=None):
    """Returns list of (text, is_name) pieces."""
    ppl = [p for p in people if p.get("family") or p.get("name")]
    if not ppl:
        return []
    trunc = maxn is not None and len(ppl) > maxn
    if trunc:
        ppl = ppl[: max(1, min(maxn, 3) if maxn > 6 else 1 if maxn <= 2 else maxn)]
    names = [fmt_name(p, first_mode if (i == 0 and first_mode) else mode, r) for i, p in enumerate(ppl)]
    out = []
    for i, n in enumerate(names):
        if i > 0:
            out.append((last if (i == len(names) - 1 and not trunc) else sep, False))
        out.append((n, True))
    if trunc:
        out.append((" " if etal.startswith("et") and sep.strip() == "" else ", " if r.random() < 0.5 else " ", False))
        out.append((etal, True))
    return out


def title_case(s):
    words = s.split(" ")
    return " ".join(w if (i and w.lower() in SMALL) or not w[:1].isalpha() else w[:1].upper() + w[1:]
                    for i, w in enumerate(words))


def sentence_case(s):
    if sum(c.isupper() for c in s) > 0.6 * max(1, sum(c.isalpha() for c in s)):
        return s
    return s[:1].upper() + "".join(w for w in s[1:])


def get_year(rec):
    for k in ("issued", "published"):
        dp = (rec.get(k) or {}).get("date-parts") or [[None]]
        if dp and dp[0] and dp[0][0]:
            return dp[0]
    return None


def pages_fmt(p, r):
    p = clean(p)
    if not p:
        return p
    if r.random() < 0.4:
        p = p.replace("-", "–")
    if r.random() < 0.15 and re.fullmatch(r"\d+-\d+", p):
        a, b = p.split("-")
        if len(a) == len(b) and len(a) > 2 and r.random() < 0.5:
            i = 0
            while i < len(a) - 1 and a[i] == b[i]:
                i += 1
            p = f"{a}-{b[i:]}"
    return p


def fields(rec, r):
    t = clean(" ".join(rec.get("title") or []))
    sub = clean(" ".join(rec.get("subtitle") or []))
    if sub and r.random() < 0.7:
        t = f"{t}: {sub}"
    t = t.rstrip(" .")
    cont = rec.get("container-title") or []
    short = rec.get("short-container-title") or []
    c = clean(cont[0]) if cont else ""
    if short and r.random() < 0.35:
        c = clean(short[0])
    ev = (rec.get("event") or {}).get("name")
    if not c and ev:
        c = clean(ev)
    loc = clean(rec.get("publisher-location"))
    if not loc and r.random() < 0.15:
        loc = r.choice(["New York", "London", "Berlin", "Cambridge, MA", "Oxford", "Amsterdam", "Cham",
                        "Singapore", "Boston", "Hoboken, NJ", "Paris", "Tokyo", "Heidelberg", "Washington, DC"])
    yr = get_year(rec)
    return dict(
        type=rec.get("type"), title=t, container=c, publisher=clean(rec.get("publisher")), location=loc,
        authors=rec.get("author") or [], editors=rec.get("editor") or [], date=yr, volume=clean(rec.get("volume")),
        issue=clean(rec.get("issue")), pages=pages_fmt(rec.get("page") or rec.get("article-number") or "", r),
        doi=rec.get("DOI", ""), isbn=clean((rec.get("ISBN") or [""])[0]),
        edition=clean(str(rec.get("edition-number") or "")), institution=clean(((rec.get("institution") or [{}])[0]).get("name")),
    )


def date_str(d, style, r):
    if not d:
        return "n.d." if r.random() < 0.5 else ""
    y = str(d[0])
    if style == "y" or len(d) < 2:
        return y + (r.choice(["a", "b"]) if r.random() < 0.03 else "")
    m = d[1]
    if style == "mon y":
        return f"{MONTHS[m-1][:3] if r.random()<0.5 else MONTHS[m-1]} {y}"
    if style == "y, mon d" and len(d) > 2:
        return f"{y}, {MONTHS[m-1]} {d[2]}"
    if style == "y mon d" and len(d) > 2:
        return f"{y} {MONTHS[m-1][:3]} {d[2]}"
    return y


def doi_str(doi, r):
    return r.choice([f"https://doi.org/{doi}", f"doi:{doi}", f"doi: {doi}", f"DOI: {doi}", f"http://dx.doi.org/{doi}",
                     f"https://doi.org/{doi}", doi])


# ---------- styles ----------
def is_part(f):
    return f["type"] in ("book-chapter", "proceedings-article", "reference-entry") or (
        f["type"] == "journal-article")


def style_apa(f, r, b):
    nl = name_list(f["authors"], "Fam, G.", r, maxn=20 if r.random() < .8 else 6)
    for s, isn in nl:
        b.add(s, "AUTHOR" if isn else None)
    b.add(" (" if nl else "")
    b.add(date_str(f["date"], "y", r) or "n.d.", "DATE")
    b.add("). " if nl else "")
    if not nl:
        pass
    title = sentence_case(f["title"])
    if f["type"] == "journal-article" or f["type"] == "posted-content":
        b.add(title, "TITLE"); b.add(". ")
        if f["container"]:
            b.add(f["container"], "CONTAINER")
            if f["volume"]:
                b.add(", "); b.add(f["volume"], "VOLUME")
            if f["issue"]:
                b.add("("); b.add(f["issue"], "ISSUE"); b.add(")")
            if f["pages"]:
                b.add(", "); b.add(f["pages"], "PAGES")
            b.add(". ")
    elif f["type"] in ("book-chapter", "proceedings-article", "reference-entry"):
        b.add(title, "TITLE"); b.add(". In ")
        ed = name_list(f["editors"], "G. Fam", r, maxn=4)
        if ed:
            for s, isn in ed:
                b.add(s, "EDITOR" if isn else None)
            b.add(" (Ed" + ("s" if len(f["editors"]) > 1 else "") + ".), ")
        if f["container"]:
            b.add(f["container"], "CONTAINER")
        if f["pages"]:
            b.add(" (pp. "); b.add(f["pages"], "PAGES"); b.add(")")
        b.add(". ")
        if f["publisher"]:
            b.add(f["publisher"], "PUBLISHER"); b.add(". ")
    else:
        b.add(title, "TITLE")
        if f["edition"] and f["edition"] != "1":
            b.add(" ("); b.add(ordinal(f["edition"]) + " ed.", "EDITION"); b.add(")")
        b.add(". ")
        if f["publisher"]:
            b.add(f["publisher"], "PUBLISHER"); b.add(". ")
    if f["doi"] and r.random() < 0.8:
        b.add(f"https://doi.org/{f['doi']}" if r.random() < .85 else f"doi:{f['doi']}", "DOI")


def ordinal(n):
    try:
        n = int(n)
    except ValueError:
        return str(n)
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def style_ieee(f, r, b):
    nl = name_list(f["authors"], "G. Fam", r, sep=", ", last=r.choice([", and ", " and "]), maxn=6, etal="et al.")
    for s, isn in nl:
        b.add(s, "AUTHOR" if isn else None)
    if nl:
        b.add(", ")
    q = r.choice(['"', "“"]); qe = '"' if q == '"' else "”"
    if f["type"] in ("book", "monograph", "edited-book"):
        b.add(f["title"], "TITLE"); b.add(", ")
        if f["edition"] and f["edition"] != "1":
            b.add(ordinal(f["edition"]) + " ed.", "EDITION"); b.add(" ")
        if f["location"]:
            b.add(f["location"], "LOCATION"); b.add(": ")
        if f["publisher"]:
            b.add(f["publisher"], "PUBLISHER"); b.add(", ")
        b.add(date_str(f["date"], "y", r), "DATE"); b.add(".")
    else:
        b.add(q); b.add(f["title"], "TITLE"); b.add("," + qe + " ")
        if f["type"] in ("proceedings-article", "book-chapter"):
            b.add("in " + ("Proc. " if r.random() < .3 and f["type"] == "proceedings-article" else ""))
        if f["container"]:
            b.add(f["container"], "CONTAINER"); b.add(", ")
        if f["volume"]:
            b.add("vol. "); b.add(f["volume"], "VOLUME"); b.add(", ")
        if f["issue"]:
            b.add("no. "); b.add(f["issue"], "ISSUE"); b.add(", ")
        if f["pages"]:
            b.add("pp. " if "-" in f["pages"] or "–" in f["pages"] else "p. " if r.random() < .5 else "Art. no. ")
            b.add(f["pages"], "PAGES"); b.add(", ")
        b.add(date_str(f["date"], r.choice(["y", "mon y"]), r), "DATE")
        if f["doi"] and r.random() < 0.6:
            b.add(", "); b.add("doi: " + f["doi"], "DOI")
        b.add(".")


def style_vancouver(f, r, b):
    nl = name_list(f["authors"], "Fam G", r, sep=", ", last=", ", maxn=6, etal="et al")
    for s, isn in nl:
        b.add(s, "AUTHOR" if isn else None)
    if nl:
        b.add(". ")
    b.add(f["title"], "TITLE"); b.add(". ")
    if f["type"] in ("book", "monograph", "edited-book"):
        if f["location"]:
            b.add(f["location"], "LOCATION"); b.add(": ")
        if f["publisher"]:
            b.add(f["publisher"], "PUBLISHER"); b.add("; ")
        b.add(date_str(f["date"], "y", r), "DATE"); b.add(".")
        return
    if f["type"] in ("book-chapter", "proceedings-article"):
        b.add("In: ")
    if f["container"]:
        b.add(f["container"], "CONTAINER"); b.add(". ")
    b.add(date_str(f["date"], r.choice(["y", "y mon d"]), r), "DATE")
    if f["volume"]:
        b.add(";"); b.add(f["volume"], "VOLUME")
    if f["issue"]:
        b.add("("); b.add(f["issue"], "ISSUE"); b.add(")")
    if f["pages"]:
        b.add(":"); b.add(f["pages"], "PAGES")
    b.add(".")
    if f["doi"] and r.random() < 0.5:
        b.add(" "); b.add(r.choice([f"doi:{f['doi']}", f"doi: {f['doi']}", f"https://doi.org/{f['doi']}"]), "DOI")


def style_mla(f, r, b):
    a = [p for p in f["authors"] if p.get("family")]
    if a:
        b.add(fmt_name(a[0], "Fam, Given", r), "AUTHOR")
        if len(a) == 2:
            b.add(", and "); b.add(fmt_name(a[1], "Given Fam", r), "AUTHOR")
        elif len(a) > 2:
            b.add(", "); b.add("et al.", "AUTHOR")
        b.add(". " if not b.text().endswith(".") else " ")
    if f["type"] in ("book", "monograph", "edited-book"):
        b.add(title_case(f["title"]), "TITLE"); b.add(". ")
        if f["publisher"]:
            b.add(f["publisher"], "PUBLISHER"); b.add(", ")
        b.add(date_str(f["date"], "y", r), "DATE"); b.add(".")
        return
    b.add("“"); b.add(title_case(f["title"]), "TITLE"); b.add(".” ")
    if f["container"]:
        b.add(f["container"], "CONTAINER"); b.add(", ")
    if f["volume"]:
        b.add("vol. "); b.add(f["volume"], "VOLUME"); b.add(", ")
    if f["issue"]:
        b.add("no. "); b.add(f["issue"], "ISSUE"); b.add(", ")
    b.add(date_str(f["date"], r.choice(["y", "mon y"]), r), "DATE")
    if f["pages"]:
        b.add(", pp. "); b.add(f["pages"], "PAGES")
    b.add(".")
    if f["doi"] and r.random() < 0.6:
        b.add(" "); b.add(f"https://doi.org/{f['doi']}", "DOI"); b.add(".")


def style_chicago(f, r, b):
    a = [p for p in f["authors"] if p.get("family")]
    nl = []
    if a:
        nl = [(fmt_name(a[0], "Fam, Given", r), True)]
        rest = a[1:10]
        for i, p in enumerate(rest):
            nl.append((", and " if i == len(rest) - 1 else ", ", False))
            nl.append((fmt_name(p, "Given Fam", r), True))
    for s, isn in nl:
        b.add(s, "AUTHOR" if isn else None)
    if nl:
        b.add(". ")
    b.add(date_str(f["date"], "y", r), "DATE"); b.add(". ")
    if f["type"] in ("book", "monograph", "edited-book"):
        b.add(title_case(f["title"]), "TITLE"); b.add(". ")
        if f["location"]:
            b.add(f["location"], "LOCATION"); b.add(": ")
        if f["publisher"]:
            b.add(f["publisher"], "PUBLISHER"); b.add(".")
    else:
        b.add("“"); b.add(title_case(f["title"]), "TITLE"); b.add(".” ")
        if f["type"] in ("book-chapter", "proceedings-article"):
            b.add("In ")
        if f["container"]:
            b.add(f["container"], "CONTAINER")
        if f["volume"]:
            b.add(" "); b.add(f["volume"], "VOLUME")
        if f["issue"]:
            b.add(" ("); b.add(f["issue"], "ISSUE"); b.add(")")
        if f["pages"]:
            b.add(": "); b.add(f["pages"], "PAGES")
        b.add(".")
    if f["doi"] and r.random() < 0.6:
        b.add(" "); b.add(f"https://doi.org/{f['doi']}", "DOI"); b.add(".")


def style_nature(f, r, b):
    nl = name_list(f["authors"], "Fam, G.", r, sep=", ", last=" & ", maxn=5, etal="et al.")
    for s, isn in nl:
        b.add(s, "AUTHOR" if isn else None)
    if nl:
        b.add(" ")
    b.add(f["title"], "TITLE"); b.add(". ")
    if f["container"]:
        b.add(f["container"], "CONTAINER"); b.add(" ")
    if f["volume"]:
        b.add(f["volume"], "VOLUME"); b.add(", ")
    if f["pages"]:
        b.add(f["pages"], "PAGES"); b.add(" ")
    b.add("("); b.add(date_str(f["date"], "y", r), "DATE"); b.add(").")


def style_acm(f, r, b):
    nl = name_list(f["authors"], "Given Fam", r, sep=", ", last=", and ", maxn=8)
    for s, isn in nl:
        b.add(s, "AUTHOR" if isn else None)
    if nl:
        b.add(". ")
    b.add(date_str(f["date"], "y", r), "DATE"); b.add(". ")
    b.add(title_case(f["title"]), "TITLE"); b.add(". ")
    if f["type"] in ("book-chapter", "proceedings-article"):
        b.add("In ")
    if f["container"]:
        b.add(f["container"], "CONTAINER")
    if f["volume"]:
        b.add(" "); b.add(f["volume"], "VOLUME")
    if f["issue"]:
        b.add(", "); b.add(f["issue"], "ISSUE")
    if f["date"] and len(f["date"]) > 1 and r.random() < .4:
        b.add(" ("); b.add(date_str(f["date"], "mon y", r), "DATE"); b.add(")")
    if f["pages"]:
        b.add(", "); b.add(f["pages"], "PAGES")
    b.add(". ")
    if f["publisher"] and f["type"] != "journal-article":
        b.add(f["publisher"], "PUBLISHER")
        if f["location"]:
            b.add(", "); b.add(f["location"], "LOCATION")
        b.add(". ")
    if f["doi"] and r.random() < .8:
        b.add(f"https://doi.org/{f['doi']}", "DOI")


def style_harvard(f, r, b):
    nl = name_list(f["authors"], "Fam, G.", r, sep=", ", last=" and ", maxn=4)
    for s, isn in nl:
        b.add(s, "AUTHOR" if isn else None)
    b.add(" " if nl else "")
    b.add("(" if r.random() < .7 else ""); b.add(date_str(f["date"], "y", r), "DATE")
    b.add(") " if b.text().count("(") > b.text().count(")") else ". ")
    if f["type"] in ("book", "monograph", "edited-book"):
        b.add(f["title"], "TITLE"); b.add(". ")
        if f["edition"] and f["edition"] != "1":
            b.add(ordinal(f["edition"]) + " edn", "EDITION"); b.add(". ")
        if f["location"]:
            b.add(f["location"], "LOCATION"); b.add(": ")
        if f["publisher"]:
            b.add(f["publisher"], "PUBLISHER"); b.add(".")
        return
    b.add("'"); b.add(f["title"], "TITLE"); b.add("', ")
    if f["type"] in ("book-chapter", "proceedings-article"):
        b.add("in ")
    if f["container"]:
        b.add(f["container"], "CONTAINER"); b.add(", ")
    if f["volume"]:
        b.add(f["volume"], "VOLUME")
    if f["issue"]:
        b.add("("); b.add(f["issue"], "ISSUE"); b.add(")")
    if f["volume"] or f["issue"]:
        b.add(", ")
    if f["pages"]:
        b.add("pp. "); b.add(f["pages"], "PAGES")
    b.add(".")
    if f["doi"] and r.random() < .5:
        b.add(" "); b.add(doi_str(f["doi"], r), "DOI")


def style_physics(f, r, b):
    nl = name_list(f["authors"], "G. Fam", r, sep=", ", last=r.choice([", and ", " and ", ", "]), maxn=4)
    for s, isn in nl:
        b.add(s, "AUTHOR" if isn else None)
    if nl:
        b.add(", ")
    if r.random() < .5 and f["title"]:
        b.add(f["title"], "TITLE"); b.add(", ")
    if f["container"]:
        b.add(f["container"], "CONTAINER"); b.add(" ")
    if f["volume"]:
        b.add(f["volume"], "VOLUME"); b.add(r.choice([", ", " "]))
    if f["pages"]:
        b.add(f["pages"].split("-")[0].split("–")[0], "PAGES"); b.add(" ")
    b.add("("); b.add(date_str(f["date"], "y", r), "DATE"); b.add(")")
    if f["doi"] and r.random() < .3:
        b.add(", "); b.add(doi_str(f["doi"], r), "DOI")
    b.add(".")


def style_german(f, r, b):
    nl = name_list(f["authors"], r.choice(["Fam, G.", "FAM, G."]), r, sep="; ", last="; ", maxn=3, etal="u. a.")
    for s, isn in nl:
        b.add(s, "AUTHOR" if isn else None)
    if nl:
        b.add(": ")
    b.add(f["title"], "TITLE"); b.add(". ")
    if f["type"] in ("book-chapter", "proceedings-article", "journal-article") and f["container"]:
        b.add("In: "); b.add(f["container"], "CONTAINER")
        if f["volume"]:
            b.add(" "); b.add(f["volume"], "VOLUME")
        b.add(" ("); b.add(date_str(f["date"], "y", r), "DATE"); b.add(")")
        if f["issue"]:
            b.add(", Nr. "); b.add(f["issue"], "ISSUE")
        if f["pages"]:
            b.add(", S. "); b.add(f["pages"], "PAGES")
    else:
        if f["location"]:
            b.add(f["location"], "LOCATION"); b.add(" : ")
        if f["publisher"]:
            b.add(f["publisher"], "PUBLISHER"); b.add(", ")
        b.add(date_str(f["date"], "y", r), "DATE")
    b.add(".")


def style_bibtexish(f, r, b):
    """Plain dump some tools emit: Authors. Title. Journal, vol(issue):pages, year. DOI"""
    nl = name_list(f["authors"], "Given Fam", r, sep=", ", last=r.choice([", and ", " and "]), maxn=10)
    for s, isn in nl:
        b.add(s, "AUTHOR" if isn else None)
    if nl:
        b.add(". ")
    b.add(f["title"], "TITLE"); b.add(". ")
    if f["container"]:
        b.add(f["container"], "CONTAINER"); b.add(", ")
    if f["volume"]:
        b.add(f["volume"], "VOLUME")
    if f["issue"]:
        b.add("("); b.add(f["issue"], "ISSUE"); b.add(")")
    if f["pages"]:
        b.add(":"); b.add(f["pages"], "PAGES")
    if f["volume"] or f["pages"]:
        b.add(", ")
    b.add(date_str(f["date"], "y", r), "DATE"); b.add(".")
    if f["publisher"] and f["type"] in ("book", "monograph", "edited-book", "book-chapter"):
        b.add(" "); b.add(f["publisher"], "PUBLISHER"); b.add(".")
    if f["isbn"] and r.random() < .5:
        b.add(" ISBN "); b.add(f["isbn"], "ISBN"); b.add(".")
    if f["doi"] and r.random() < .5:
        b.add(" "); b.add(doi_str(f["doi"], r), "DOI")


STYLES = {"apa": (style_apa, 3), "ieee": (style_ieee, 3), "vancouver": (style_vancouver, 2), "mla": (style_mla, 1.5),
          "chicago": (style_chicago, 1.5), "nature": (style_nature, 1.5), "acm": (style_acm, 1.5),
          "harvard": (style_harvard, 2), "physics": (style_physics, 1), "german": (style_german, 0.7),
          "plain": (style_bibtexish, 1.5)}


# ---------- noise ----------
def prefix(r):
    k = r.random()
    if k < 0.25:
        return f"[{r.randint(1, 120)}] "
    if k < 0.4:
        return f"{r.randint(1, 120)}. "
    if k < 0.45:
        return f"{r.randint(1, 120)} "
    if k < 0.48:
        return "• "
    return ""


def noisy(text, spans, r):
    """Character edits that keep span alignment: hyphen-break, double spaces, ascii folding."""
    ops = []
    if r.random() < 0.08:  # line-break hyphenation inside a word
        words = [m for m in re.finditer(r"[A-Za-z]{7,}", text)]
        if words:
            m = r.choice(words); cut = m.start() + r.randint(3, len(m.group()) - 3)
            ops.append((cut, "- " if r.random() < .5 else "-\n"))
    if r.random() < 0.08:
        sp = [m.start() for m in re.finditer(" ", text)]
        if sp:
            ops.append((r.choice(sp), " "))
    for pos, ins in sorted(ops, reverse=True):
        text = text[:pos] + ins + text[pos:]
        spans = [[s + (len(ins) if s >= pos else 0), e + (len(ins) if e > pos else 0), l] for s, e, l in spans]
    if r.random() < 0.1:
        folded = unicodedata.normalize("NFKD", text)
        if len(folded) == len(text):
            pass
        else:
            # rebuild spans char by char
            new, mp = [], []
            for i, ch in enumerate(text):
                f = "".join(c for c in unicodedata.normalize("NFKD", ch) if not unicodedata.combining(c)) or ch
                f = {"“": '"', "”": '"', "–": "-", "’": "'"}.get(f, f)
                mp.append(len("".join(new)))
                new.append(f)
            mp.append(len("".join(new)))
            text = "".join(new)
            spans = [[mp[s], mp[e], l] for s, e, l in spans]
    return text, spans


def render(rec, r):
    f = fields(rec, r)
    if not f["title"] or len(f["title"]) > 400:
        return None
    name = r.choices(list(STYLES), weights=[w for _, w in STYLES.values()])[0]
    if r.random() < 0.1:  # drop a field
        f[r.choice(["doi", "issue", "pages", "volume", "publisher", "location"])] = ""
    b = Buf()
    p = prefix(r)
    b.add(p)
    STYLES[name][0](f, r, b)
    text, spans = b.text(), [s for s in b.spans if s[1] > s[0]]
    text, spans = noisy(text, spans, r)
    # trim leading/trailing whitespace inside spans
    out = []
    for s, e, l in spans:
        while s < e and text[s].isspace(): s += 1
        while e > s and text[e - 1].isspace(): e -= 1
        if e > s:
            out.append([s, e, l])
    return {"text": text.strip(), "spans": out, "style": name, "type": f["type"]}


if __name__ == "__main__":
    src, dst, per = sys.argv[1], sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 2
    r = random.Random(0)
    n = 0
    with open(dst, "w") as o:
        for line in open(src):
            rec = json.loads(line)
            for _ in range(per):
                row = render(rec, r)
                if row:
                    # text.strip() may shift if leading whitespace; prefix never starts with space
                    o.write(json.dumps(row, ensure_ascii=False) + "\n"); n += 1
    print("rows", n)
