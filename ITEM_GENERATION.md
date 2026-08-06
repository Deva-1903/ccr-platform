# LLM-Generated Construct Items — Design Note

> STATUS 2026-08-05: BUILT. Backend: `backend/app/item_generation.py` (prompt
> v1 with the PI's final rule-6 wording), `POST /api/constructs/generate-items`
> in main.py (signed-in only, `CCR_USER_MAX_GENERATIONS_PER_DAY` default 20,
> counted in the `generation_events` table), provenance via
> `Construct.generation_json` -> `ai_generated` in the API and
> `source_type: llm_generated` + `items_source_note` in run-metadata
> snapshots. Frontend: draft-with-AI section in the custom-construct form
> (approved cautionary wording, simple library name-match warning),
> "AI-generated · not validated" labels in picker/selection/results.
> Tests: `backend/tests/test_item_generation.py` (model call mocked).
> PENDING: `ANTHROPIC_API_KEY` on the deployment (billing), one live smoke
> test, then the SWLS/MFQ validation run below.

Feature: generate questionnaire-style items ("prototypical sentences") for a
construct from its name + explanation, for use as CCR item sets when no
validated scale exists. Backlog item in ROADMAP.md (PI idea 2026-07-31).

## Decisions (PI, 2026-08-05, via Slack)

- **Item wording:** positively-keyed items only in v1. No reverse-scored "(R)"
  items — an AI-drafted reverse item that is subtly off corrupts the centroid.
  Reverse/opposite items revisit later alongside anchor vectors (feature 2).
- **Access:** signed-in users only (reuses `auth.get_current_user`; no new
  rate-limiting infrastructure).
- **Labeling:** cautionary note required in UI and exports; wording below is
  DRAFT pending PI review.
- **Timeline:** launch by Friday 2026-08-07 (dev testers first).

## Flow (mirrors the parse-file preview pattern)

`POST /api/constructs/generate-items` (signed-in only) takes
`{name, description, n_items}` and returns proposed items as a **preview
only** — nothing is saved. The frontend fills the existing NewConstructForm
textarea; the researcher reviews/edits/deletes, then saves through the normal
`POST /api/constructs` path (`verification_status="draft"`). Generation
metadata (model ID, prompt version, timestamp) is recorded on the saved
construct so runs and reproduction scripts carry provenance.

Before generating, the UI searches the built-in library by construct name and
suggests an existing validated scale if one matches.

## Model options and cost

Each generation is tiny: ~600 tokens in (system prompt + the researcher's
construct) and ~300 out (10 items + notes), ~900 tokens total. That makes cost
a rounding error on every option below — the real axes are item quality (these
items ARE the measurement instrument, so quality has scientific stakes) and how
much infrastructure we want to own. Three tiers:

### Tier 1 — hosted frontier API (paid, but ~free at this volume)

Best quality and most reliable structured output / item-writing craft. Cost per
generation (~900 tokens):

| Model | Price (in/out per 1M) | ~ per generation | 1,000 generations |
| --- | --- | --- | --- |
| Claude Haiku 4.5 | $1 / $5 | ~$0.002 | ~$2 |
| Claude Sonnet 5 | $3 / $15 | ~$0.006 | ~$6 |
| Claude Opus 4.8 | $5 / $25 | ~$0.010 | ~$10 |

Realistic lab usage (a lab plus invited collaborators, a few generations per
construct) is single-digit dollars per year. "Payments" here means a small
prepaid balance on an API key, not a recurring budget line. OpenAI's GPT tiers
are comparable on price and quality if preferred.

### Tier 2 — hosted open-source (paid, cheaper still; open weights)

Open-weight models (Llama 3.1 8B, Qwen2.5 7B/72B, Mistral) served via Together /
Fireworks / DeepInfra / Groq / OpenRouter — same API shape as tier 1, pointed at
open models. Roughly $0.10–0.90 per 1M tokens by model size, so ~0.01–0.08 cents
per generation (below Haiku). Groq and OpenRouter have free tiers usable at low
volume. No GPU to run; adds one external dependency. Quality is good but a notch
below frontier on reliably-formatted, well-crafted items — which matters more
here than for a typical text task because the items are the instrument.

### Tier 3 — self-hosted open-source (no API cost; needs compute)

Run an instruction-tuned model ourselves via `transformers`: Qwen2.5-7B-Instruct
(Apache 2.0), Llama-3.1-8B-Instruct, Mistral-7B-Instruct-v0.3, Gemma-2-9B-it, or
the smaller Phi-3.5-mini / Qwen2.5-3B for lighter hardware. Force valid JSON with
`outlines` or `lm-format-enforcer`. Zero per-call cost and no data leaves our
infra — but a 7–8B model wants a GPU; on our current CPU-only deployment (the
embedding models already run on CPU) generation would be slow (tens of seconds
to minutes per call) and memory-heavy. Only attractive if the lab already has a
GPU, or we accept slow CPU generation.

### Recommendation

Paid isn't strictly *necessary* — an open model can write items — but at ~900
tokens a call the frontier cost is a few dollars a year, and the items are the
measurement instrument, so the quality/reliability gain is worth it. Suggest
**Claude Haiku 4.5 or Sonnet 5 for v1** (cheap, strong, reliable structured
output). If the PI wants zero external API on principle, fall back to a Groq /
OpenRouter free tier (tier 2) or self-hosted Qwen2.5-7B if we have a GPU
(tier 3).

## Generation prompt — v1 draft

Structured output (Pydantic: `GeneratedItems{items: list[str], notes: str |
None}`), single synchronous call, no job queue. The prompt is model-agnostic —
see "Model options and cost" above. Whatever we pick, the call sits behind one
function, `generate_items(name, description, n, language) -> GeneratedItems`,
with the provider + model id read from env, so swapping models later is a config
change, not a code change.

### System prompt

```text
You are an expert psychometrician helping a researcher draft self-report
questionnaire items for a psychological construct. The items will be used with
Contextualized Construct Representation (CCR): each item is embedded with a
sentence-embedding model, and texts are scored by their semantic similarity to
the items. Item wording therefore matters as much as item content.

The researcher provides a construct name and an explanation of what it means.
Write the requested number of candidate items following ALL of these rules:

1. REGISTER. Each item is a short, first-person declarative statement in
   standard questionnaire style (like "I feel that my life is close to my
   ideal."), matching the register of validated self-report scales.
2. ONE IDEA PER ITEM. No double-barreled items (never join two claims with
   "and"/"or"), no conditionals, no questions.
3. POSITIVELY KEYED ONLY. Agreement with an item must always indicate MORE of
   the construct. Do not write reverse-scored items. Avoid negations
   ("I do not...", "I never...").
4. PLAIN LANGUAGE. Words a general adult population understands. Do not reuse
   academic or technical vocabulary from the researcher's explanation; express
   the same idea in everyday words.
5. COVERAGE AND VARIETY. Cover the distinct facets of the construct as
   described in the explanation. Vary sentence openings and vocabulary —
   items that are near-paraphrases of each other add no information in CCR.
6. LENGTH. Keep each item approximately between 5 and 25 words, unless the
   construct or the researcher's explanation requires otherwise. No proper
   nouns and no culturally narrow references unless the construct requires them.
7. SCOPE. Stay strictly within the construct as the researcher defined it.
   If the explanation is ambiguous, prefer the most standard interpretation
   in the psychology literature, and say so in the notes field.

If the input does not describe a psychological construct, or the explanation
is too vague to write faithful items, still do your best, and explain the
problem in the notes field so the researcher can refine their description.

Return output only through the structured output schema: "items" (the list of
item texts, nothing else — no numbering, no quotes) and "notes" (optional:
ambiguities, interpretation choices, or facets you could not cover).
```

### User message template

```text
Construct name: {name}
Explanation: {description}
Number of items: {n_items}
Language: {language}
```

Defaults: `n_items=10` (allowed 5–20), `language="English"` (from the
construct form's existing language field).

### Worked example

The fixed system prompt above is sent first, followed by this filled-in user
message:

```text
Construct name: Gratitude
Explanation: The tendency to notice and appreciate the positive things in one's
life, and to feel thankful for what one has and for what others do.
Number of items: 10
Language: English
```

Example structured response (`GeneratedItems`):

```json
{
  "items": [
    "I often pause to appreciate the good things in my life.",
    "I feel thankful for the people who support me.",
    "I notice small moments that make my day better.",
    "When something goes well, I take time to feel grateful.",
    "I appreciate what I have rather than focusing on what I lack.",
    "I often think about how fortunate I am.",
    "I feel a warm sense of thanks when others help me.",
    "I recognize the everyday things that make my life good.",
    "I remember to thank people who show me kindness.",
    "I am grateful for the opportunities I have been given."
  ],
  "notes": "All items are positively keyed and cover the main facets in the explanation: noticing good things, appreciating what one has, and feeling thankful toward others."
}
```

## Cautionary note — DRAFT wording for PI review

- **Badge** (picker, construct cards, results header):
  `AI-generated · not validated`
- **Generation panel** (shown before the user generates):
  > These items are drafted by an AI language model. They are a starting
  > point, not a validated questionnaire. Review every item, edit or remove
  > weak ones, and prefer a validated scale whenever one exists.
- **Results page** (when a run uses a generated construct):
  > This construct's items were AI-generated and have not been
  > psychometrically validated. Interpret scores with appropriate caution.
- **Exports / run metadata** (machine- and human-readable):
  > items_source: ai_generated (unvalidated). Drafted by {model} on {date},
  > reviewed and saved by the researcher. These items are not from a
  > validated questionnaire; interpret scores accordingly.

## Validation plan

Generate items for constructs with validated scales in the library (SWLS,
MFQ), score the same corpus with both item sets in one multi-construct run,
and report the correlation of per-text CCR scores. Target: strong convergence
(r ≳ .8) before recommending generated items for real analyses.
