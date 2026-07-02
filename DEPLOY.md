# Deploying the demo

## Option A — Hugging Face Spaces (free, recommended for the demo)

Free Docker Spaces: 2 vCPU / 16 GB RAM, no credit card. Bonus: the original
CCR online tool lives on HF Spaces, so the prototype sits where the CCR
community already works.

1. Create the Space at https://huggingface.co/new-space →
   SDK: **Docker** → visibility: Public → name: `ccr-platform`.

2. HF reads deployment config from YAML frontmatter at the top of the
   Space's `README.md`. Add this block (top of the file) before pushing:

   ```yaml
   ---
   title: CCR Platform
   emoji: 🧭
   colorFrom: red
   colorTo: gray
   sdk: docker
   app_port: 7860
   pinned: false
   ---
   ```

3. Push this repo to the Space:

   ```bash
   git remote add hf https://huggingface.co/spaces/<your-username>/ccr-platform
   git push hf main
   ```

   First build takes ~5–10 min (model bakes into the image). Watch the
   build logs in the Space's "Logs" tab.

4. Optional hardening for the public instance — in Space Settings →
   Variables, set `CCR_MAX_ROWS=20000` (tighter ceiling than the
   100k default while strangers can reach it).

Notes:
- Storage is **ephemeral** — uploads/results vanish on restart or rebuild.
  Fine for a demo; the email and the in-app welcome text both say so.
- Free Spaces sleep after ~48h without traffic. Visit the URL the
  evening before and the morning of the interview so it's warm.
- The direct app URL (no HF frame) is
  `https://<username>-ccr-platform.hf.space` — send that one.

## Option B — Google Cloud Run (few dollars, more "prod-like" URL)

```bash
gcloud run deploy ccr-platform \
  --source . \
  --region us-central1 \
  --allow-unauthenticated \
  --memory 2Gi \
  --cpu 2 \
  --min-instances 1 \
  --max-instances 1 \
  --concurrency 20
```

- `--min-instances 1`: no cold starts while he plays with it (~a few
  dollars for the week; delete the service after the process ends).
- `--max-instances 1`: SQLite + in-process queue assume one instance —
  documented demo trade-off, not an oversight.

## Pre-send checklist (either host)

1. Open the URL in an **incognito window and on your phone (off Wi-Fi)**.
2. Full run: new project → upload `sample_data/sample_corpus.csv` →
   Satisfaction with Life → Run → results render → Export CSV downloads.
3. Second run (Individualism) finishes in seconds (model + item cache warm).
4. Upload your own messy CSV (Excel export with a BOM, or semicolon-
   delimited) — parses, and any fallback is flagged in the UI.
5. Upload rejects a bogus file (.txt/.exe) with a clean error.
6. Refresh the page — SPA loads, project still listed.
7. Morning of the interview: open the URL once (warm the instance),
   re-run step 2 quickly.

If anything fails, fix before sending. No link is better than a broken link.
