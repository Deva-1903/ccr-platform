# Roadmap

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

## Sequencing

Anchor vectors first (pure scoring change, no ingestion changes), then
chunking (touches ingestion, warnings, cache keys - chunked and unchunked
embeddings must not share a cache entry).
