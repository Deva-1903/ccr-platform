"""Named language sets resolved to ISO 639-1 codes.

A registry entry may declare `supported_language_set: xlm_roberta_100` instead of an
explicit list. This module resolves such names so the warning engine can check a
user-selected language against a real set (design doc §12 - a bare "multilingual"
label is banned because it is not machine-checkable).

xlm_roberta_100: languages covered by XLM-RoBERTa pretraining (Conneau et al., 2020),
which underlies the multilingual-E5 family. Verify against the model card when
adding new multilingual models.
"""

XLM_ROBERTA_100: frozenset[str] = frozenset(
    """
    af am ar as az be bg bn br bs ca cs cy da de el en eo es et eu fa fi fr fy ga gd
    gl gu ha he hi hr hu hy id is it ja jv ka kk km kn ko ku ky la lo lt lv mg mk ml
    mn mr ms my ne nl no om or pa pl ps pt ro ru sa sd si sk sl so sq sr su sv sw ta
    te th tl tr ug uk ur uz vi xh yi zh
    """.split()
)

LANGUAGE_SETS: dict[str, frozenset[str]] = {
    "xlm_roberta_100": XLM_ROBERTA_100,
}


def resolve(set_name: str) -> frozenset[str]:
    """Return the ISO-code set for a named language set; raises on unknown names."""
    if set_name not in LANGUAGE_SETS:
        raise KeyError(
            f"Unknown language set '{set_name}'. Known: {sorted(LANGUAGE_SETS)}. "
            "Add it here with a citation before referencing it in models.yaml."
        )
    return LANGUAGE_SETS[set_name]


def supports(set_name: str, iso_code: str) -> bool:
    return iso_code.lower() in resolve(set_name)
