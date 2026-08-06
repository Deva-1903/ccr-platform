"""LLM-generated construct items (design note: ITEM_GENERATION.md).

Drafts questionnaire-style items for a construct from its name + explanation,
for use as CCR item sets when no validated scale exists. PI decisions
(2026-08-05): positively-keyed items only, signed-in users only, cautionary
labeling everywhere the construct appears.

Two providers behind one generate_items() function:
  * anthropic - Claude Haiku (the PI-decided target once billing lands),
  * groq      - free-tier open models (Llama), the interim/testing provider.
Selection: CCR_GENERATION_PROVIDER, else inferred from which API key is set
(ANTHROPIC_API_KEY wins over GROQ_API_KEY). The provenance stamp records the
actual model, so constructs drafted during the Groq period stay traceable.

Nothing here is persisted - the endpoint returns a PREVIEW; the researcher
reviews/edits and saves through the normal POST /api/constructs path.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone

from pydantic import BaseModel, Field, ValidationError

# Bump whenever SYSTEM_PROMPT changes: recorded on every saved construct so a
# run's provenance names the exact instructions that drafted its items.
PROMPT_VERSION = "1"

ANTHROPIC_MODEL_DEFAULT = "claude-haiku-4-5"  # PI decision 2026-08-05
GROQ_MODEL_DEFAULT = "llama-3.3-70b-versatile"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
USER_MAX_GENERATIONS_PER_DAY_DEFAULT = 20
N_ITEMS_MIN, N_ITEMS_MAX, N_ITEMS_DEFAULT = 5, 20, 10

# Wording approved by the PI (2026-08-05); rule 6 carries his final edit
# ("approximately between 5 and 25 words, unless ... requires otherwise").
SYSTEM_PROMPT = """You are an expert psychometrician helping a researcher draft self-report
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
   described in the explanation. Vary sentence openings and vocabulary -
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
item texts, nothing else - no numbering, no quotes) and "notes" (optional:
ambiguities, interpretation choices, or facets you could not cover)."""


class GeneratedItems(BaseModel):
    """Structured output schema the model must fill."""

    items: list[str] = Field(min_length=1)
    notes: str | None = None


class GenerationError(Exception):
    """User-presentable generation failure (message is safe to show)."""

    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


def provider() -> str | None:
    """Active provider: explicit CCR_GENERATION_PROVIDER, else inferred from
    which key is set (anthropic preferred - it's the decided target)."""
    explicit = os.environ.get("CCR_GENERATION_PROVIDER", "").strip().lower()
    if explicit in ("anthropic", "groq"):
        return explicit
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.environ.get("GROQ_API_KEY"):
        return "groq"
    return None


def configured() -> bool:
    p = provider()
    if p == "anthropic":
        return bool(os.environ.get("ANTHROPIC_API_KEY"))
    if p == "groq":
        return bool(os.environ.get("GROQ_API_KEY"))
    return False


def generation_model() -> str:
    override = os.environ.get("CCR_GENERATION_MODEL")
    if override:
        return override
    return GROQ_MODEL_DEFAULT if provider() == "groq" else ANTHROPIC_MODEL_DEFAULT


def user_max_generations_per_day() -> int:
    return int(
        os.environ.get(
            "CCR_USER_MAX_GENERATIONS_PER_DAY", USER_MAX_GENERATIONS_PER_DAY_DEFAULT
        )
    )


def _user_message(name: str, description: str, n_items: int, language: str) -> str:
    return (
        f"Construct name: {name}\n"
        f"Explanation: {description}\n"
        f"Number of items: {n_items}\n"
        f"Language: {language}"
    )


def generate_items(
    name: str, description: str, n_items: int = N_ITEMS_DEFAULT, language: str = "English"
) -> GeneratedItems:
    """One synchronous structured-output call; raises GenerationError with a
    user-presentable message on any failure."""
    if not configured():
        raise GenerationError(
            "Item generation is not configured on this instance "
            "(no generation API key set).",
            status_code=503,
        )
    user_message = _user_message(name, description, n_items, language)
    if provider() == "groq":
        return _generate_groq(user_message)
    return _generate_anthropic(user_message)


def _generate_anthropic(user_message: str) -> GeneratedItems:
    import anthropic  # deferred: keeps app import light and tests patchable

    client = anthropic.Anthropic()
    try:
        response = client.messages.parse(
            model=generation_model(),
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
            output_format=GeneratedItems,
        )
    except anthropic.AuthenticationError as exc:
        raise GenerationError(
            "The generation service rejected this instance's API key. "
            "Ask an admin to check the configuration.",
            status_code=502,
        ) from exc
    except anthropic.RateLimitError as exc:
        raise GenerationError(
            "The generation service is rate-limited right now. "
            "Wait a minute and try again.",
            status_code=503,
        ) from exc
    except anthropic.APIStatusError as exc:
        raise GenerationError(
            "The generation service returned an error. Try again shortly.",
            status_code=502,
        ) from exc
    except anthropic.APIConnectionError as exc:
        raise GenerationError(
            "Could not reach the generation service. Try again shortly.",
            status_code=502,
        ) from exc

    parsed = response.parsed_output
    if parsed is None:
        raise GenerationError(
            "The model returned an unusable draft. Try again, or refine the "
            "construct description.",
            status_code=502,
        )
    return _clean(parsed)


# Groq (OpenAI-compatible) via stdlib urllib, matching auth_google.py's
# zero-dependency convention. JSON mode + Pydantic validation stands in for
# Anthropic's structured outputs; open models fail format more often, hence
# the explicit schema addendum and the validation error path.
_GROQ_JSON_ADDENDUM = (
    '\n\nRespond with a single JSON object exactly of the form '
    '{"items": ["...", "..."], "notes": "..."} - "items" is the list of item '
    'texts and "notes" is a string or null. No other keys, no markdown.'
)


def _generate_groq(user_message: str) -> GeneratedItems:
    payload = {
        "model": generation_model(),
        "max_tokens": 2048,
        "temperature": 0.7,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT + _GROQ_JSON_ADDENDUM},
            {"role": "user", "content": user_message},
        ],
    }
    req = urllib.request.Request(
        GROQ_URL,
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {os.environ['GROQ_API_KEY']}",
            # Cloudflare in front of Groq blocks urllib's default UA (403 code
            # 1010); any explicit product UA passes.
            "User-Agent": "ccr-platform/0.1",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            body = json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise GenerationError(
                "The generation service rejected this instance's API key. "
                "Ask an admin to check the configuration.",
                status_code=502,
            ) from exc
        if exc.code == 429:
            raise GenerationError(
                "The generation service is rate-limited right now (free tier). "
                "Wait a minute and try again.",
                status_code=503,
            ) from exc
        raise GenerationError(
            "The generation service returned an error. Try again shortly.",
            status_code=502,
        ) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise GenerationError(
            "Could not reach the generation service. Try again shortly.",
            status_code=502,
        ) from exc

    try:
        content = body["choices"][0]["message"]["content"]
        parsed = GeneratedItems.model_validate_json(content)
    except (KeyError, IndexError, TypeError, ValidationError) as exc:
        raise GenerationError(
            "The model returned an unusable draft. Try again, or refine the "
            "construct description.",
            status_code=502,
        ) from exc
    return _clean(parsed)


def _clean(parsed: GeneratedItems) -> GeneratedItems:
    # Belt-and-suspenders cleanup: drop empties/duplicates, bound the count.
    seen: set[str] = set()
    items: list[str] = []
    for raw in parsed.items:
        text = " ".join(str(raw).split()).strip()
        if text and text.lower() not in seen:
            seen.add(text.lower())
            items.append(text)
    if not items:
        raise GenerationError(
            "The model returned no usable items. Try again, or refine the "
            "construct description.",
            status_code=502,
        )
    notes = (parsed.notes or "").strip() or None
    return GeneratedItems(items=items[:N_ITEMS_MAX], notes=notes)


def generation_stamp() -> dict:
    """Provenance recorded on constructs saved from a generated draft."""
    return {
        "model": generation_model(),
        "prompt_version": PROMPT_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
