"""The Cite dialog's contents (citation.py), and the CITATION.cff beside it.

A citation feature has one job: say the same true thing everywhere. So these
tests are less about code paths than about agreement - between the endpoint,
the BibTeX/RIS exports, the .cff GitHub reads, and the version stamped into
run metadata.
"""

from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from app import citation
from app.main import app
from app.version import PLATFORM_VERSION

CFF_PATH = Path(__file__).resolve().parents[2] / "CITATION.cff"


@pytest.fixture(scope="module")
def cff():
    return yaml.safe_load(CFF_PATH.read_text(encoding="utf-8"))


def test_endpoint_serves_every_style_and_both_exports():
    client = TestClient(app)
    resp = client.get("/api/citation")
    assert resp.status_code == 200
    body = resp.json()

    style_ids = [s["id"] for s in body["styles"]]
    assert style_ids == ["apa", "mla", "chicago", "harvard", "vancouver"]
    for sid in style_ids:
        text = body["platform"]["styles"][sid]
        # Every style names the authors, the year, the version and where to
        # find it. A style that quietly drops one is the bug this catches.
        assert "Anand" in text and "Atari" in text
        assert str(citation.PLATFORM_YEAR) in text
        assert PLATFORM_VERSION in text
        assert citation.PLATFORM_URL in text

    assert body["platform"]["version"] == PLATFORM_VERSION
    assert body["bibtex"].count("@") == 3  # platform + both method papers
    assert body["ris"].count("TY  - ") == 3


def test_citation_endpoint_is_public():
    """The dialog lives on the landing page, which signed-out visitors see."""
    client = TestClient(app)
    assert client.get("/api/citation").status_code == 200


def test_method_papers_carry_their_dois():
    body = TestClient(app).get("/api/citation").json()
    dois = " ".join(m["apa"] for m in body["method"])
    assert "10.31234/osf.io/m93pd" in dois  # Atari, Omrani & Dehghani (2023)
    assert "10.18653/v1/2024.emnlp-main.151" in dois  # Chen et al. (2024), EMNLP


def test_bibtex_keys_are_unique_and_titles_are_brace_protected():
    entries = citation.payload()["bibtex"].split("\n\n")
    keys = [e.split("{", 1)[1].split(",", 1)[0] for e in entries]
    assert len(set(keys)) == len(keys)
    for entry in entries:
        # {{...}} keeps BibTeX styles from lowercasing CCR, PsyArXiv, Chinese.
        assert "title = {{" in entry


def test_apa_author_forms():
    """Two authors keep the comma before the ampersand; three or more are all
    listed. Both are APA 7 rules people notice when they are wrong."""
    assert citation.apa(citation.PLATFORM).startswith("Anand, D., & Atari, M. (2026).")
    assert citation.apa(citation.CCR_METHOD).startswith(
        "Atari, M., Omrani, A., & Dehghani, M. (2023)."
    )


def test_mla_uses_et_al_beyond_two_authors_without_doubling_the_period():
    assert citation.mla(citation.CCR_EMNLP).startswith('Chen, Yuqi, et al. "Surveying')
    assert ".." not in citation.mla(citation.CCR_EMNLP)


def test_cff_agrees_with_the_served_citation(cff):
    """CITATION.cff is what GitHub shows and what reference managers read from
    the repo. If someone edits one side only, this fails."""
    assert cff["title"] == citation.PLATFORM.title
    assert cff["version"] == PLATFORM_VERSION
    assert cff["url"] == citation.PLATFORM_URL
    assert cff["repository-code"] == citation.REPO_URL

    cff_authors = [(a["family-names"], a["given-names"]) for a in cff["authors"]]
    assert cff_authors == [(a.family, a.given) for a in citation.PLATFORM.authors]

    cff_dois = {r["doi"] for r in cff["references"]}
    assert cff_dois == {citation.CCR_METHOD.doi, citation.CCR_EMNLP.doi}


def test_cff_method_papers_list_the_same_authors(cff):
    by_doi = {r["doi"]: r for r in cff["references"]}
    for work in (citation.CCR_METHOD, citation.CCR_EMNLP):
        listed = [
            (a["family-names"], a["given-names"]) for a in by_doi[work.doi]["authors"]
        ]
        assert listed == [(a.family, a.given) for a in work.authors]


def test_run_metadata_version_matches_the_citation():
    """A paper cites version X and its reproducibility record says version X.
    Both read the same constant; this fails if one is ever forked."""
    from app import jobs

    assert jobs.PLATFORM_VERSION == PLATFORM_VERSION == citation.PLATFORM.version
