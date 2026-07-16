"""Tester-facing extras: the /guide page and the /samples demo-data mount.

Both exist for the hosted dev instance so the PI/students can test without
being handed files out of band. They are static content, but regressions here
(a renamed sample file, a moved directory) would silently break the guide's
download links, so pin the contract.
"""

import re
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import SAMPLES_DIR, app

client = TestClient(app)


def test_guide_serves_html():
    r = client.get("/guide")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "Testing Guide" in r.text


def test_samples_mount_serves_files():
    r = client.get("/samples/sample_corpus.csv")
    assert r.status_code == 200
    assert r.text.splitlines()[0].startswith("id,")


def test_every_sample_link_in_guide_resolves():
    """Every /samples/<file> href in guide.html must exist in sample_data/."""
    html = (Path(__file__).resolve().parents[1] / "app" / "guide.html").read_text()
    linked = set(re.findall(r'href="/samples/([^"]+)"', html))
    assert linked, "guide.html should link to sample files"
    missing = sorted(f for f in linked if not (SAMPLES_DIR / f).exists())
    assert not missing, f"guide links to samples that do not exist: {missing}"
