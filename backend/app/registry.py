"""Model registry loader - the app-side reader of packages/model_registry/models.yaml.

Single source of model truth (design doc §13): the UI dropdown, backend validation,
prefix handling, language-support warnings, run metadata, and generated reproduction
scripts all read the SAME config through this module. No model behavior is hardcoded
anywhere else (CLAUDE.md hard rule).

Language sets are resolved through packages/model_registry/language_sets.py, loaded
by explicit file path (editable-install wiring arrives with Phase 1 packaging).
"""

from __future__ import annotations

import importlib.util
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
MODELS_YAML = Path(os.environ.get("CCR_MODELS_YAML", REPO_ROOT / "packages" / "model_registry" / "models.yaml"))
_LANGUAGE_SETS_PY = REPO_ROOT / "packages" / "model_registry" / "language_sets.py"


def _load_language_sets():
    spec = importlib.util.spec_from_file_location("ccr_language_sets", _LANGUAGE_SETS_PY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@dataclass(frozen=True)
class ModelConfig:
    id: str
    provider_model_id: str
    display_name: str
    revision: str
    default: bool
    supported_languages: frozenset[str]  # resolved ISO codes; frozenset() = unknown/any
    language_set_name: str | None
    embedding_dimension: int
    max_seq_length: int
    quality_tier: str
    speed_tier: str
    requires_prefix: bool
    item_prefix: str
    text_prefix: str
    normalize_embeddings: bool
    lazy_load: bool
    user_warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def pinned_revision(self) -> str | None:
        """Revision to pass to the model loader; None while unpinned (PIN_ME)."""
        return None if self.revision in ("PIN_ME", "", None) else self.revision

    def supports_language(self, iso_code: str) -> bool:
        if not self.supported_languages:  # unknown coverage - never block/warn on it
            return True
        return iso_code.lower() in self.supported_languages


def _parse_model(raw: dict, lang_sets) -> ModelConfig:
    usage = raw.get("usage_config", {})
    ops = raw.get("operational_config", {})
    set_name = raw.get("supported_language_set")
    if set_name:
        languages = frozenset(lang_sets.resolve(set_name))
    else:
        languages = frozenset(str(c).lower() for c in raw.get("supported_languages", []))

    sym = usage.get("symmetric_similarity_prefix") or ""
    return ModelConfig(
        id=raw["id"],
        provider_model_id=raw["provider_model_id"],
        display_name=raw.get("display_name", raw["id"]),
        revision=str(raw.get("revision", "PIN_ME")),
        default=bool(raw.get("default", False)),
        supported_languages=languages,
        language_set_name=set_name,
        embedding_dimension=int(raw["embedding_dimension"]),
        max_seq_length=int(raw["max_seq_length"]),
        quality_tier=str(raw.get("quality_tier", "unknown")),
        speed_tier=str(raw.get("speed_tier", "unknown")),
        requires_prefix=bool(usage.get("requires_prefix", False)),
        item_prefix=usage.get("construct_prefix") or sym or "",
        text_prefix=usage.get("text_prefix") or sym or "",
        normalize_embeddings=bool(usage.get("normalize_embeddings", True)),
        lazy_load=bool(ops.get("lazy_load", False)),
        user_warnings=tuple(raw.get("warnings", []) or []),
    )


@lru_cache(maxsize=1)
def _registry() -> dict[str, ModelConfig]:
    data = yaml.safe_load(MODELS_YAML.read_text())
    lang_sets = _load_language_sets()
    models = {}
    for raw in data.get("models", []):
        cfg = _parse_model(raw, lang_sets)
        if cfg.requires_prefix and not (cfg.item_prefix and cfg.text_prefix):
            raise ValueError(f"models.yaml: {cfg.id} requires_prefix but prefixes missing.")
        models[cfg.id] = cfg
    defaults = [m for m in models.values() if m.default]
    if len(defaults) != 1:
        raise ValueError(f"models.yaml must define exactly one default model, found {len(defaults)}.")
    return models


def reload() -> None:
    """Clear the cache (tests / config changes)."""
    _registry.cache_clear()


def list_models() -> list[ModelConfig]:
    ordered = sorted(_registry().values(), key=lambda m: (not m.default, m.id))
    return ordered


def get_model(model_id: str) -> ModelConfig:
    reg = _registry()
    if model_id not in reg:
        raise KeyError(f"Unknown model id '{model_id}'. Known: {sorted(reg)}")
    return reg[model_id]


def default_model() -> ModelConfig:
    return next(m for m in _registry().values() if m.default)


def known_ids() -> set[str]:
    return set(_registry().keys())
