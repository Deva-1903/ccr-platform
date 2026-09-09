# Roadmap

## Backlog (pick one at a time)

Working list as of 2026-07-31 - features, bugs, and chores in rough priority
order. Detailed specs for the numbered features live in the sections below.

**Features**
- [x] PsyEmbedding models in the picker (PI short-term ask): all four models
      in the hub collection are in the registry and live on dev - verified
      against huggingface.co/collections/Culture-and-Morality-Lab/psyembedding
      2026-07-31.
- [x] LLM-generated construct items (PI idea 2026-07-31): BUILT 2026-08-05
      (see ITEM_GENERATION.md). Design note + PI-approved prompt and
      cautionary wording; POST /api/constructs/generate-items (signed-in,
      20/day cap, Claude Haiku, preview-only into the existing review-and-save
      flow); provenance on construct + run metadata; badges in picker/results.
      Remaining before Friday launch: ANTHROPIC_API_KEY on the Space (billing),
      live smoke test, then the SWLS/MFQ validation run (correlate per-text
      CCR scores from generated vs. validated items).
- [x] Anchor vectors / bipolar constructs (feature 2 below): SHIPPED 2026-08-22
      (spec 0006). AV = C - C_opposite centroids with a cosine default and a
      dot-product toggle, both item sets entered or uploaded, bipolar results
      and export at output_schema_version 1.2. Live on dev; NOT yet on the lab
      production Space.
- [ ] Automatic chunking for over-limit rows (feature 1 below). PI re-sent
      the spec 2026-07-31; matches feature 1 (optional, warn about
      truncation without it, chunk-embedding vs chunk-similarity averaging
      still an open question for him).
- [x] CAMEL as the built-in example corpus: DONE 2026-09-07 (spec 0010). The
      999-text sample is the default (seconds to run) and the full 57,174-text
      corpus is offered beside it, served from R2 under examples/. Citation and
      provenance travel into run metadata. CCR_MAX_ROWS raised to 100,000.
- [x] CAMEL dataset link: no action needed (checked 2026-09-07). The dataset
      is public and GATED, not private: the page opens for anyone (HTTP 200)
      and only file downloads ask for a sign-in and acceptance of the terms,
      which is normal for a research dataset. The earlier "401 for everyone"
      reading came from testing the file URL, not the page.
- [ ] Dark mode for the app - /guide and /product already have it; the React
      app doesn't.
- [ ] Decide the default model with the PI: MiniLM (CCR reference) vs. a
      PsyEmbedding model ("prominent or default" was the PI's ask).

**Bugs / fixes**
- [x] PsyEmbedding HF repos: DONE 2026-08-22. The missing 1_Pooling config
      was pushed to all four repos with lab credentials; models.yaml re-pins
      each to the fixed revision (one commit above the old pin, identical
      weights) and the pooling_fallback workaround is removed.
- [x] PsyEmbedding benchmarks: DONE 2026-08-26. All SEVEN models were
      unbenchmarked, not just the four. Each now records short/medium/long
      seconds per 1k texts, measured on an Apple M4 Pro at 2 threads and
      labelled as such. Still worth a re-run on the Space before the numbers
      are shown to users: a shared vCPU is roughly 2-4x slower.
- [ ] /admin on a phone: the users table still needs a sideways drag (six
      columns, and the role dropdown squashes to "exter"). Left as it is on
      2026-09-09 because admin is a staff tool used on a laptop; the fix is the
      same data-label stacking the runs table uses.

**Updates / chores**
- [x] Open-source warning text from the PI: received and placed verbatim on
      the landing page (2026-07-31), along with his hero copy and "Who runs
      this" text.
- [x] LICENSE: DONE. MIT, single-licensed (DECISIONS 2026-08-26); the two
      untracked drafts (a duplicate MIT and an Apache-2.0 alternative) are
      removed and README now states the license and separates it from the
      questionnaire items, which belong to their original authors.
- [x] Construct library verification pass: DONE 2026-08-27 (spec 0007). Noor's
      review of all 525 items applied, and her follow-up answers resolved every
      open question except the two PI decisions; 88 of 94 constructs verified.
- [x] Construct library: DONE 2026-09-07. Both open wording questions settled
      with the PI - the IPIP "I" stays (it came from lib.xlsx, not from the
      platform) and the K10 is retired. All 93 live constructs are verified.
- [ ] Durable source links: the Grit-S entries point at personal Dropbox URLs,
      dirty_dozen_* traded a working ResearchGate link for a paywalled PsycNET
      one (the reviewer's link carried a session token that could not be
      committed), cage_questionnaire uses a token-style USPSTF file URL, and
      mfq_care/mfq_fairness point at a third-party mirror of the cited paper.
      All four want a stable replacement.
- [x] Anonymous session identity: DONE 2026-09-04 (spec 0009). Anonymous
      visitors carry a signed session id and own their rows as "anon:<id>", so
      projects and constructs are private per browser and are adopted into the
      account on sign-in. Custom constructs also expire on the anonymous TTL
      (they previously never expired) and creation is capped per day.
- [ ] Verify Dr. Chen's maintainer pre-assignment exists on /admin and that
      she can sign in.
- [ ] Self-service password reset (currently admin-only; tied to the planned
      Supabase auth swap).
- [ ] Invite links: currently ON HOLD behind CCR_INVITES_ENABLED - decide
      keep/kill permanently.
- [ ] Celery + Redis job queue - only when multi-instance deployment or retry
      semantics are needed (see jobs.py docstring).

PI-requested features (Mohammad, 2026-07-18), grounded in Teitelbaum & Simchon
(2025), *Neural Text Embeddings in Psychological Research*, Psychological
Methods, https://doi.org/10.1037/met0000768.

## 1. Automatic text chunking for over-limit rows

**Problem.** Every model has a token window (MiniLM 256, the others 512 tokens
= roughly 350-400 English words). Rows beyond it are silently truncated today;
we only warn (TEXTS_MAYBE_TRUNCATED). In a typical upload most rows fit and a
handful do not (e.g. 190 of 200 under the limit, 10 over).

**Feature.** An optional per-run "Split long texts into chunks" toggle
(default OFF - never changes existing behavior silently).

- Detection: count tokens with the SELECTED model's own tokenizer (exact, not
  a word-count estimate). The Step 3 card shows the toggle only when the
  corpus has over-limit rows: "N rows exceed this model's 512-token window."
