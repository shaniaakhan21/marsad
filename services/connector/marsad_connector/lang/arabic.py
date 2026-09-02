"""
Arabic text handling for incident intake.

Why this module exists as a single entry point
----------------------------------------------
UAE incident reports are written in Arabic, in English, and — most often — in both
at once: Arabic prose carrying English technical terms in the same sentence. Arabic
orthography is variable in ways that matter to string matching. The same word is
written with or without diacritics, with any of أ إ آ ا for alef, with ى or ي at the
end, and with ة or ه. A human reads all of these as the same word. `find()` does not.

So text is normalised before anything looks at it. The rule that makes that safe is
narrow and absolute:

    **`normalise()` is applied unconditionally, on every path, to every string.**

It is NOT gated on a language detector. A detector that says "Arabic" on the write
path and "English" on the query path — because a query is shorter, or happens to
contain fewer Arabic letters — reintroduces exactly the bug normalisation exists to
prevent, and it fails silently: no error, no exception, just a token that never
matches and a correlation that never fires. Detection in this module routes *cue
tables*. It never decides whether to normalise.

The four operations are CAMeL Tools' — `dediac_ar`, `normalize_alef_ar`,
`normalize_alef_maksura_ar`, `normalize_teh_marbuta_ar` — applied in a fixed order in
one place, so "the same functions at write time and at query time" is a property of
the code rather than a convention someone has to remember.

Why they are vendored rather than imported
------------------------------------------
`camel-tools` declares torch and transformers as hard dependencies, and torch's Linux
wheel pulls roughly thirty NVIDIA CUDA packages with it. Installing it put a 3.29GB
image inside an institution's perimeter to obtain four character maps — a deep-learning stack shipped, and its attack surface
accepted, for four `str.translate` tables. That contradicts the argument this project
makes everywhere else about what belongs inside the boundary, and three connectors at
that size do not fit on a modest VPS.

So the four maps are implemented below, derived from the upstream source and cited to
it. They are deliberately dull: a table and a translate, no cleverness, so a reviewer
can check them against the CAMeL source by eye.

Vendoring normally trades one risk for another — a second implementation that drifts
from the first, silently. Here that risk is a test rather than a hope:
`test_vendored_normalisation_matches_camel_tools` runs the real CAMeL Tools, kept as a
**test-only** dependency, and asserts identical output for **every codepoint in the
Arabic block U+0600–U+06FF individually**, for every Arabic fixture, and for the
code-switched cases. Not a sample — the whole range. If upstream ever changes, or if
one of these tables is edited wrongly, that test fails before anything ships.

Raw text is what the analyst sees; normalised text is what the machine matches. Both
are kept, and `NormalisedText` carries the offset map between them so a span found in
normalised text can be shown back to the analyst as the words they actually typed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

# --------------------------------------------------------------------------
# The four character maps, vendored from CAMeL Tools 1.6.0
# --------------------------------------------------------------------------
#
# Derived from camel_tools/utils/dediac.py (`_DIAC_RE_AR`) and
# camel_tools/utils/normalize.py (`_ALEF_NORMALIZE_AR_RE`, `normalize_alef_maksura_ar`,
# `normalize_teh_marbuta_ar`) at version 1.6.0, MIT licensed.
#
# Every one is a per-character rule with no context sensitivity, which is what makes
# the offset map in `NormalisedText` valid and what lets these be expressed as
# translation tables. The four sets are disjoint, so composing them in the fixed order
# below is equivalent to any other order — but the order is kept as upstream applies
# it, because "equivalent" is a claim a test should make, not a comment.

#: Arabic diacritics, removed outright. U+064B..U+0652 (tanween, short vowels, shadda,
#: sukun) plus U+0670 superscript alef. Upstream: `_DIAC_RE_AR`.
DIACRITICS: tuple[str, ...] = (
    "\u064b",  # ARABIC FATHATAN
    "\u064c",  # ARABIC DAMMATAN
    "\u064d",  # ARABIC KASRATAN
    "\u064e",  # ARABIC FATHA
    "\u064f",  # ARABIC DAMMA
    "\u0650",  # ARABIC KASRA
    "\u0651",  # ARABIC SHADDA
    "\u0652",  # ARABIC SUKUN
    "\u0670",  # ARABIC LETTER SUPERSCRIPT ALEF
)

#: Alef variants folded to plain alef. Upstream: `_ALEF_NORMALIZE_AR_RE`.
ALEF_VARIANTS: tuple[str, ...] = (
    "\u0622",  # ALEF WITH MADDA ABOVE
    "\u0623",  # ALEF WITH HAMZA ABOVE
    "\u0625",  # ALEF WITH HAMZA BELOW
    "\u0671",  # ALEF WASLA
)
PLAIN_ALEF = "\u0627"

ALEF_MAKSURA = "\u0649"
YEH = "\u064a"

TEH_MARBUTA = "\u0629"
HEH = "\u0647"

_DEDIAC_TABLE = str.maketrans("", "", "".join(DIACRITICS))
_ALEF_TABLE = str.maketrans({variant: PLAIN_ALEF for variant in ALEF_VARIANTS})
_ALEF_MAKSURA_TABLE = str.maketrans({ALEF_MAKSURA: YEH})
_TEH_MARBUTA_TABLE = str.maketrans({TEH_MARBUTA: HEH})


def dediac_ar(text: str) -> str:
    """Remove Arabic diacritics. Vendored from CAMeL Tools 1.6.0 `dediac_ar`."""
    return text.translate(_DEDIAC_TABLE)


def normalize_alef_ar(text: str) -> str:
    """Fold alef variants to plain alef. Vendored from CAMeL Tools 1.6.0."""
    return text.translate(_ALEF_TABLE)


def normalize_alef_maksura_ar(text: str) -> str:
    """Fold alef maksura to yeh. Vendored from CAMeL Tools 1.6.0."""
    return text.translate(_ALEF_MAKSURA_TABLE)


def normalize_teh_marbuta_ar(text: str) -> str:
    """Fold teh marbuta to heh. Vendored from CAMeL Tools 1.6.0."""
    return text.translate(_TEH_MARBUTA_TABLE)


#: Arabic letters, excluding the diacritic block (which dediac removes anyway).
_ARABIC_LETTER = re.compile(r"[ؠ-يٱ-ۓۺ-ۿ]")
_LATIN_LETTER = re.compile(r"[A-Za-z]")

#: Above this share of Arabic letters the text is treated as Arabic prose; anything
#: between this and zero is code-switched. The band is wide on purpose — misjudging
#: it costs a duplicate cue pass, while missing it costs an unread field.
ARABIC_DOMINANT = 0.60


class Language(str, Enum):
    ENGLISH = "ENGLISH"
    ARABIC = "ARABIC"
    MIXED = "MIXED"       # code-switched: Arabic prose, English technical terms


def normalise(text: str) -> str:
    """
    THE normalisation function. Every path uses this one; none reimplements it.

    Safe to apply to Latin text — all four operations are Arabic-script character
    maps and leave everything else untouched — which is what lets it be applied
    unconditionally rather than behind a language check.
    """
    if not text:
        return text
    return normalize_teh_marbuta_ar(
        normalize_alef_maksura_ar(normalize_alef_ar(dediac_ar(text)))
    )


@dataclass(frozen=True)
class NormalisedText:
    """
    Raw and normalised text together, with the map between them.

    `dediac_ar` deletes characters, so the two strings do not share an index space.
    Keeping the map is what allows matching on normalised text while still showing
    the analyst the exact words they typed — without it, an evidence span found in
    normalised text would highlight the wrong slice of the original.
    """

    raw: str
    text: str                      #: normalised; what patterns are matched against
    _offsets: tuple[int, ...]      #: normalised index -> raw index

    def to_raw_span(self, start: int, end: int) -> tuple[int, int] | None:
        """Translate a span in normalised coordinates back to raw coordinates."""
        if start >= end or start < 0 or end > len(self._offsets):
            return None
        raw_start = self._offsets[start]
        raw_end = self._offsets[end - 1] + 1
        # Diacritics dropped by normalisation sit between raw characters; extend so
        # the excerpt shown to the analyst is not clipped mid-word.
        while raw_end < len(self.raw) and not normalise(self.raw[raw_end]):
            raw_end += 1
        return (raw_start, raw_end)

    def raw_excerpt(self, start: int, end: int) -> str:
        span = self.to_raw_span(start, end)
        return self.raw[span[0]:span[1]] if span else ""


def normalise_tracked(raw: str) -> NormalisedText:
    """
    Normalise while recording where every surviving character came from.

    Built character by character. That is equivalent to normalising the whole string
    because all four operations are per-character maps — asserted by
    `test_character_wise_normalisation_matches_whole_string_normalisation`, which is
    what would catch a future CAMeL Tools release making any of them context-sensitive
    and silently invalidating every offset this class hands out.
    """
    out: list[str] = []
    offsets: list[int] = []
    for index, character in enumerate(raw or ""):
        mapped = normalise(character)
        for char in mapped:
            out.append(char)
            offsets.append(index)
    return NormalisedText(raw=raw or "", text="".join(out), _offsets=tuple(offsets))


def arabic_ratio(text: str) -> float:
    """Share of the letters in `text` that are Arabic. Digits and URLs do not count."""
    arabic = len(_ARABIC_LETTER.findall(text or ""))
    latin = len(_LATIN_LETTER.findall(text or ""))
    total = arabic + latin
    return (arabic / total) if total else 0.0


def detect_language(text: str) -> Language:
    """
    Classify the narrative so the right cue tables run.

    This decides which vocabularies to search, never whether to normalise. When any
    Arabic is present at all the Arabic cues run — a Gulf incident report written in
    English routinely still carries an Arabic severity label, and a missed field is a
    worse outcome than a redundant pass over the text.
    """
    ratio = arabic_ratio(text)
    if ratio == 0.0:
        return Language.ENGLISH
    if ratio >= ARABIC_DOMINANT:
        return Language.ARABIC
    return Language.MIXED


def has_arabic(text: str) -> bool:
    return bool(_ARABIC_LETTER.search(text or ""))


__all__ = [
    "ALEF_MAKSURA",
    "ALEF_VARIANTS",
    "ARABIC_DOMINANT",
    "DIACRITICS",
    "HEH",
    "PLAIN_ALEF",
    "TEH_MARBUTA",
    "YEH",
    "Language",
    "NormalisedText",
    "arabic_ratio",
    "dediac_ar",
    "detect_language",
    "has_arabic",
    "normalise",
    "normalise_tracked",
    "normalize_alef_ar",
    "normalize_alef_maksura_ar",
    "normalize_teh_marbuta_ar",
]
