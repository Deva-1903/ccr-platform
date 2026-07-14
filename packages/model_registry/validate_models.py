#!/usr/bin/env python3
"""Validate models.yaml against the registry contract (design doc §13).

Run: python packages/model_registry/validate_models.py
Exit 0 = valid; exit 1 = violations printed.
"""

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
from language_sets import LANGUAGE_SETS  # noqa: E402

REQUIRED_FIELDS = {
    "id", "provider_model_id", "display_name", "revision",
    "embedding_dimension", "max_seq_length", "quality_tier", "speed_tier",
    "usage_config", "operational_config",
}
REQUIRED_USAGE = {"requires_prefix", "normalize_embeddings", "pooling"}


def main() -> int:
    path = Path(__file__).parent / "models.yaml"
    data = yaml.safe_load(path.read_text())
    models = data.get("models", [])
    errors: list[str] = []

    if not models:
        errors.append("models.yaml contains no models.")

    ids = [m.get("id") for m in models]
    if len(ids) != len(set(ids)):
        errors.append(f"Duplicate model ids: {ids}")

    defaults = [m["id"] for m in models if m.get("default")]
    if len(defaults) != 1:
        errors.append(f"Exactly one model must have default: true (found: {defaults}).")

    for m in models:
        mid = m.get("id", "<missing id>")
        missing = REQUIRED_FIELDS - m.keys()
        if missing:
            errors.append(f"{mid}: missing fields {sorted(missing)}")
            continue

        # Language support must be machine-checkable.
        has_list = isinstance(m.get("supported_languages"), list) and m["supported_languages"]
        set_name = m.get("supported_language_set")
        if not has_list and not set_name:
            errors.append(f"{mid}: needs supported_languages list OR supported_language_set.")
        if has_list and "multilingual" in [str(x).lower() for x in m["supported_languages"]]:
            errors.append(f"{mid}: bare 'multilingual' label is banned - use supported_language_set.")
        if set_name and set_name not in LANGUAGE_SETS:
            errors.append(f"{mid}: unknown language set '{set_name}' (add to language_sets.py).")

        usage = m["usage_config"]
        missing_u = REQUIRED_USAGE - usage.keys()
        if missing_u:
            errors.append(f"{mid}: usage_config missing {sorted(missing_u)}")
        if usage.get("requires_prefix"):
            if not (usage.get("symmetric_similarity_prefix") or (usage.get("construct_prefix") and usage.get("text_prefix"))):
                errors.append(f"{mid}: requires_prefix=true but no prefix strings defined.")

        if m.get("revision") == "PIN_ME":
            print(f"  WARN {mid}: revision not pinned yet (required before Phase 1 exit).")

    if errors:
        print("MODEL REGISTRY INVALID:")
        for e in errors:
            print(f"  ERROR: {e}")
        return 1
    print(f"models.yaml OK - {len(models)} model(s), default: {defaults[0]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
