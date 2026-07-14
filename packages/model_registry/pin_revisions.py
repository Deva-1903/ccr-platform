#!/usr/bin/env python3
"""Pin every registry model to the current HF commit SHA (Phase 1 exit criterion).

Usage (needs internet):
    python packages/model_registry/pin_revisions.py          # dry run: show SHAs
    python packages/model_registry/pin_revisions.py --write  # update models.yaml

Reproducibility depends on this: an unpinned model silently changes when the
provider pushes a new revision, which would change scores between runs.
Re-running with --write later REPINS to newer revisions - only do that as a
deliberate, logged decision (scores may shift; see design doc Section 6).
"""

import json
import re
import sys
import urllib.request
from pathlib import Path

MODELS_YAML = Path(__file__).parent / "models.yaml"


def current_sha(provider_id: str) -> str:
    with urllib.request.urlopen(
        f"https://huggingface.co/api/models/{provider_id}", timeout=30
    ) as resp:
        return json.load(resp)["sha"]


def main() -> None:
    write = "--write" in sys.argv
    text = MODELS_YAML.read_text()
    providers = re.findall(r"provider_model_id:\s*(\S+)", text)

    for provider in providers:
        sha = current_sha(provider)
        print(f"{provider}: {sha}")
        if write:
            # replace the revision line that follows this provider line
            pattern = re.compile(
                rf"(provider_model_id:\s*{re.escape(provider)}\s*\n(?:.*\n)*?\s*revision:\s*)(\S+)"
            )
            text, n = pattern.subn(rf"\g<1>{sha}", text, count=1)
            assert n == 1, f"could not locate revision line for {provider}"

    if write:
        MODELS_YAML.write_text(text)
        print("\nmodels.yaml updated. Now run the validator and the test suite:")
        print("  python packages/model_registry/validate_models.py")
        print("  cd backend && CCR_FAKE_EMBEDDINGS=1 python -m pytest -q")
    else:
        print("\nDry run. Re-run with --write to update models.yaml.")


if __name__ == "__main__":
    main()
