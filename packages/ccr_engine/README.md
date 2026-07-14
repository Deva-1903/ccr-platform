# ccr_engine (Phase 1 target - spec 0005)

This package will hold the pure CCR analysis engine: preprocessing, embeddings (via the model
registry), similarity, scoring/aggregation, warnings, stats, reproducibility artifacts -
callable from the web app, worker, tests, CLI, and generated scripts.

Today the engine logic lives in `backend/app/ccr.py` + `backend/app/jobs.py`. Do NOT start the
extraction ad hoc: it begins by freezing current behavior with golden evals (strangler step 1,
design §7), then moves code behind the `run_ccr_analysis(...)` interface (design §10).

Boundary rule (enforced in review): nothing in this package may import from `backend/app`.