- Off (default): current behavior, plus the existing truncation warning, with
  hint text: "text beyond the model's window is ignored."
- On: each over-limit row is split into sequential chunks of at most
  max_seq_length tokens (example: 1,200 tokens -> 512 + 512 + 176). Rows
  within the limit are untouched.
- Row-level result from chunk results - two candidate aggregations (PI listed
  both; decide before implementation):
  a) average the chunk EMBEDDINGS (optionally length-weighted), then score
     the averaged embedding once - keeps one scoring path;
  b) score each chunk, then average the chunk SIMILARITIES per row.
- Warnings: chunked runs report TEXTS_CHUNKED (count + affected rows) instead
  of TEXTS_MAYBE_TRUNCATED for those rows.
- Reproducibility: chunking config (on/off, chunk size, aggregation) goes into
  run metadata AND the generated reproduction script, which must implement the
  identical split so exported scores reproduce offline.

**Open questions for the PI**
- Aggregation default: mean of embeddings vs mean of similarities?
- Length-weight the chunk average (176-token tail counts less) or plain mean?
- Any chunk overlap (e.g. 50 tokens) to avoid cutting sentences, or none?

## 2. Anchor vectors (bipolar constructs)

**Problem.** Plain CCR scores similarity to a single construct C. Constructs
with a natural opposite (happiness vs sadness, internal vs external locus of
control) are better measured along the direction BETWEEN the poles - this also
cancels shared confounds like "questionnaire-ness" (both poles are worded as
questionnaire items, so their difference subtracts that style component;
see the paper's Appendix B).

**Feature.** Optional second item set on a run:

- C        = centroid of the target construct's item embeddings
- C_opp    = centroid of the opposing construct's item embeddings
- AV       = C - C_opp
- loading  = cos(T, AV) for each text embedding T

Higher = toward the target pole, negative = toward the opposing pole.

- UX: in the construct picker, an "Add contrasting construct (anchor vector)"
  option opens the SAME selection flows for the opposite pole (library /
  typed / file upload). Both item sets show side by side before running.
- Data model: Job gains an optional opposite_construct_id. Metadata records
  BOTH construct snapshots + item hashes and a scoring block
  {"method": "anchored_vector", "similarity": "cosine"}.
- Results page: the score is now bipolar - histogram centered on 0, negative
  scores meaningful (toward the opposite pole), top/bottom texts labeled
  "most <target>" / "most <opposite>". Per-item loadings shown per pole.
- Reproduction script: embeds both item sets verbatim and reproduces AV math.
- Reverse-scored items: unchanged in v1 (the paper's footnote 27 suggests
  negating reverse items; our (R) flags already carry the information).

**Open questions for the PI**
- Similarity metric: cosine(T, AV) per the PI's formula; the paper found
  dot(T, AV) sometimes better (Appendix B). Config flag or fixed cosine?
- Should anchored runs also report the plain per-pole similarities
  (cos(T, C), cos(T, C_opp)) in the export for transparency?

## 3. Multi-construct runs - IMPLEMENTED

**Problem.** Each construct had to be run separately, which is slow when the
goal is to see how two or more constructs are interrelated in the same texts.

**Implemented (2026-07-23).** A run now accepts up to 10 constructs
(`POST /api/jobs` takes `construct_ids`; `construct_id` still works). The
corpus is embedded ONCE and every construct is scored against the same
document embeddings, so N constructs cost barely more than one - and the
per-text scores are row-aligned by construction.

- Results add a "Construct interrelations" card: Pearson r between per-text
  CCR scores, plus a collapsible per-construct section (histogram, item
  loadings, top/bottom texts).
- Export: per-construct prefixed columns ({slug}_sim_item_N, {slug}_ccr_score)
  under output_schema_version 1.1; single-construct exports unchanged at 1.0.
- Metadata records every construct snapshot + item hash and the correlation
  matrix; the reproduction script embeds the corpus once, scores all
  constructs, and prints the same correlations.
- A multi-construct run counts once toward the anonymous/saved-run limits;
  the constructs-per-run cap (10) bounds export width, not compute.

## Sequencing

Anchor vectors first (pure scoring change, no ingestion changes), then
chunking (touches ingestion, warnings, cache keys - chunked and unchunked
embeddings must not share a cache entry). Multi-construct runs (3) shipped
first: no scoring or ingestion changes, and the embedding-reuse plumbing it
added (one corpus pass, N scorings) is what chunking's cache work builds on.
