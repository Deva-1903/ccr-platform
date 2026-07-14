# Sample data: demo and test corpus kit

One file per platform behavior. To demonstrate or manually test something, upload the
file named for it and follow the "How to trigger" column. Unless stated otherwise,
select language English and model MiniLM.

| File | Demonstrates | How to trigger / what you see |
|---|---|---|
| `sample_corpus.csv` | Clean baseline run (60 rows) | Run any construct; no warnings expected |
| `warnings_showcase.csv` | All text-QA warnings at once | Run as-is: EMPTY_ROWS_DROPPED (2), DUPLICATE_TEXTS (2), TEXT_TOO_SHORT (3), TEXTS_MAYBE_TRUNCATED (2). Language detects cleanly as English, so no false language alarms |
| `french_demo.csv` | Language checks (24 French rows) | Select English: LANGUAGE_MISMATCH (detected fr at 100%). Select French + MiniLM: MODEL_LANGUAGE_UNSUPPORTED. Select French + Multilingual E5: no warning |
| `demo_spanish.csv` | Same checks in Spanish + short rows | Select English: LANGUAGE_MISMATCH; includes "si"/"no" rows for TEXT_TOO_SHORT |
| `mixed_language_demo.csv` | Uncertain detection (15 EN + 15 ES) | Majority is 50%, below the 70% threshold: LANGUAGE_UNCERTAIN, checks skipped rather than guessed |
| `long_documents_demo.csv` | Token-window truncation | 4 of 10 texts exceed MiniLM's 256-token window: TEXTS_MAYBE_TRUNCATED. Results table shows snippet ellipsis on long texts |
| `moral_foundations_demo.csv` | Meaningful score spread (42 rows, 6 themed per MFQ-2 foundation + 6 neutral) | Run each MFQ-2 foundation against the same corpus: top texts change per foundation, neutral rows sink to the bottom. Also the corpus-reuse story: same corpus, many constructs |
| `multi_column_demo.csv` | Text-column suggestion | 5 columns (id, author, comment_text, created_at, upvotes); the app should suggest `comment_text` |
| `semicolon_delimited_demo.csv` | Delimiter sniffing | Semicolon-separated, texts contain commas; parses into exactly id + text |
| `latin1_encoding_demo.csv` | Encoding fallback | Not valid UTF-8; ENCODING_FALLBACK warning, accented words (fiancée, café) must render correctly |
| `xlsx_upload_demo.xlsx` | Excel ingestion path | Uploads and parses like a CSV |
| `large_demo.csv` | Anonymous upload caps (800 rows) | Signed out: blocked with the sign-in hint. Signed in: runs |
| `construct_items_demo.csv` | Construct upload: item + reverse columns | + Custom construct > upload: 6 items parse, last one flagged reverse-scored |
| `construct_items_marker_demo.csv` | Construct upload: (R) markers, blank + duplicate rows | 4 items parse (blank and duplicate skipped, notes say so); "(R)" line flagged |
| `construct_items_demo.xlsx` | Construct upload from Excel | 4 items, two flagged reverse via (R) markers |

Notes:

- Files with fewer than 20 detectable rows (long_documents, multi_column, semicolon,
  latin1, xlsx) also show an info-level LANGUAGE_UNCERTAIN notice. That is the
  minimum-rows guard by design: the platform refuses to judge a corpus language from a
  handful of rows instead of guessing.
- Warnings are computed per run and stored in that run's results. To see different
  warnings, start a new run with the relevant selection; old result pages do not update.
- All texts are synthetic, written for this kit. No real participant data anywhere.
