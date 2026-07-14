"""Structured data-quality warnings (spec 0001, design doc §12).

Every warning is an object - {code, severity, message, count?, affected_rows_sample?} -
never a bare string. Codes are UPPER_SNAKE and stable: downstream notebooks and the UI
key off them. Severity: "info" (status, not a problem) | "warning" (proceed with care).
Language detection is corpus-level only; short texts are exactly where detection is
unreliable, so uncertainty is reported instead of guessed away.

Deviation from spec 0001 (recorded there): langdetect instead of lingua - pure-Python,
~1 MB vs ~100 MB wheels; seeded for determinism. Upgrade path preserved by recording
detector + version in metadata.
"""

from __future__ import annotations

from dataclasses import dataclass

MIN_TOKENS_STABLE = 4          # texts below this are flagged TEXT_TOO_SHORT
DETECT_MIN_TOKENS = 5          # rows shorter than this are skipped for detection
DETECT_SAMPLE_MAX = 200        # rows sampled for corpus-level detection
DETECT_MIN_ROWS = 20           # fewer detectable rows -> LANGUAGE_UNCERTAIN
DETECT_CONFIDENCE = 0.70       # majority share below this -> LANGUAGE_UNCERTAIN
SAMPLE_ROWS_SHOWN = 5


def warning(code: str, severity: str, message: str, **extra) -> dict:
    return {"code": code, "severity": severity, "message": message, **extra}


# ---------------------------------------------------------------- text QA
def short_text_warning(texts: list[str]) -> dict | None:
    idx = [i for i, t in enumerate(texts) if len(t.split()) < MIN_TOKENS_STABLE]
    if not idx:
        return None
    return warning(
        "TEXT_TOO_SHORT",
        "warning",
        f"{len(idx)} text(s) contain fewer than {MIN_TOKENS_STABLE} words; "
        "CCR scores may be unstable for very short texts.",
        count=len(idx),
        affected_rows_sample=idx[:SAMPLE_ROWS_SHOWN],
    )


# ---------------------------------------------------------- language checks
@dataclass
class LanguageResult:
    selected: str
    detected: str | None
    confidence: float | None
    n_rows_sampled: int
    detector: str
    detector_version: str

    def as_metadata(self) -> dict:
        return {
            "selected": self.selected,
            "detected": self.detected,
            "confidence": self.confidence,
            "n_rows_sampled": self.n_rows_sampled,
            "detector": self.detector,
            "detector_version": self.detector_version,
        }


def detect_corpus_language(texts: list[str], selected: str) -> tuple[LanguageResult, list[dict]]:
    """Corpus-level majority-vote detection on a sample of detectable rows."""
    from langdetect import DetectorFactory, detect  # lazy import
    from langdetect.lang_detect_exception import LangDetectException

    try:
        from importlib.metadata import version as _v

        detector_version = _v("langdetect")
    except Exception:
        detector_version = "unknown"

    DetectorFactory.seed = 0  # determinism - same corpus, same result, every run

    detectable = [t for t in texts if len(t.split()) >= DETECT_MIN_TOKENS][:DETECT_SAMPLE_MAX]
    warnings: list[dict] = []

    if len(detectable) < DETECT_MIN_ROWS:
        result = LanguageResult(selected, None, None, len(detectable), "langdetect", detector_version)
        warnings.append(
            warning(
                "LANGUAGE_UNCERTAIN",
                "info",
                f"Language could not be determined confidently ({len(detectable)} detectable "
                f"row(s), need {DETECT_MIN_ROWS}); language checks were skipped.",
            )
        )
        return result, warnings

    votes: dict[str, int] = {}
    for t in detectable:
        try:
            lang = detect(t)  # one detection per row (detect() is the expensive call)
        except LangDetectException:
            continue
        votes[lang] = votes.get(lang, 0) + 1

    if not votes:
        result = LanguageResult(selected, None, None, len(detectable), "langdetect", detector_version)
        warnings.append(
            warning("LANGUAGE_UNCERTAIN", "info",
                    "Language detection produced no result; language checks were skipped.")
        )
        return result, warnings

    top_lang, top_count = max(votes.items(), key=lambda kv: kv[1])
    confidence = round(top_count / sum(votes.values()), 3)
    result = LanguageResult(selected, top_lang, confidence, len(detectable), "langdetect", detector_version)

    if confidence < DETECT_CONFIDENCE:
        warnings.append(
            warning(
                "LANGUAGE_UNCERTAIN",
                "info",
                f"Detected language is uncertain (top candidate '{top_lang}' at "
                f"{confidence:.0%} of sampled rows); interpret language checks with care.",
            )
        )
    elif top_lang != selected.lower():
        warnings.append(
            warning(
                "LANGUAGE_MISMATCH",
                "warning",
                f"You selected '{selected}', but the corpus appears to be '{top_lang}' "
                f"({confidence:.0%} of {len(detectable)} sampled rows).",
                detected_language=top_lang,
                selected_language=selected,
            )
        )
    return result, warnings


def model_language_warning(selected: str, model_id: str, supported: frozenset[str],
                           language_set_name: str | None) -> dict | None:
    if not supported or selected.lower() in supported:
        return None
    label = f"the '{language_set_name}' language set" if language_set_name else \
        f"{sorted(supported)}"
    return warning(
        "MODEL_LANGUAGE_UNSUPPORTED",
        "warning",
        f"The selected model supports {label}, but you selected '{selected}'. "
        "Switch to a multilingual model or proceed with caution.",
        selected_language=selected,
        model_id=model_id,
    )
