# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/). User-visible changes only.

## [Unreleased]

### Changed
- Every construct in the library now carries a verification decision. The two
  wording questions left open by the August review were settled: the IPIP Big
  Five scales keep the leading "I" on their items (that wording came from the
  lab's own questionnaire spreadsheet, not from the platform), and the K10 was
  withdrawn rather than rewritten. 93 constructs are live and verified.
- The K10 is no longer offered. Its items are stored as bare fragments
  ("nervous?", "worthless?") because the scale prints them under a shared
  header, and CCR embeds item text directly, so a one-word item does not carry
  the construct. It is archived rather than deleted: runs that used it still
  open, export, and reproduce exactly as before.
- Languages are shown by name instead of ISO code: the text-language selector,
  the runs table, the model list, and the language warnings now say "Arabic"
  rather than "ar". Codes are unchanged everywhere they are recorded (run
  metadata, the results CSV, construct files), so exports and reproduction
  scripts are byte-identical to before. Requested by Mohammad Atari.
- Construct library verified against the source publications. All 525 items across the
  94 constructs were reviewed (wording, reverse-scoring keys, subscale grouping,
  citations); 88 constructs are now marked verified and show who reviewed them and
  when, instead of the blanket "needs verification" flag every construct carried. The
  review corrected 61 reverse-scoring flags across 14 constructs (the library had 35
  flagged items, it now has 96), 8 item wordings, the item order of two scales that did
  not match their own source (which decides what the per-item export columns line up
  with, though not the scores), one subscale grouping in the SCS-SF, and a batch of dead
  or incomplete citation links. Corrected constructs ship as a new
  version: the picker offers the corrected one, and runs that used the earlier version
  still open, export, and reproduce exactly as before. Six constructs stay flagged, all
  for the same two open wording questions: the five IPIP Big Five scales and the K10.
  (spec 0007)

### Added
- "Cite this platform" in the landing-page footer, asked for by Ali Hajian
  (2026-09-09) and modelled on Google Scholar's Cite button: the reference in
  APA, MLA, Chicago, Harvard and Vancouver, click one to copy it, plus BibTeX
  and RIS for EndNote, Zotero and Mendeley. The dialog also names the two CCR
  papers a methods section needs beside the platform, and the BibTeX and RIS
  carry all three entries. The version in the citation is the same one stamped
  into every run's metadata, so a paper and its reproducibility record agree.
  The repository gained a CITATION.cff, so GitHub shows a "Cite this
  repository" button with the same details.
- Example corpora now state their licence, in the info dialog and in the run
  metadata alongside the citation. The CAMEL corpus is CC BY-NC 4.0, which the
  repository's MIT licence does not cover, and the README and sample_data notes
  now say so for the bundled sample.
- Sample data built into Step 1: under the upload row, "Use sample data" opens
  the lab's CAMEL corpus (Cultural and Moral Expressions in Language) in two
  sizes. The 999-text sample loads with one click, with the right text column
  selected for you, so you can run CCR without uploading anything and see a
  result in seconds. The complete 57,174-text corpus, annotated for 25 cultural
  and moral constructs, sits beside it for real analyses, labelled with its
  cost. "About" on either shows the description, text column, preprocessing,
  citation and source link, and the citation is written into the run metadata
  of any analysis you run on it, so attribution travels with your results.
  Picking a size you already loaded selects that copy rather than loading it
  again. A corpus larger than the instance's row limit is shown as unavailable
  with the reason, instead of failing after you pick it. Corpus by Zewail et
  al. (2026). (spec 0010)
- Anonymous work is now private to the browser that made it, and is adopted into
  your account when you sign in. Anonymous visitors previously shared one bucket,
  so they saw each other's projects and custom constructs; each visitor now has
  their own session. Signing in moves that session's projects and constructs to
  the account, so nothing is lost by starting without one. (spec 0009)
- Custom constructs made without an account are removed after 24 hours, like
  anonymous projects. They previously had no expiry at all: uploads are deleted
  as soon as a run finishes and projects expire daily, but a custom construct
  stayed in the picker permanently, which is what filled up the public site. A
  construct a saved run used is kept, so that run still works. (spec 0009)
- Anonymous visitors can create 5 custom constructs a day (configurable via
  CCR_ANON_MAX_CONSTRUCTS_PER_DAY); signing in lifts the limit. Saving a
  construct without an account now says it is browser-only and offers sign-in.
  (spec 0009)
- Delete a custom construct, from a confirmation dialog in the picker that names
  the construct. A construct already used by a run is hidden rather than removed,
  so that run, its results, and its reproduction script keep working; one that
  has never been used is deleted outright. Library constructs cannot be deleted.
  (spec 0008)
- Runs now warn when every item in a construct is reverse-scored. Scores are raw
  similarities with no reverse adjustment, so for such a construct a higher score means
  the text expresses the OPPOSITE of the construct's name. The results page previously
  told every run that higher meant more of the construct; it now defers to this warning,
  which names the construct affected. Four library constructs are in this position after
  the review: De Jong Gierveld social loneliness and the three SCS-SF negative subscales.
- Model picker timing estimates are real measurements instead of placeholders. Every
  model in the registry now records seconds per 1,000 texts for short, medium, and long
  texts, with the machine and date they were measured on.

### Fixed
- The sample corpus is visible without hunting for it, and reads as part of the
  form. Step 1 now presents uploading and starting from a sample corpus as two
  branches separated by an "or" rule, with the sample picker using the same
  label and control shape as the fields above it. It was previously a collapsed
  link opening a grey panel, so the CAMEL corpus was never named on screen and
  people looking for it by name did not find it.
- Runs table on phones: Status and View results were off the right edge and
  needed a sideways scroll to reach. Each run is now a stacked card with every
  field labelled, so nothing is cut off and nothing is hidden.
- The rest of the app fits a phone screen too (reported by Ali Hajian
  2026-09-09, after the runs table). The results tables no longer need a
  sideways drag: the highest and lowest scoring texts wrap their text beside
  the score, and an interrelations matrix of two or three constructs fits the
  screen (a wider matrix still scrolls inside its own box, as a matrix must).
  A multi-construct results page previously scrolled sideways as a whole,
  because each construct's summary line (mean, SD, items, CSV columns) was set
  never to wrap; it now sits under the construct name. On the public guide, the
  reproduction commands wrap inside their code block instead of widening every
  paragraph on the page. Checked at 360 and 390 px across the landing page,
  dashboard, all three steps, the pickers and dialogs, single, multi-construct
  and anchored results, and the guide.
- The full CAMEL corpus now loads on the lab's deployment. Copying it into a
  project used a server-side storage copy, which that account's object storage
  does not support; it now falls back to uploading the copy the server already
  has, which works on any S3-compatible backend.
- Creating a project or a custom construct without signing in works again. Since
  2026-09-04 both deployments returned a server error for anonymous visitors:
  the new anonymous session owner key was 37 characters and the database column
  holds 32. Signed-in users were unaffected, which is why it went unnoticed.
  Local SQLite installs never hit it either, because SQLite ignores column
  length limits and PostgreSQL enforces them.
- Custom constructs are private to the person who created them. A construct
  anyone typed on the public site was listed to every other visitor, including
  under a heading that read "My custom constructs", because constructs had no
  owner at all. Signed-in users now see the library plus only their own; the
  anonymous bucket stays shared, as anonymous projects already do. Constructs
  that already exist become anonymous on upgrade, so they leave every signed-in
  user's picker immediately. Reported by a PhD student on the public site.
  (spec 0008)
- Deleting a project works again on the deployed instances, and expired
  anonymous projects are actually purged. Both go through one cascade that
  removed rows in an order the database could reject, so "Delete project"
  returned a server error and the hourly retention sweep stopped on the first
  expired project that had ever been run, leaving anonymous projects and runs
  in place past their 24 hour window. Uploaded files were never affected: an
  anonymous run's corpus is still deleted the moment the run finishes. Local
  SQLite installs never hit either bug.
- PsyEmbedding models now load through the standard sentence-transformers path.
  The lab's four Hugging Face repos were missing the 1_Pooling config their
  modules.json references; the fix was pushed upstream (2026-08-22), the
  registry re-pins each model to the fixed revision (one commit above the old
  pin, identical weights, identical scores), and the pooling_fallback
  workaround is gone from models.yaml. Reproduction scripts for new runs use
  the plain one-line loader; scripts from older runs still carry the explicit
  module assembly and keep working.
- Signed-in users no longer see other people's anonymous projects. A signed-in
  account's project list shows only its own projects; projects created without
  signing in stay in the shared anonymous space.
- The site identity footer now shows only on the public welcome page, not on the
  dashboard and results views.

### Added
- Anchor vectors (bipolar constructs): a run can score texts along the axis between a
  target construct and a contrasting "opposite" construct (anchor vector = target
  centroid minus opposite centroid), with a cosine (default) or dot-product metric.
  Results are bipolar - the distribution is centered on zero, top/bottom texts are
  labeled "most <target>" / "most <opposite>", and item loadings show per pole. The
  export adds target_/opposite_ per-item similarities, both per-pole CCR scores, and
  anchor_score under output_schema_version 1.2; run metadata records both construct
  snapshots and the scoring block; the reproduction script embeds both item sets and
  reproduces the anchor-vector math. (spec 0006)
- Public guide (/guide): a "Sample datasets" section that links ready-to-run example
  corpora (served from /samples) so new users can try CCR without their own data, with
  a pointer from the upload step. Suggested by Meriel Burnett.
- Real accounts: register/sign in with email + password (free, no external service).
  Signing in lifts anonymous limits and keeps your data. No self-service password
  reset yet (contact the admin); Google sign-in arrives with the managed-auth swap.
- Anonymous usage tiers (PI decisions): 3 runs/day (counter shown under the Run
  button, resets daily), uploads deleted immediately after analysis (results stay
  downloadable), whole anonymous projects purged after 24h on hosted instances.
- Saved-run cap for signed-in users (15): new runs are refused at the cap; nothing
  is ever auto-deleted from an account.
- Project ownership: signed-in projects are private to their owner; anonymous
  projects remain shared.
- Custom constructs can be uploaded from CSV/XLSX (item column or one per row;
  reverse-scored via a "reverse" column or trailing "(R)"), with a review-before-
  save preview. Typed items also support the "(R)" reverse marker.
- Runs table now shows the model and language of every run.
- Corpus-embedding cache: re-running new constructs against the same corpus skips
  document embedding entirely (seconds instead of minutes). Duplicate texts are
  embedded once. Gzip compression on API responses. Optional model pre-warm at
  startup (CCR_WARM_MODEL=1).
- MANUAL_TESTING.md: click-through scenarios for everything built so far.
- Deployment-ready container: updated Dockerfile (bakes MiniLM, retention on,
  persistent-volume instructions), production env vars documented in .env.example
  (CCR_SESSION_SECRET, CCR_COOKIE_SECURE, CCR_ANON_TTL_HOURS).
- Demo/test corpus kit in sample_data/ (one file per behavior): all text-QA warnings,
  French and mixed-language corpora for every language check, token-window truncation,
  multi-column text suggestion, semicolon and latin-1 ingestion, XLSX upload, and an
  MFQ-2-themed corpus showing per-foundation score spread. sample_data/README.md maps
  each file to what it triggers.
- Searchable construct picker replacing the flat dropdown: search by scale, construct, or
  category; results grouped by category; recently-used constructs pinned on top; full
  keyboard navigation. Scales to hundreds of library entries.
- Construct library expanded from 5 to 99 entries from the lab's questionnaire collection
  (38 questionnaires; multi-dimensional scales split per dimension, incl. MFQ-2's six
  foundations). Reverse-scored flags imported where the source marked them; filler items
  excluded; everything flagged needs-verification pending verbatim wording checks.
- Reusable importer for the lab's questionnaire spreadsheet format
  (packages/construct_library/import_from_xlsx.py).
- Anonymous vs signed-in upload tiers: anonymous uploads capped at 2 MB / 500 rows with a
  clear sign-in hint; signing in lifts limits. Sign-in is a labeled placeholder (name only)
  until managed auth arrives with lab accounts; tampered sessions are treated as anonymous.
- Project lifecycle: archive/unarchive (reversible, collapses into an Archived sidebar
  group) and permanent delete with type-the-name confirmation. Delete cascades to datasets,
  runs, uploaded files, and result files, and is logged without retaining any text.
- Public how-to guide at /guide (open to everyone): the upload to construct to run to
  export walkthrough, the four ways to add a construct (library, typed, uploaded, AI
  drafting) with the live AI model and prompt-version details, the models table, and a
  reproducibility section covering the results CSV, run metadata, and the offline
  reproduction script.
- AI construct path shows the drafting model on demand: a "Drafted by <model>" line with
  a hover/focus info bubble listing the model, provider, prompt version, item rules, and
  daily cap, read live from the API so it always matches the configured model.

### Changed
- Project-wide style rule: no em dashes in any project text (enforced by an edit hook).
- Guides split: /guide is now the public how-to guide; the click-through testing guide
  moved to /testing and is lab-only (same gate as /product). Lab members reach both from
  the header.
- Landing page links the PI's name (Mohammad Atari) to his website.

### Fixed
- Google sign-in no longer breaks when CCR_APP_URL is pasted with a trailing
  newline or space: the app trims the value before building the sign-in return
  URL. Untrimmed, the newline reached Supabase as %0A inside the redirect, so
  the redirect never matched the allow list and browsers flagged the link.
- Existing local databases no longer 500 after schema additions: additive
  SQLite auto-migration adds missing columns at startup (Alembic replaces this in
  Phase 2 with Postgres).
- Job worker survives lifespan restarts (dev reload previously killed job submission
  permanently).

### Fixed
- Project sidebar redesigned for growing lists: always-visible search, recency groups
  (Today / This week / Earlier), per-project run count + relative last-activity time,
  and ordering by last activity instead of creation date.
- Improved dashboard responsive layout, focus states, and table overflow handling on
  narrow screens.
- Aligned the run-analysis action with the model/language controls and made the project
  sidebar scroll cleanly as project counts grow.

### Added
- Repository initialized from the public demo (v0.1 feature set: projects, tolerant CSV/XLSX
  ingestion, seeded constructs, MiniLM/mpnet/multilingual models, async runs with progress,
  results dashboard with descriptive stats + per-item loadings + top/bottom texts,
  data-quality warnings, CSV export mirroring ccr_wrapper shape, reproducibility metadata).
- Model registry (packages/model_registry) and versioned construct library
  (packages/construct_library) with validators - not yet wired into the app (specs 0003/0004).
- Claude Code project config: CLAUDE.md, path-scoped rules, 3 review agents, 4 commands,
  golden-file protection + Python syntax hooks.

## [0.2.0] - 2026-07-09

### Added
- Language selection per run (English default) with corpus-level language detection:
  warnings for language mismatch, uncertain detection, and model/language coverage
  (multilingual model checked against its real ISO language set). (spec 0001/0003)
- Very-short-text warning (< 4 words) with affected-row samples. (spec 0001)
- Downloadable Python reproduction script per run - offline-runnable, embeds construct
  items, model revision, and E5 prefix logic - plus pinned requirements file. (spec 0002)
- Model registry drives the model dropdown, validation, prefixes, and metadata:
  MiniLM (default), E5-Large-v2, Multilingual-E5-base. (spec 0003)
- Construct library loaded from versioned YAML files with item hashes, citations, and
  verification status shown in the UI; custom constructs support reverse-scored flags. (spec 0004)
- Run metadata now records: output_schema_version, scoring.adjustment_strategy, language
  block, construct snapshot, model revision, environment pins.

### Changed
- All warnings are structured objects (code/severity/message/count/rows) - UI renders codes.
- /api/models response shape changed (registry ids like "all-minilm-l6-v2" replace provider ids).
- Delimiter detection restricted to real candidates (, ; tab |) - fixes single-column
  sentence CSVs being split on spaces.

### Removed
- backend/app/seed_constructs.py (replaced by packages/construct_library YAML).
