"""How to cite the platform, and the papers behind it.

Requested by Ali Hajian (2026-09-09): a Google Scholar style "Cite" button on
the landing page, offering the usual styles plus BibTeX.

Everything citable lives HERE, once. The dialog, the BibTeX/RIS exports, and
`CITATION.cff` at the repo root all come from these three records, and a test
(`tests/test_citation.py`) fails if the .cff drifts from them. A citation that
disagrees with itself in two places is worse than no citation button at all.

Three works, deliberately:
  * the platform - what the button is for;
  * Atari, Omrani & Dehghani (2023) - the method this software implements;
  * Chen, Li, Li & Atari (2024) - the EMNLP paper that extended and validated
    it, and the reference implementation our parity tests follow.
A paper that used the platform needs all three, so the BibTeX and RIS exports
carry all three and the dialog says so.

Both paper records were taken from Crossref (2026-09-10), not from memory:
10.31234/osf.io/m93pd and 10.18653/v1/2024.emnlp-main.151.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .version import PLATFORM_VERSION

# The year the platform citation carries. Not today's year: a citation that
# changes under the reader every January is not a citation. Bump it when a
# release is worth re-dating.
PLATFORM_YEAR = 2026

PLATFORM_URL = "https://psychologicaltextanalysis.com"
REPO_URL = "https://github.com/Culture-and-Morality-Lab/ccr-platform"
LAB = "Culture and Morality Lab, University of Massachusetts Amherst"


@dataclass(frozen=True)
class Author:
    family: str
    given: str

    @property
    def initials(self) -> str:
        """'Deva' -> 'D.'; 'Yuqi' -> 'Y.'. Hyphenated given names keep both
        initials ('Jean-Paul' -> 'J.-P.'), which APA, Harvard and Vancouver
        all want."""
        return "-".join(f"{part[0]}." for part in self.given.split("-") if part)

    @property
    def vancouver_initials(self) -> str:
        """Vancouver drops the periods: 'Deva' -> 'D'."""
        return "".join(part[0] for part in self.given.split("-") if part)


@dataclass(frozen=True)
class Work:
    """One citable thing.

    `title` is the title as published (title case, for MLA and Chicago) and
    `title_sentence` is the same title in sentence case (for APA, Harvard and
    Vancouver). Both are written out rather than derived: a lowercasing
    function would flatten CCR, Chinese and PsyArXiv, and getting a citation
    subtly wrong is the one failure this feature cannot afford.
    """

    key: str  # BibTeX key
    kind: str  # software | preprint | inproceedings
    authors: list[Author]
    year: int
    title: str
    title_sentence: str
    publisher: str = ""
    url: str = ""
    doi: str = ""
    version: str = ""
    booktitle: str = ""
    pages: str = ""  # "2597-2615"
    address: str = ""
    month: str = ""
    note: str = ""
    extra_urls: dict[str, str] = field(default_factory=dict)

    @property
    def doi_url(self) -> str:
        return f"https://doi.org/{self.doi}" if self.doi else ""

    @property
    def link(self) -> str:
        """The one link a reader should follow: a DOI where there is one."""
        return self.doi_url or self.url


PLATFORM = Work(
    key=f"ccr_platform_{PLATFORM_YEAR}",
    kind="software",
    # Who is credited is the PI's call, not the code's. It is this one list
    # (and CITATION.cff, which a test holds to it), so it is a one-line change:
    # developer first, PI second, the lab as publisher, which is the usual
    # shape for research software out of a single lab.
    authors=[Author("Anand", "Deva"), Author("Atari", "Mohammad")],
    year=PLATFORM_YEAR,
    title=(
        "CCR Platform: Theory-Driven Psychological Text Analysis with "
        "Contextualized Construct Representation"
    ),
    title_sentence=(
        "CCR Platform: Theory-driven psychological text analysis with "
        "contextualized construct representation"
    ),
    publisher=LAB,
    url=PLATFORM_URL,
    # The version stamped into every run's metadata and reproduction script
    # (jobs.py), so a paper's citation and its reproducibility record agree.
    version=PLATFORM_VERSION,
    address="Amherst, MA",
    note="Computer software",
    extra_urls={"repository": REPO_URL},
)

CCR_METHOD = Work(
    key="atari2023contextualized",
    kind="preprint",
    authors=[
        Author("Atari", "Mohammad"),
        Author("Omrani", "Ali"),
        Author("Dehghani", "Morteza"),
    ],
    year=2023,
    title=(
        "Contextualized Construct Representation: Leveraging Psychometric "
        "Scales to Advance Theory-Driven Text Analysis"
    ),
    title_sentence=(
        "Contextualized construct representation: Leveraging psychometric "
        "scales to advance theory-driven text analysis"
    ),
    publisher="PsyArXiv",
    doi="10.31234/osf.io/m93pd",
    note="Preprint",
)

CCR_EMNLP = Work(
    key="chen-etal-2024-surveying",  # the ACL Anthology's own key
    kind="inproceedings",
    authors=[
        Author("Chen", "Yuqi"),
        Author("Li", "Sixuan"),
        Author("Li", "Ying"),
        Author("Atari", "Mohammad"),
    ],
    year=2024,
    title=(
        "Surveying the Dead Minds: Historical-Psychological Text Analysis "
        "with Contextualized Construct Representation (CCR) for Classical "
        "Chinese"
    ),
    title_sentence=(
        "Surveying the dead minds: Historical-psychological text analysis "
        "with contextualized construct representation (CCR) for classical "
        "Chinese"
    ),
    booktitle=(
        "Proceedings of the 2024 Conference on Empirical Methods in Natural "
        "Language Processing"
    ),
    publisher="Association for Computational Linguistics",
    pages="2597-2615",
    address="Miami, Florida, USA",
    month="November",
    doi="10.18653/v1/2024.emnlp-main.151",
)

WORKS = [PLATFORM, CCR_METHOD, CCR_EMNLP]

STYLE_LABELS = [
    ("apa", "APA"),
    ("mla", "MLA"),
    ("chicago", "Chicago"),
    ("harvard", "Harvard"),
    ("vancouver", "Vancouver"),
]


# ----------------------------------------------------------------- authors
def _apa_authors(authors: list[Author]) -> str:
    """'Anand, D., & Atari, M.' - APA lists every author up to 20, and keeps
    the comma before the ampersand even with only two."""
    names = [f"{a.family}, {a.initials}" for a in authors]
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + ", & " + names[-1]


def _mla_authors(authors: list[Author]) -> str:
    """'Anand, Deva, and Mohammad Atari.' Three or more become 'et al.'"""
    first = f"{authors[0].family}, {authors[0].given}"
    if len(authors) == 1:
        return first
    if len(authors) == 2:
        return f"{first}, and {authors[1].given} {authors[1].family}"
    return f"{first}, et al."


def _chicago_authors(authors: list[Author]) -> str:
    """Chicago bibliography style names everyone: first author inverted, the
    rest in reading order."""
    first = f"{authors[0].family}, {authors[0].given}"
    rest = [f"{a.given} {a.family}" for a in authors[1:]]
    if not rest:
        return first
    if len(rest) == 1:
        return f"{first}, and {rest[0]}"
    return f"{first}, " + ", ".join(rest[:-1]) + f", and {rest[-1]}"


def _harvard_authors(authors: list[Author]) -> str:
    """'Anand, D. and Atari, M.' - Harvard uses 'and', not an ampersand."""
    names = [f"{a.family}, {a.initials}" for a in authors]
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + f" and {names[-1]}"


def _vancouver_authors(authors: list[Author]) -> str:
    """'Anand D, Atari M' - no periods, no ampersand."""
    return ", ".join(f"{a.family} {a.vancouver_initials}" for a in authors)


def _join(parts: list[str]) -> str:
    """Drop the empty fields before joining, so a work without a DOI or a
    page range does not leave a dangling separator."""
    return " ".join(p for p in parts if p)


# ------------------------------------------------------------------ styles
def apa(w: Work) -> str:
    who = _apa_authors(w.authors)
    if w.kind == "software":
        version = f" (Version {w.version})" if w.version else ""
        return _join([
            f"{who} ({w.year}).", f"{w.title_sentence}{version} [Computer software].",
            f"{w.publisher}.", w.link,
        ])
    if w.kind == "preprint":
        return _join([f"{who} ({w.year}).", f"{w.title_sentence}.", f"{w.publisher}.", w.link])
    pages = f" (pp. {w.pages})" if w.pages else ""
    return _join([
        f"{who} ({w.year}).", f"{w.title_sentence}.", f"In {w.booktitle}{pages}.",
        f"{w.publisher}.", w.link,
    ])


def mla(w: Work) -> str:
    # _mla_authors already ends in a period for the "et al." form, so the
    # separator is added only when it is missing (otherwise: "et al..").
    who = _mla_authors(w.authors).rstrip(".")
    if w.kind == "software":
        version = f"Version {w.version}, " if w.version else ""
        return _join([
            f"{who}.", f"{w.title}.", f"{version}{w.publisher},", f"{w.year},",
            f"{w.link}.",
        ])
    if w.kind == "preprint":
        return _join([f"{who}.", f'"{w.title}."', f"{w.publisher}, {w.year},", f"{w.link}."])
    pages = f" pp. {w.pages}." if w.pages else ""
    return _join([
        f"{who}.", f'"{w.title}."', f"{w.booktitle},", f"{w.publisher}, {w.year},",
    ]) + pages


def chicago(w: Work) -> str:
    who = _chicago_authors(w.authors)
    if w.kind == "software":
        version = f" Version {w.version}." if w.version else ""
        return _join([f"{who}.", f"{w.year}.", f'"{w.title}."{version}', f"{w.publisher}.", f"{w.link}."])
    if w.kind == "preprint":
        return _join([f"{who}.", f"{w.year}.", f'"{w.title}."', f"{w.publisher}.", f"{w.link}."])
    pages = f", {w.pages}" if w.pages else ""
    return _join([
        f"{who}.", f"{w.year}.", f'"{w.title}."', f"In {w.booktitle}{pages}.",
        f"{w.address}: {w.publisher}." if w.address else f"{w.publisher}.",
    ])


def harvard(w: Work) -> str:
    who = _harvard_authors(w.authors)
    if w.kind == "software":
        version = f" (Version {w.version})" if w.version else ""
        return _join([
            f"{who} ({w.year})", f"{w.title}{version}.", "[Computer software]",
            f"{w.publisher}.", f"Available at: {w.link}",
        ])
    if w.kind == "preprint":
        return _join([
            f"{who} ({w.year})", f"{w.title_sentence}.", f"{w.publisher}.",
            f"Available at: {w.link}",
        ])
    pages = f", pp. {w.pages}" if w.pages else ""
    return _join([
        f"{who} ({w.year})", f"'{w.title_sentence}',", f"{w.booktitle}.",
        f"{w.publisher}{pages}.",
    ])


def vancouver(w: Work) -> str:
    who = _vancouver_authors(w.authors)
    if w.kind == "software":
        version = f" Version {w.version}." if w.version else ""
        place = f"{w.address}: " if w.address else ""
        return _join([
            f"{who}.", f"{w.title_sentence} [computer software].{version}",
            f"{place}{w.publisher}; {w.year}.", f"Available from: {w.link}",
        ])
    if w.kind == "preprint":
        return _join([
            f"{who}.", f"{w.title_sentence}.", f"{w.publisher}; {w.year}.",
            f"Available from: {w.link}",
        ])
    pages = f" p. {w.pages}." if w.pages else ""
    where = f"{w.month} {w.year}; {w.address}." if w.month and w.address else f"{w.year}."
    return _join([
        f"{who}.", f"{w.title_sentence}.", f"In: {w.booktitle};", where,
        f"{w.publisher}; {w.year}.",
    ]) + pages


FORMATTERS = {
    "apa": apa, "mla": mla, "chicago": chicago, "harvard": harvard, "vancouver": vancouver,
}


def styles(w: Work) -> dict[str, str]:
    return {style: FORMATTERS[style](w) for style, _ in STYLE_LABELS}


# ----------------------------------------------------------------- exports
def bibtex(w: Work) -> str:
    """One BibTeX entry. Titles are wrapped in an extra brace pair so BibTeX
    styles do not lowercase CCR, PsyArXiv or Chinese."""
    if w.kind == "software":
        fields = [
            ("author", " and ".join(f"{a.family}, {a.given}" for a in w.authors)),
            ("title", f"{{{w.title}}}"),
            ("year", str(w.year)),
            ("version", w.version),
            ("organization", w.publisher),
            ("url", w.url),
            ("note", w.note),
        ]
        entry = "software"
    elif w.kind == "preprint":
        fields = [
            ("author", " and ".join(f"{a.family}, {a.given}" for a in w.authors)),
            ("title", f"{{{w.title}}}"),
            ("year", str(w.year)),
            ("publisher", w.publisher),
            ("doi", w.doi),
            ("url", w.link),
            ("note", w.note),
        ]
        entry = "misc"
    else:
        fields = [
            ("author", " and ".join(f"{a.family}, {a.given}" for a in w.authors)),
            ("title", f"{{{w.title}}}"),
            ("booktitle", w.booktitle),
            ("year", str(w.year)),
            ("address", w.address),
            ("publisher", w.publisher),
            ("pages", w.pages.replace("-", "--")),
            ("doi", w.doi),
            ("url", w.link),
        ]
        entry = "inproceedings"
    lines = [f"@{entry}{{{w.key},"]
    lines += [f"  {name} = {{{value}}}," for name, value in fields if value]
    lines[-1] = lines[-1].rstrip(",")
    lines.append("}")
    return "\n".join(lines)


_RIS_TYPES = {"software": "COMP", "preprint": "UNPB", "inproceedings": "CPAPER"}


def ris(w: Work) -> str:
    """RIS, which is what EndNote, Zotero, Mendeley and RefWorks all import."""
    rows = [("TY", _RIS_TYPES[w.kind])]
    rows += [("AU", f"{a.family}, {a.given}") for a in w.authors]
    rows.append(("TI", w.title))
    rows.append(("PY", str(w.year)))
    if w.kind == "inproceedings":
        rows.append(("T2", w.booktitle))
        if w.pages:
            start, _, end = w.pages.partition("-")
            rows += [("SP", start), ("EP", end)]
        if w.address:
            rows.append(("CY", w.address))
    if w.publisher:
        rows.append(("PB", w.publisher))
    if w.version:
        rows.append(("ET", f"Version {w.version}"))
    if w.doi:
        rows.append(("DO", w.doi))
    if w.link:
        rows.append(("UR", w.link))
    if w.note:
        rows.append(("N1", w.note))
    rows.append(("ER", ""))
    return "\n".join(f"{tag}  - {value}".rstrip() for tag, value in rows)


def payload() -> dict:
    """What GET /api/citation returns.

    The dialog shows the five styles for the platform (Google Scholar's shape)
    and names the two method papers underneath; the BibTeX and RIS exports
    carry all three, because a methods section needs all three.
    """
    return {
        "platform": {
            "title": PLATFORM.title,
            "version": PLATFORM.version,
            "year": PLATFORM.year,
            "url": PLATFORM.url,
            "repository": REPO_URL,
            "styles": styles(PLATFORM),
        },
        "styles": [{"id": sid, "label": label} for sid, label in STYLE_LABELS],
        "method": [
            {
                "key": w.key,
                "label": label,
                "apa": apa(w),
                "url": w.link,
            }
            for w, label in ((CCR_METHOD, "The CCR method"), (CCR_EMNLP, "Extension and validation"))
        ],
        "bibtex": "\n\n".join(bibtex(w) for w in WORKS),
        "ris": "\n\n".join(ris(w) for w in WORKS),
    }
