# Manual testing guide

Everything built so far, as click-through scenarios. Each scenario says what to
do and exactly what you should see. Files referenced live in `sample_data/`
(see `sample_data/README.md` for what each one triggers).

## 0. Setup

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Open http://127.0.0.1:8000. First start downloads MiniLM (~90 MB) on the first
real run; set `CCR_WARM_MODEL=1` to preload it at startup instead.

To test quickly without models: `CCR_FAKE_EMBEDDINGS=1 uvicorn ...` (scores are
fake but every flow works; never use for real analysis).

## 1. Projects and sidebar

1. Create three projects. They appear under "Today", newest activity first.
2. Type in the sidebar search box: list filters as you type.
3. Archive a project (project header > Archive): it moves into the collapsed
   "Archived" group; Unarchive brings it back. No data is lost either way.
4. Delete a project: requires typing the project name; removes its datasets,
   runs, and files permanently.

## 2. Upload paths (Step 1 card)

| Upload | Expect |
|---|---|
| `sample_corpus.csv` | Parses, 60 rows, `text` column suggested |
| `multi_column_demo.csv` | 5 columns; `comment_text` marked "(suggested)" |
| `semicolon_delimited_demo.csv` | Parses into exactly id + text (commas inside texts intact) |
| `latin1_encoding_demo.csv` | Parses with a ⚠ note: decoded as latin-1; fiancée/café render correctly |
| `xlsx_upload_demo.xlsx` | Parses like a CSV |
| a `.txt` or `.pdf` file | Rejected: unsupported file type |

Anonymous limits (signed out): the Step 1 hint shows 2 MB / 200 rows and says
uploads are deleted after analysis. Upload `large_demo.csv` (800 rows): rejected
with a "Sign in (top right)" message. Sign in and retry: accepted.

## 3. Construct selection (Step 2 card)

1. Open the picker: search field + panel below it, library grouped by category,
   with "Recently used" pinned on top after your first runs.
2. Type "GAD" or "empathy": matches by name and category; Arrow keys + Enter work.
3. Select any imported construct: items listed, plus the "not yet verified
   verbatim" notice (expected for the whole imported library for now).

### Custom construct, typed

1. "+ Custom construct" > name it, paste items one per line.
2. Append `(R)` to one line: the form shows "1 item(s) marked reverse-scored".
3. Save: it appears in the picker under "My custom constructs"; run metadata
   will carry the reverse flag (check via Results > metadata download).

### Custom construct, from file (new)

1. "+ Custom construct" > "Upload items from CSV/XLSX".
2. Try a CSV with `item,reverse` columns (1/true/yes/R = reverse) or a
   single-column file with `(R)` markers.
3. Expect: items fill the textarea ((R) appended where flagged), the filename
   becomes the suggested name, and parse notes list skipped duplicates (and
   blank cells in multi-column files; fully blank lines are dropped at read).
   Nothing is saved until you review and press Save. Item files are never
   retained on the server.

## 4. Language, models, and warnings (Step 3 card + results)

Run each of these and open the results page; the amber warnings panel should
show exactly:

| Corpus | Selection | Expected warnings |
|---|---|---|
| `warnings_showcase.csv` | en + MiniLM | EMPTY_ROWS_DROPPED (2), DUPLICATE_TEXTS (2), TEXT_TOO_SHORT (3), TEXTS_MAYBE_TRUNCATED (2); no language warnings |
| `french_demo.csv` | en + MiniLM | LANGUAGE_MISMATCH (detected fr, 100%) |
| `french_demo.csv` | fr + MiniLM | MODEL_LANGUAGE_UNSUPPORTED |
| `french_demo.csv` | fr + Multilingual E5 | no language warnings |
| `mixed_language_demo.csv` | en + MiniLM | LANGUAGE_UNCERTAIN (majority 50%) |
| `long_documents_demo.csv` | en + MiniLM | TEXTS_MAYBE_TRUNCATED (4) + LANGUAGE_UNCERTAIN (only 10 rows, below the 20-row minimum - by design) |

Warnings are per-run snapshots: changing language/model requires a NEW run;
old result pages don't update.

## 5. Results and reproducibility

1. Run `moral_foundations_demo.csv` against two different MFQ-2 foundations:
   top texts change per foundation; the 6 neutral rows sink to the bottom.
2. Results page: histogram, mean/SD/min/max, per-item loadings, top/bottom texts.
3. Downloads: results CSV (input columns + sim_item_N + ccr_score), metadata
   JSON (model revision, construct snapshot + item hash, language block,
   environment pins), reproduction script + requirements file.
4. Reproduction check: both downloads carry your run's id, e.g.
   `pip install -r requirements-repro_<run-id>.txt`, then
   `python reproduce_analysis_<run-id>.py your_corpus.csv` on a machine with no
   platform access; the exact commands (with your run id and CSV name) are in
   the script's header. Values should match the export (target ~1e-5 with real
   models).

## 6. Accounts

1. Sign in (top right) > "Create a free account" > email + password (min 8 chars).
2. You're signed in immediately; header shows your name.
3. Sign out, sign back in; wrong password gives "Incorrect email or password";
   registering the same email again gives "already exists".
4. Email is case-insensitive. There is no self-service password reset yet
   (interim local accounts; Google/Supabase swap planned) - reset = admin action.

