"""One live end-to-end check of LLM item generation (ITEM_GENERATION.md).

Calls the real provider (whichever key is configured - Groq or Anthropic),
prints the drafted items, and exits non-zero on failure. Run it once after
setting a key, and again after any provider/model/prompt change:

    cd backend && ../scripts/smoke_test_generation.sh   # or:
    cd backend && GROQ_API_KEY=... .venv/bin/python ../scripts/smoke_test_generation.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app import item_generation  # noqa: E402


def main() -> int:
    p = item_generation.provider()
    if not p:
        print("FAIL: no GROQ_API_KEY or ANTHROPIC_API_KEY set.")
        return 1
    print(f"provider={p} model={item_generation.generation_model()} "
          f"prompt_version={item_generation.PROMPT_VERSION}")
    try:
        draft = item_generation.generate_items(
            name="Gratitude",
            description=(
                "The tendency to notice and appreciate the positive things in "
                "one's life, and to feel thankful for what one has and for "
                "what others do."
            ),
            n_items=10,
        )
    except item_generation.GenerationError as exc:
        print(f"FAIL ({exc.status_code}): {exc}")
        return 1
    print(f"\n{len(draft.items)} items:")
    for i, item in enumerate(draft.items, 1):
        print(f"  {i:2}. {item}")
    if draft.notes:
        print(f"\nnotes: {draft.notes}")
    # Cheap rule checks (the human review still judges quality):
    problems = []
    for item in draft.items:
        if not item.lower().startswith(("i ", "i'", "my ", "when ")):
            problems.append(f"not first-person? {item!r}")
        if "?" in item:
            problems.append(f"question: {item!r}")
    if problems:
        print("\nrule warnings (review, not necessarily failures):")
        for w in problems:
            print(f"  - {w}")
    print("\nOK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
