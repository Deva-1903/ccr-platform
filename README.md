---
title: CCR Platform
emoji: 🧭
colorFrom: red
colorTo: gray
sdk: docker
app_port: 7860
pinned: false
---

# CCR Platform

A web platform for **Contextualized Construct Representations (CCR)** - theory-driven
psychological text analysis ([Atari, Omrani, et al.](https://github.com/Ali-Omrani/CCR);
[EMNLP 2024](https://aclanthology.org/2024.emnlp-main.151/)). Built for the Culture and
Morality Lab (UMass Amherst); this instance is the lab's **dev/testing environment**.

Upload a corpus (CSV/XLSX), pick a validated construct from the library or define your
own (typed or uploaded from a file), choose a language and embedding model, run the
analysis, inspect results (distributions, per-item loadings, top/bottom texts,
data-quality warnings), and export everything - including a Python script that
reproduces the run on any machine.

## Features

- Anonymous try-it tier: 3 runs/day, uploads deleted right after analysis, sessions
  purged after 24 h. Free accounts (email/password, optional Google sign-in) lift
  limits and keep your work (15 saved runs).
- Construct library (versioned, append-only, item-hashed) + custom constructs with
  reverse-scored flags; searchable grouped picker.
- Model registry: MiniLM default (the CCR reference model), E5-large-v2,
  Multilingual-E5; E5 prefix policy handled automatically; language coverage warnings.
- Structured data-quality warnings (language mismatch/uncertainty, short texts,
  truncation, duplicates, encoding fallback) - stable machine-readable codes.
- Per-run reproducibility: metadata JSON + offline-runnable script + pinned
  requirements. Corpus-embedding cache makes re-runs on the same corpus near-instant.
- Storage: local disk by default; S3-compatible (Cloudflare R2) via env config.

## Run locally

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000 --env-file ../.env
```

Open http://127.0.0.1:8000. See `MANUAL_TESTING.md` for a full click-through test
script and `sample_data/README.md` for what each sample file demonstrates.
Configuration: copy `.env.example` to `.env` and fill what you need.

## Notes

- Do not upload sensitive or identifiable data to this shared dev instance; anonymous
  storage is ephemeral and the instance may reset.
- The construct library ships the lab's full collection of 94 constructs. Item wording,
  reverse-scoring keys, subscale grouping, and citations were reviewed against the source
  publications in August 2026: 88 constructs are marked verified and carry the reviewer
  and review date. The other 6 stay flagged in the interface pending two wording
  decisions (the IPIP scales and the K10). See
  `docs/specs/0007-construct-library-verification-pass.md`.
- Tests: `cd backend && CCR_FAKE_EMBEDDINGS=1 python -m pytest -q` (174 tests, no ML
  downloads needed).

## How to cite

If you use the platform in research, cite it and the CCR method papers. The app's
landing page has a "Cite this platform" link (APA, MLA, Chicago, Harvard, Vancouver,
BibTeX, RIS), GitHub reads `CITATION.cff` for the same details, and the strings all
come from `backend/app/citation.py`.

> Anand, D., & Atari, M. (2026). CCR Platform: Theory-driven psychological text
> analysis with contextualized construct representation (Version 0.2.0) [Computer
> software]. Culture and Morality Lab, University of Massachusetts Amherst.
> https://psychologicaltextanalysis.com

> Atari, M., Omrani, A., & Dehghani, M. (2023). Contextualized construct
> representation: Leveraging psychometric scales to advance theory-driven text
> analysis. PsyArXiv. https://doi.org/10.31234/osf.io/m93pd

> Chen, Y., Li, S., Li, Y., & Atari, M. (2024). Surveying the dead minds:
> Historical-psychological text analysis with contextualized construct
> representation (CCR) for classical Chinese. In Proceedings of the 2024 Conference
> on Empirical Methods in Natural Language Processing (pp. 2597-2615). Association
> for Computational Linguistics. https://doi.org/10.18653/v1/2024.emnlp-main.151

Analyses run on a bundled example corpus also need that corpus's own citation, which
the run metadata carries.

## License

MIT (see `LICENSE`) covers the CODE. Data shipped alongside it does not inherit that
licence:

- the questionnaire items in the construct library belong to their original authors, and
  each construct records its citation, source, and any redistribution caveat in
  `rights_note`;
- `sample_data/camel_sample.csv` is a slice of the CAMEL corpus (Zewail et al., 2026) and
  is **CC BY-NC 4.0**, not MIT. Non-commercial use with attribution; the citation and
  licence travel in the run metadata of any analysis run on it.
