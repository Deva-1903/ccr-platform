"""Construct library loader - seeds the DB from packages/construct_library/constructs/.

Source of truth is the versioned YAML files (spec 0004, design doc §10.1). Rules:
  * append-only: (construct_id, version) is immutable - same version with changed
    items is a hard error, never a silent update;
  * item_hash uses the REFERENCE implementation from validate_constructs.py (loaded
    by file path) so validator, seeder, and metadata always agree;
  * verification_status flows to the UI - unverified wording is visibly flagged.

New questionnaires from the lab land as new YAML files; `python packages/construct_library/
validate_constructs.py` first, then restart the app (or call sync) to pick them up.
"""

from __future__ import annotations

import importlib.util
import json
import logging
from pathlib import Path

import yaml
from sqlalchemy.orm import Session

from .models import Construct

logger = logging.getLogger("ccr.constructs")

REPO_ROOT = Path(__file__).resolve().parents[2]
CONSTRUCTS_DIR = REPO_ROOT / "packages" / "construct_library" / "constructs"
_VALIDATOR_PY = REPO_ROOT / "packages" / "construct_library" / "validate_constructs.py"


def _reference_item_hash():
    spec = importlib.util.spec_from_file_location("ccr_construct_validator", _VALIDATOR_PY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.item_hash


def load_yaml_constructs() -> list[dict]:
    files = sorted(CONSTRUCTS_DIR.glob("*.yaml"))
    out = []
    for f in files:
        data = yaml.safe_load(f.read_text())
        data["_file"] = f.name
        out.append(data)
    return out


def sync_library(db: Session) -> dict:
    """Idempotent seed/update of library constructs. Returns a small report."""
    item_hash = _reference_item_hash()
    report = {"inserted": 0, "unchanged": 0, "errors": []}

    for c in load_yaml_constructs():
        slug, version = c["construct_id"], int(c["version"])
        computed_hash = item_hash(c)

        existing = (
            db.query(Construct)
            .filter_by(construct_slug=slug, version=version, is_seed=True)
            .one_or_none()
        )
        if existing:
            if existing.item_hash != computed_hash:
                # Append-only violation: same version, different wording. Refuse loudly.
                report["errors"].append(
                    f"{c['_file']}: items changed under existing version {version} "
                    f"(hash {existing.item_hash[:12]} -> {computed_hash[:12]}). "
                    "Create a NEW version instead of editing this one."
                )
            else:
                report["unchanged"] += 1
            continue

        db.add(
            Construct(
                name=c["name"],
                description=c.get("description", ""),
                reference=c.get("citation", ""),
                items_json=json.dumps([str(i["text"]) for i in c["items"]]),
                reverse_flags_json=json.dumps([bool(i.get("reverse_scored", False)) for i in c["items"]]),
                is_seed=True,
                construct_slug=slug,
                version=version,
                item_hash=computed_hash,
                verification_status=c.get("verification_status", "needs_verification"),
                language=c.get("language", "en"),
                category=c.get("category", ""),
            )
        )
        report["inserted"] += 1

    db.commit()
    if report["errors"]:
        for e in report["errors"]:
            logger.error("construct library: %s", e)
        raise RuntimeError(
            "Construct library append-only violation(s): " + " | ".join(report["errors"])
        )
    logger.info("construct library sync: %s", report)
    return report


def construct_snapshot(construct: Construct) -> dict:
    """Immutable snapshot embedded in every run's metadata (design §10.1)."""
    items = json.loads(construct.items_json)
    flags = json.loads(construct.reverse_flags_json or "[]") or [False] * len(items)
    return {
        "construct_id": construct.construct_slug or f"custom_{construct.id[:8]}",
        "version": construct.version or 1,
        "name": construct.name,
        "language": construct.language or "en",
        "items": [
            {"text": t, "reverse_scored": bool(f)} for t, f in zip(items, flags)
        ],
        "item_hash": construct.item_hash or "",
        "citation": construct.reference or "",
        "verification_status": construct.verification_status or "draft",
        "source_type": "predefined" if construct.is_seed else "user_custom",
    }
