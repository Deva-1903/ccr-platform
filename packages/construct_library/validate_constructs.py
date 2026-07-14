#!/usr/bin/env python3
"""Validate construct YAML files and print each construct's item hash.

Run: python packages/construct_library/validate_constructs.py
The item hash (sha256 of normalized item text + order + flags + language + version)
is the construct's identity in run metadata - this validator is the reference
implementation of that hash (design doc §10.1).
"""

import hashlib
import sys
from pathlib import Path

import yaml

REQUIRED = {"construct_id", "version", "name", "language", "citation", "verification_status", "items"}
VALID_STATUS = {"draft", "needs_verification", "verified", "archived"}


def item_hash(construct: dict) -> str:
    parts = [str(construct["language"]), str(construct["version"])]
    for i, item in enumerate(construct["items"]):
        parts.append(f"{i}|{' '.join(str(item['text']).split())}|{bool(item.get('reverse_scored', False))}")
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()


def main() -> int:
    constructs_dir = Path(__file__).parent / "constructs"
    files = sorted(constructs_dir.glob("*.yaml"))
    errors: list[str] = []
    seen: dict[tuple, Path] = {}

    if not files:
        errors.append("No construct files found.")

    for f in files:
        c = yaml.safe_load(f.read_text())
        name = f.name
        missing = REQUIRED - c.keys()
        if missing:
            errors.append(f"{name}: missing fields {sorted(missing)}")
            continue
        if c["verification_status"] not in VALID_STATUS:
            errors.append(f"{name}: invalid verification_status '{c['verification_status']}'")
        if not c["items"]:
            errors.append(f"{name}: no items")
            continue
        for i, item in enumerate(c["items"]):
            if not str(item.get("text", "")).strip():
                errors.append(f"{name}: item {i} has empty text")
            if "reverse_scored" not in item:
                errors.append(f"{name}: item {i} missing explicit reverse_scored flag")
        texts = [" ".join(str(i["text"]).split()).lower() for i in c["items"]]
        if len(texts) != len(set(texts)):
            errors.append(f"{name}: duplicate item texts")
        key = (c["construct_id"], c["version"])
        if key in seen:
            errors.append(f"{name}: duplicate (construct_id, version) with {seen[key].name} - versions are append-only")
        seen[key] = f

        if all(i.get("reverse_scored") for i in c["items"]):
            print(f"  WARN {name}: ALL items reverse-scored - aggregate will be blocked under exclude_reversed.")

        if not errors or all(name not in e for e in errors):
            print(f"  OK   {name}  v{c['version']}  items={len(c['items'])}  hash={item_hash(c)[:16]}  [{c['verification_status']}]")

    if errors:
        print("CONSTRUCT LIBRARY INVALID:")
        for e in errors:
            print(f"  ERROR: {e}")
        return 1
    print(f"construct library OK - {len(files)} construct(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
