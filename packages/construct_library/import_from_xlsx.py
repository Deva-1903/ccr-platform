#!/usr/bin/env python3
"""Import questionnaires from the lab's xlsx format into construct YAML files.

Usage: python packages/construct_library/import_from_xlsx.py <items.xlsx>

Expected workbook shape (as provided by the lab, July 2026):
  Items sheet:          construct, questionnaire, item_number, item_text,
                        subconstruct, APA_reference, source_url, rights_or_permission_note
  Questionnaires sheet: construct, questionnaire, expected_item_count,
                        included_item_count, APA_reference, source_url,
                        rights_or_permission_note, notes

Rules (recorded in DECISIONS.md):
  * Multi-dimensional questionnaires are split into one construct per dimension,
    because a CCR run scores ONE construct: a blended "Big Five" score would be
    meaningless. Dimension = normalized subconstruct label.
  * A trailing "(R)" in a subconstruct label marks a reverse-scored item; the
    marker is stripped from the dimension name and stored as the item's flag.
    Where the source encodes no markers, flags default to false and the YAML
    records reverse_flags_source: not_provided (pending verification).
  * Rows whose subconstruct is "Filler" are excluded (unscored by design).
  * Everything imports as verification_status: needs_verification - wording
    must still be checked verbatim against the original publications.
  * Existing seed constructs are never overwritten; questionnaires that
    duplicate a seed scale are skipped and reported.
"""

from __future__ import annotations

import re
import sys
import unicodedata
from pathlib import Path

import pandas as pd
import yaml

CONSTRUCTS_DIR = Path(__file__).parent / "constructs"
REVERSE_MARKER = re.compile(r"\s*\((r|rev|reversed)\)\s*$", re.IGNORECASE)
FILLER_LABELS = {"filler"}
# Questionnaires that duplicate an existing seed construct (kept as seeds).
SKIP_DUPLICATE_OF_SEED = {"Satisfaction With Life Scale (SWLS)": "satisfaction_with_life"}


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "_", text).strip("_").lower()
    return re.sub(r"_+", "_", text)[:80]


def short_name(questionnaire: str) -> str:
    """Prefer the parenthesized abbreviation: 'Ten-Item Personality Inventory (TIPI)' -> 'TIPI'."""
    m = re.search(r"\(([^)]{2,20})\)\s*$", questionnaire)
    return m.group(1) if m else questionnaire


def main(xlsx_path: str) -> int:
    items = pd.read_excel(xlsx_path, sheet_name="Items")
    meta = pd.read_excel(xlsx_path, sheet_name="Questionnaires").set_index("questionnaire")

    report = {"written": 0, "dims": 0, "reversed_items": 0, "filler_dropped": 0,
              "skipped": [], "warnings": []}

    for questionnaire, group in items.groupby("questionnaire", sort=True):
        if questionnaire in SKIP_DUPLICATE_OF_SEED:
            report["skipped"].append(f"{questionnaire} (duplicate of seed "
                                     f"'{SKIP_DUPLICATE_OF_SEED[questionnaire]}')")
            continue

        group = group.sort_values("item_number")
        construct_family = str(group["construct"].iloc[0])
        m = meta.loc[questionnaire] if questionnaire in meta.index else None
        if m is None:
            report["warnings"].append(
                f"'{questionnaire}': no row in Questionnaires sheet (name mismatch?); "
                "using item-level citation metadata."
            )
        citation = str((m["APA_reference"] if m is not None else group["APA_reference"].iloc[0]) or "")
        source_url = str((m["source_url"] if m is not None else group["source_url"].iloc[0]) or "")
        rights = str((m["rights_or_permission_note"] if m is not None
                      else group["rights_or_permission_note"].iloc[0]) or "")
        if m is not None and int(m["included_item_count"]) != len(group):
            report["warnings"].append(
                f"'{questionnaire}': Questionnaires sheet says {m['included_item_count']} "
                f"items, Items sheet has {len(group)}."
            )

        # Normalize dimensions + reverse flags; drop filler rows.
        rows = []
        any_marker = False
        for _, r in group.iterrows():
            raw_sub = "" if pd.isna(r["subconstruct"]) else str(r["subconstruct"]).strip()
            reverse = bool(REVERSE_MARKER.search(raw_sub))
            any_marker = any_marker or reverse
            dim = REVERSE_MARKER.sub("", raw_sub).strip()
            if dim.lower() in FILLER_LABELS:
                report["filler_dropped"] += 1
                continue
            rows.append({"dim": dim, "text": str(r["item_text"]).strip(),
                         "reverse": reverse, "n": int(r["item_number"])})
        if not rows:
            report["skipped"].append(f"{questionnaire} (no scored items)")
            continue

        dims = sorted({r["dim"] for r in rows if r["dim"]})
        split = len(dims) > 1
        buckets = {d: [r for r in rows if r["dim"] == d] for d in dims} if split \
            else {None: rows}

        abbrev = short_name(questionnaire)
        for dim, bucket in buckets.items():
            name = f"{dim} ({abbrev})" if dim else questionnaire
            slug = slugify(f"{abbrev}_{dim}" if dim else abbrev)
            n_rev = sum(r["reverse"] for r in bucket)
            report["reversed_items"] += n_rev

            doc = {
                "construct_id": slug,
                "version": 1,
                "name": name,
                "language": "en",
                "category": construct_family,
                "description": (f"{construct_family}"
                                + (f" - {dim} dimension of the {questionnaire}." if dim
                                   else f" - {questionnaire}.")
                                + (" Screening tool only; not a diagnosis."
                                   if "not a diagnosis" in rights.lower() else "")),
                "citation": citation,
                "verification_status": "needs_verification",
                "source_url": source_url,
                "rights_note": rights,
                "questionnaire": questionnaire,
                "reverse_flags_source": ("subconstruct_markers" if any_marker
                                         else "not_provided_pending_verification"),
                "imported_from": Path(xlsx_path).name,
                "items": [
                    {"item_id": f"{slug}_{r['n']}", "text": r["text"],
                     "reverse_scored": bool(r["reverse"])}
                    for r in bucket
                ],
            }
            out = CONSTRUCTS_DIR / f"{slug}.yaml"
            if out.exists():
                report["warnings"].append(f"SKIPPED existing file: {out.name}")
                continue
            out.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=100))
            report["written"] += 1
            report["dims"] += 1 if dim else 0

    print(f"written: {report['written']} construct files "
          f"({report['dims']} from dimensional splits)")
    print(f"reverse-scored items flagged from source markers: {report['reversed_items']}")
    print(f"filler items excluded: {report['filler_dropped']}")
    for s in report["skipped"]:
        print(f"  SKIP: {s}")
    for w in report["warnings"]:
        print(f"  WARN: {w}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    raise SystemExit(main(sys.argv[1]))