## 7. Anonymous tiers (test signed OUT)

1. Upload caps: see section 2.
2. Run limit: run 3 analyses (default). The Step 3 card counts "X of 3 free
   runs used today". The 4th run is refused with a sign-in prompt (HTTP 429).
   Counter resets next day (UTC). Signing in removes the limit.
3. Delete-after-analysis: run any corpus, open results (fine, downloadable),
   note the info warning "uploaded file was deleted after this analysis".
   Re-running that same corpus: refused ("upload again, or sign in").
4. TTL purge: with `CCR_ANON_TTL_HOURS=24` (deployment default; 0 = off in
   local dev), anonymous projects older than 24h are deleted entirely,
   startup + hourly.

## 8. Signed-in tier

1. Sign in, upload, run: no ANONYMOUS_DATA_REMOVED warning; re-running the same
   corpus works (file kept).
2. Saved-run cap: Step 3 card shows "N of 15 saved runs used". At the cap, new
   runs are refused until you delete old runs/projects (nothing is auto-deleted).
3. Ownership: your projects are invisible to signed-out visitors and other
   accounts (they get 403 on any modification). Anonymous projects stay shared.

## 9. Performance behaviors

1. Corpus-embedding cache: run the SAME corpus with a second construct
   (signed in, same model): the run skips document embedding and completes in
   seconds; metadata shows `"doc_embeddings_from_cache": true`.
2. Duplicate texts are embedded once (`warnings_showcase.csv` has 2 dupes):
   identical scores for identical texts, less compute.
3. API responses are gzip-compressed (check the response headers).

## 10. Robustness

1. Restart the server mid-run: the orphaned job is marked failed with an
   explanation, never stuck at "running".
2. A DB from an older version gains new columns automatically at startup
   (additive auto-migration) - no more "no such column" 500s.
3. Tampered session cookie = treated as signed out, no error.

## 11. Deployment (container)

```bash
cd frontend && npm run build && cd ..
docker build -t ccr-platform .
docker run -p 7860:7860 \
  -e CCR_SESSION_SECRET=$(python3 -c "import secrets;print(secrets.token_hex(32))") \
  -e CCR_DATA_DIR=/data -e CCR_COOKIE_SECURE=1 \
  -v ccr_data:/data ccr-platform
```

Checklist before giving the URL to real users:
- [ ] `CCR_SESSION_SECRET` set (sessions survive restarts)
- [ ] `CCR_COOKIE_SECURE=1` (HTTPS only)
- [ ] `CCR_DATA_DIR` on a persistent volume (default /tmp is ephemeral)
- [ ] `CCR_ANON_TTL_HOURS=24` (default in the image)
- [ ] Supabase: RLS shows enabled on all public tables (the app enables it
      automatically at startup; the Supabase dashboard linter should report
      zero `rls_disabled_in_public` issues)
- [ ] Smoke test: sections 2, 4, 6, 7 above

## 12. Admin page (/admin)

Requires `ADMIN_EMAILS` to include your signed-in email (see .env.example),
OR a pi/maintainer role. The env allowlist is bootstrap + break-glass; the
PI role carries the same escalation rights in-app. The full access model is
documented at /product.

1. Sign in with an allowlisted or staff account: an "Admin" link appears in
   the header; non-admins (and signed-out visitors) see an access notice.
2. Overview: account/run/project counters plus scales awaiting verification.
3. Users - four tiers (external user, lab member, maintainer, PI):
   - Set a user to "lab member" or above: their saved-run cap disappears
     (check /api/auth/me shows max_saved_runs null).
   - Set a user to "maintainer" or "PI": they also get this admin page.
   - Escalation needs PI or env-admin rights: a maintainer gets 403 on
     granting pi/maintainer, and on resetting the password of, changing the
     role of, or deleting a pi/maintainer account. A PI-by-role CAN do all
     of that (no env entry needed). Nobody can change their own role.
   - Reset a password (temporary password shown once; old one stops working),
     delete a user (removes all their data; self-deletion refused).
4. Access before sign-in:
   - Pre-assign a role to an email (staff roles need PI/env rights): register
     with that email afterwards - the account lands at that tier, the
     assignment shows "claimed". Works for Google sign-ins too.
   - Create an invite link (lab member or external only): open it in a
     private window - the signup form announces the invite; registering
     through it grants the role. The invites table shows each link's status
     (active/expired/revoked) and who signed up through it ("used by");
     Copy link re-copies an active link, Revoke kills it immediately.
     Expired/garbage/revoked tokens refuse registration.
5. Construct verification is maintainer-only: PI/env admins see the queue
   read-only (no action buttons; the API returns 403), a maintainer can mark
   scales verified. Statuses are applied back to the library YAML before
   production.
6. Audit trail (PI/env admins only; maintainers get 403 and don't see the
   card): every role change, reset, deletion, invite, pre-assignment,
   requeue, and verification appears with actor, target, and time.
4. Failed runs: a failed job lists with its error tail; Requeue re-runs it
   (refused when the corpus file is already gone - anonymous retention).
5. Verification: mark a scale Verified; its "unverified" flag disappears
   platform-wide. Statuses are applied back to the library YAML before
   production.
