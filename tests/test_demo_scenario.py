"""
The guided demo's scenario actually produces the match it narrates.

Read straight from the demo page, so the narratives tested are the ones a judge watches.
This exists because the demo once matched only on leftovers from earlier runs: on a
clean core the English and Arabic reports shared no technique, step 3 said "the
correlation fires", and nothing did. The browser test only checked the panel appeared.
"""

from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [
    str(ROOT / "packages" / "contracts"),
    str(ROOT / "services" / "connector"),
    str(ROOT / "services" / "core"),
]

from marsad_connector.agents.a2_extract import ExtractionAgent
from marsad_core.engines.correlation import DEFAULT_SIMILARITY_THRESHOLD
from marsad_core.engines.similarity import build_similarity_engine

DEMO = (ROOT / "apps" / "web" / "app" / "demo" / "page.tsx").read_text()


def _narrative(name: str) -> str:
    body = re.search(rf"const {name} =(.*?);\n", DEMO, re.DOTALL).group(1)
    return "".join(re.findall(r'"((?:[^"\\]|\\.)*)"', body))


def _techniques(narrative: str) -> list[str]:
    draft = asyncio.run(ExtractionAgent().propose(narrative))
    return list(draft.fields["techniques"].value or [])


def test_the_english_and_arabic_demo_reports_match_on_a_clean_core():
    """Step 3 of the guided demo, proven without any earlier data to lean on."""
    english = _techniques(_narrative("EN_NARRATIVE"))
    arabic = _techniques(_narrative("AR_NARRATIVE"))
    score = build_similarity_engine("jaccard").compare(english, arabic).score
    assert score >= DEFAULT_SIMILARITY_THRESHOLD, (english, arabic, score)


def test_the_arabic_demo_report_uses_different_infrastructure():
    """The point of step 3 is a match on tradecraft, so no indicator may be shared."""
    assert "sso-almaha-verify" not in _narrative("AR_NARRATIVE")
    assert "gulfsec-rotated.com" not in _narrative("EN_NARRATIVE")


def test_an_arabic_phishing_link_and_impersonation_are_recognised():
    """The same attack must classify the same way in either language."""
    found = _techniques("رسالة تصيد تنتحل صفة البنك مع رابط احتيالي. الأثر: عالي.")
    assert set(found) == {"T1566.002", "T1656"}


def test_a_negated_arabic_impersonation_is_not_read_as_one():
    """"ولم يتم انتحال" means no impersonation happened. A rule must not invert it."""
    assert "T1656" not in _techniques("رسالة تصيد، ولم يتم انتحال أي جهة. الأثر: منخفض.")


def test_and_not_written_as_one_word_still_negates_any_arabic_cue():
    """The conjunction attaches to the particle; the guard must see through it."""
    assert "T1486" not in _techniques("تعطل نظام التداول، ولم يتم تشفير الملفات. الأثر: متوسط.")
    assert "T1486" in _techniques("تعطل نظام التداول وتم تشفير الملفات. الأثر: متوسط.")
