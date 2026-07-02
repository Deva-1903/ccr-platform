"""Corpus ingestion — tolerant of real-world research files.

Researchers upload CSVs exported from Qualtrics, Excel, R, SPSS, and
scrapers: BOMs, latin-1 encodings, semicolon/tab delimiters, ragged rows.
The loader tries the common cases in order and records exactly how the
file was parsed, so every downstream result is traceable to a specific
parse configuration.
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

# Encodings tried in order. utf-8-sig transparently strips a BOM and reads
# plain UTF-8; latin-1 never fails (maps all 256 bytes), so it is the
# last-resort fallback and is recorded as such.
_ENCODINGS = ("utf-8-sig", "latin-1")


def max_rows() -> int:
    """Row ceiling, env-configurable (CCR_MAX_ROWS). Protects a shared
    demo instance from unbounded jobs; raise deliberately for real use."""
    return int(os.environ.get("CCR_MAX_ROWS", 100_000))


class IngestError(ValueError):
    """Raised with a user-facing message when a file cannot be ingested."""


def load_corpus(path: str | Path) -> tuple[pd.DataFrame, dict]:
    """Parse CSV/XLSX into a DataFrame.

    Returns (df, parse_info) where parse_info records the format,
    encoding, and delimiter actually used — stored with the corpus and
    echoed into every run's reproducibility metadata.
    """
    p = Path(path)

    if p.suffix.lower() in (".xlsx", ".xls"):
        try:
            df = pd.read_excel(p)
        except Exception as exc:
            raise IngestError(f"Could not read Excel file: {exc}") from exc
        return _validate(df), {"format": "excel"}

    last_error: Exception | None = None
    for encoding in _ENCODINGS:
        # First attempt: delimiter sniffing (handles ',', ';', '\t', '|').
        # The python engine is slower but supports sniffing + bad-line skips;
        # fine at lab scale. Falls back to plain comma parsing for files the
        # sniffer chokes on (e.g., single-column CSVs).
        for sep, sep_label in ((None, "sniffed"), (",", ",")):
            try:
                df = pd.read_csv(
                    p,
                    encoding=encoding,
                    sep=sep,
                    engine="python",
                    on_bad_lines="skip",
                )
                info = {
                    "format": "csv",
                    "encoding": encoding,
                    "delimiter": _describe_sep(df, sep_label),
                }
                if encoding == "latin-1":
                    info["note"] = (
                        "File was not valid UTF-8; decoded as latin-1. "
                        "Verify non-ASCII characters rendered correctly."
                    )
                return _validate(df), info
            except IngestError:
                raise
            except Exception as exc:  # try next (sep, encoding) combination
                last_error = exc

    raise IngestError(f"Could not parse CSV file: {last_error}")


def _describe_sep(df: pd.DataFrame, sep_label: str) -> str:
    return sep_label


def _validate(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or len(df.columns) == 0:
        raise IngestError("The file parsed but contains no data rows.")
    if len(df) > max_rows():
        raise IngestError(
            f"File has {len(df):,} rows — above this instance's "
            f"{max_rows():,}-row limit. Split the corpus or run locally."
        )
    df.columns = [str(c) for c in df.columns]
    return df


def suggest_text_column(df: pd.DataFrame) -> str | None:
    """Best-guess text column: prefer a column literally named 'text',
    otherwise the string column with the longest average length (sampled)."""
    lowered = {c.lower(): c for c in df.columns}
    if "text" in lowered:
        return lowered["text"]

    best, best_len = None, 0.0
    sample = df.head(200)
    for col in df.columns:
        values = sample[col].dropna()
        if values.empty:
            continue
        as_str = values.astype(str)
        # Skip columns that are clearly numeric/IDs.
        if pd.to_numeric(values, errors="coerce").notna().mean() > 0.9:
            continue
        avg_len = float(as_str.str.len().mean())
        if avg_len > best_len:
            best, best_len = col, avg_len
    return best
