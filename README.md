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

A web platform for **Contextualized Construct Representations (CCR)** — theory-driven psychological text analysis ([Atari, Omrani, et al.](https://github.com/Ali-Omrani/CCR); [Chen et al., EMNLP 2024](https://aclanthology.org/2024.emnlp-main.151/)).

Researchers upload a text corpus, select (or define) a psychological construct backed by a validated self-report scale, run a CCR analysis with a locally-hosted sentence-embedding model, inspect the results, and export scores — with a reproducibility record attached to every run.

**Method in one line:** embed the validated scale items and the texts with a contextual language model; the cosine similarity between a text and each item is the text's *loading* on the construct; the mean loading is its CCR score.

## Quickstart

Requires Python 3.10+. No Node needed — the dashboard ships prebuilt.

```bash
./run.sh
# then open http://127.0.0.1:8000
```

First run creates a virtualenv and installs dependencies; the default embedding model (~90 MB) downloads on first analysis. To verify the install end-to-end:

```bash
source backend/.venv/bin/activate
python scripts/verify_install.py
```

**Try it:** create a project → upload `sample_data/sample_corpus.csv` (60 synthetic texts) → choose *Satisfaction with Life* → Run. Then re-run the same corpus against *Individualism* vs *Collectivism* and compare the top-scoring texts.

## What the platform adds over the existing CCR tools

The published [R/Python packages](https://github.com/Ali-Omrani/CCR) and the single-run web demo cover one-off analyses. This platform adds the workflow around the method: **projects** that persist corpora and runs, a **construct library** of validated scales (plus custom constructs), **async jobs** with live progress on large corpora, a **results dashboard** (score distribution, per-item loadings, highest/lowest-scoring texts for face-validity checks), **CSV export** in the same shape as `ccr_wrapper` output, and a **reproducibility record** (model + version, item hash, package versions, timestamps) downloadable per run.

## Architecture

```
Browser (React SPA, prebuilt → served by FastAPI)
    │  REST /api/*
FastAPI (backend/app/main.py)
    │── SQLite (projects, corpora, constructs, jobs)      backend/data/ccr.db
    │── File storage (uploaded corpora, result CSVs)      backend/data/
    └── Background jobs (backend/app/jobs.py)
            └── CCR engine (backend/app/ccr.py)
                    └── sentence-transformers (local, pinned)
```

| Component | Choice | Why (and what it's not) |
|---|---|---|
| Embeddings | Local `sentence-transformers`, default `all-MiniLM-L6-v2` | Matches published CCR; pinned weights = reproducible results; text never leaves the deployment (IRB-friendly when self-hosted). Not an embeddings API: per-call cost, data leaves your control, models get deprecated mid-study. |
| Database | SQLite | Right-sized for single-node, few writers. Schema is Postgres-portable; the upgrade trigger is concurrent multi-user writes. |
| Job execution | FastAPI `BackgroundTasks`, state in DB | Zero extra infrastructure; lab-scale corpora embed in seconds–minutes. Known limits (no restart survival, no retries) are accepted MVP trade-offs; upgrade trigger to Celery+Redis is long/frequent jobs — the API contract doesn't change because job state already lives in the DB. |
| Model dependency | Injected `EmbeddingBackend` interface | Tests/CI run a deterministic hash embedder (no torch), so the full pipeline is testable in seconds. Production backend is swappable per job. |
| Frontend | React (Vite), served as static files by the API | Single deployable, no CORS in production, no Node required to run. |

## Processing robustness (bring your own corpus)

Research files are messy, so ingestion is tolerant by design: encoding fallback (UTF-8 with BOM → latin-1, with a user-facing note when fallback was needed), delimiter sniffing (`,` `;` tab `|`), ragged-row skipping, a configurable row ceiling (`CCR_MAX_ROWS`, default 100k), and a text-column suggestion heuristic. The exact parse configuration (format, encoding, delimiter) is stored per corpus and echoed into each run's reproducibility record. Runs execute on a dedicated worker queue with persisted state — jobs orphaned by a restart are marked failed with an explanation instead of hanging — and results carry data-quality notes (empty rows dropped, duplicates detected, texts likely truncated by the model's token window) so silent data issues become visible ones.

## Reproducibility & data handling

Every run records: model name + `sentence-transformers` version, embedding dimension, SHA-256 of the exact item wordings, text column, row counts (including empty rows dropped), timestamps, and library versions — downloadable as JSON next to the results CSV. Exports mirror the `ccr_wrapper` output shape (input columns + `sim_item_i` + `ccr_score`) so they drop into existing CCR workflows.

Processing is self-contained: embeddings are computed on the server running the app — text is never sent to third-party AI APIs. Run locally (`./run.sh`) and corpora never leave your machine, which is the recommended mode for sensitive data. Uploaded corpora and results live in the data directory (`backend/data/` locally; ephemeral on the hosted demo, which may reset at any time — don't upload sensitive or identifiable data there).

## Construct library — verify before research use

The seeded scales (SWLS; MFQ Care & Fairness; Triandis & Gelfand Individualism/Collectivism) carry citations, but item wordings must be **verified verbatim against the original publications before research use** — CCR's validity rests on using the validated instrument as published.

## Known limitations / roadmap

- **Method nuance:** cosine similarity captures construct *relatedness* more than stance — a text lamenting life dissatisfaction can sit near SWLS items in embedding space. Reverse-scored items need care, and results should be validated against human-annotated subsets for new constructs/corpora.
- No auth/multi-user yet (single-lab, local deployment); add before any public hosting, along with per-user quotas.
- `BackgroundTasks` → Celery+Redis when corpora grow; SQLite → Postgres with multi-user concurrency; local files → S3/GCS if deployed off-machine.
- Embedding cache keyed on (model, item-set hash) to make repeated runs on the same construct instant.

## Development

```bash
# backend tests (fast — no ML deps needed)
cd backend && pip install -r requirements-dev.txt && python -m pytest tests/ -q

# frontend dev server (proxies /api to :8000)
cd frontend && npm install && npm run dev

# rebuild the shipped dashboard
cd frontend && npm run build   # outputs to backend/static/
```

Tests cover the CCR engine (determinism, normalization, scoring) and the full API flow: project → upload → job lifecycle → results summary → export shape → validation errors.
