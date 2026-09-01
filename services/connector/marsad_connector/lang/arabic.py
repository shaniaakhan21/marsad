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

The four functions are CAMeL Tools' own — `dediac_ar`, `normalize_alef_ar`,
`normalize_alef_maksura_ar`, `normalize_teh_marbuta_ar` — applied in a fixed order in
one place, so "the same functions at write time and at query time" is a property of
the code rather than a convention someone has to remember.

Raw text is what the analyst sees; normalised text is what the machine matches. Both
are kept, and `NormalisedText` carries the offset map between them so a span found in
normalised text can be shown back to the analyst as the words they actually typed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from camel_tools.utils.dediac import dediac_ar
from camel_tools.utils.normalize import (
    normalize_alef_ar,
    normalize_alef_maksura_ar,
    normalize_teh_marbuta_ar,
)

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
    "ARABIC_DOMINANT", "Language", "NormalisedText", "arabic_ratio", "detect_language",
    "has_arabic", "normalise", "normalise_tracked",
]
