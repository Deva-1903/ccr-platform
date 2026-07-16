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
- The construct library ships the lab's full collection (94 validated-scale
  constructs + 5 seeds); wording verification against original publications is in
  progress and unverified scales are flagged in the interface.
- Tests: `cd backend && CCR_FAKE_EMBEDDINGS=1 python -m pytest -q` (64 tests, no ML
  downloads needed).
