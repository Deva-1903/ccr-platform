"""Parse a construct's items from an uploaded CSV/XLSX file.

Design (Deva, 2026-07-11): parse -> preview -> confirm. The file is parsed
into items + reverse flags and returned for the researcher to REVIEW AND EDIT
before saving - never silently imported, because in CCR the item wording IS
the instrument.

Accepted shapes (tolerant, reusing the corpus ingest loaders):
  * an "item" / "items" / "text" / "statement" / "question" column (case-
    insensitive), else a single-column file, else the longest-string column;
  * optional reverse-scoring either as a column ("reverse", "reversed",
    "reverse_scored", "rev", "r"; truthy = 1/true/yes/y/r) or as a trailing
    "(R)" / "(rev)" / "(reversed)" marker in the item text (the lab's own
    spreadsheet convention - packages/construct_library/import_from_xlsx.py);
  * blank rows dropped, exact duplicates dropped with a warning.
"""

from __future__ import annotations

import re

import pandas as pd

from .ingest import IngestError, load_corpus

ITEM_COLUMNS = ("item", "items", "text", "statement", "question", "item_text")
REVERSE_COLUMNS = ("reverse", "reversed", "reverse_scored", "reverse-scored", "rev", "r")
TRUTHY = {"1", "true", "yes", "y", "r", "reverse", "reversed"}
REVERSE_MARKER = re.compile(r"\s*\((r|rev|reversed)\)\s*$", re.IGNORECASE)
MAX_ITEMS = 200


def parse_construct_file(path: str) -> dict:
    """Return {items: [{text, reverse_scored}], warnings: [str], source_column: str}."""
    try:
        df, _info = load_corpus(path)
    except IngestError as exc:
        raise ValueError(str(exc)) from exc
    if df.empty:
        raise ValueError("The file contains no rows.")

    lower = {str(c).strip().lower(): c for c in df.columns}

    item_col = next((lower[c] for c in ITEM_COLUMNS if c in lower), None)
    if item_col is None:
        if len(df.columns) == 1:
            item_col = df.columns[0]
        else:  # longest average string wins - same heuristic family as corpora
            def avg_len(col):
                s = df[col].astype("string").dropna()
                return s.str.len().mean() if len(s) else 0
            item_col = max(df.columns, key=avg_len)

    reverse_col = next((lower[c] for c in REVERSE_COLUMNS if c in lower), None)
    if reverse_col == item_col:
        reverse_col = None

    warnings: list[str] = []
    items: list[dict] = []
    seen: set[str] = set()
    n_blank = n_dupes = 0

    for _, row in df.iterrows():
        raw = row[item_col]
        text = "" if pd.isna(raw) else str(raw).strip()
        if not text:
            n_blank += 1
            continue

        reverse = False
        if reverse_col is not None:
            flag = row[reverse_col]
            if not pd.isna(flag):
                s = str(flag).strip().lower()
                try:  # pandas floats an int column containing blanks: 1 -> "1.0"
                    reverse = float(s) != 0
                except ValueError:
                    reverse = s in TRUTHY
        if REVERSE_MARKER.search(text):
            reverse = True
            text = REVERSE_MARKER.sub("", text).strip()

        if text in seen:
            n_dupes += 1
            continue
        seen.add(text)
        items.append({"text": text, "reverse_scored": reverse})

    if not items:
        raise ValueError(f"No usable items found in column '{item_col}'.")
    if len(items) > MAX_ITEMS:
        raise ValueError(
            f"{len(items)} items found; a construct is capped at {MAX_ITEMS}. "
            "If this file holds multiple scales, split it per construct."
        )

    if n_blank:
        warnings.append(f"{n_blank} blank row(s) skipped.")
    if n_dupes:
        warnings.append(f"{n_dupes} duplicate item(s) skipped.")
    if reverse_col is None and not any(i["reverse_scored"] for i in items):
        warnings.append(
            "No reverse-scoring information found. Mark reverse-scored items by "
            "appending (R) to the item text, or include a 'reverse' column."
        )
    warnings.append(
        "Review each item against the original publication before research use - "
        "the item wording IS the instrument."
    )
    return {"items": items, "warnings": warnings, "source_column": str(item_col)}
