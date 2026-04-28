"""v2 matcher precision/recall tests against hand-labeled cross-venue pairs.

Each pair in cross_venue_pairs.json has label = "true_match" or "false_match".
We feed each pair into match_markets() one at a time and assert:

  precision = TP / (TP + FP)  >= 0.85
  recall    = TP / (TP + FN)  >= 0.70

This is the v2 acceptance gate from BUILD_PROMPTS.md Prompt 13.
"""
import json
from pathlib import Path

import pytest

from src.core.matcher import match_markets
from src.core.title_normalizer import extract_entities, normalize_title

_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "cross_venue_pairs.json"


def _load_pairs() -> list[dict]:
    return json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))["pairs"]


def _market(title: str, resolution_date: str) -> dict:
    return {
        "id": title[:30],
        "title": title,
        "resolution_date": resolution_date,
        "yes_price": 0.5,
        "no_price": 0.5,
        "liquidity_usd": 10000,
        "volume_usd": 50000,
        "market_url": "https://example.com",
        "is_binary": True,
        "category": "",
        "raw": {},
    }


def _matched(pair: dict) -> bool:
    """True if the matcher considers this pair a match (≥ default min_confidence)."""
    a = [_market(pair["polymarket_title"], pair["polymarket_date"])]
    b = [_market(pair["kalshi_title"], pair["kalshi_date"])]
    return len(match_markets(a, b, "polymarket", "kalshi")) > 0


# ---------------------------------------------------------------------------
# Precision / recall acceptance gate
# ---------------------------------------------------------------------------

class TestPrecisionRecall:
    def test_precision_at_least_85_pct(self):
        pairs = _load_pairs()
        tp = sum(1 for p in pairs if p["label"] == "true_match" and _matched(p))
        fp = sum(1 for p in pairs if p["label"] == "false_match" and _matched(p))

        if tp + fp == 0:
            pytest.fail("Matcher returned 0 positives — no matches at all")

        precision = tp / (tp + fp)
        assert precision >= 0.85, (
            f"Precision {precision:.2%} < 85%. TP={tp} FP={fp}. "
            f"False positives leaking through:\n"
            + "\n".join(
                f"  - {p['case']}: {p['polymarket_title']!r} ↔ {p['kalshi_title']!r}"
                for p in pairs if p["label"] == "false_match" and _matched(p)
            )
        )

    def test_recall_at_least_70_pct(self):
        pairs = _load_pairs()
        tp = sum(1 for p in pairs if p["label"] == "true_match" and _matched(p))
        fn = sum(1 for p in pairs if p["label"] == "true_match" and not _matched(p))

        recall = tp / (tp + fn)
        assert recall >= 0.70, (
            f"Recall {recall:.2%} < 70%. TP={tp} FN={fn}. "
            f"True matches missed:\n"
            + "\n".join(
                f"  - {p['case']}: {p['polymarket_title']!r} ↔ {p['kalshi_title']!r}"
                for p in pairs if p["label"] == "true_match" and not _matched(p)
            )
        )


# ---------------------------------------------------------------------------
# Title normalizer unit tests
# ---------------------------------------------------------------------------

class TestNormalizer:
    def test_strips_will_question_form(self):
        out = normalize_title("Will the Lakers win the 2026 NBA Finals?")
        assert "will" not in out.split()
        assert "lakers" in out

    def test_strips_kalshi_ticker_prefix(self):
        out = normalize_title("NBAFINALS-26 — NBA Finals winner: Los Angeles Lakers")
        assert "nbafinals-26" not in out
        assert "lakers" in out

    def test_strips_date_phrases(self):
        out = normalize_title("Will Bitcoin close above $100k by end of 2026?")
        assert "by end of 2026" not in out
        assert "100k" in out
        assert "bitcoin" in out

    def test_strips_fomc_meeting_phrase(self):
        out = normalize_title("Will the Fed cut rates at the June 2026 FOMC meeting?")
        # "june 2026" date phrase stripped, "meeting" fluff stripped
        assert "june" not in out
        assert "2026" not in out
        assert "fed" in out

    def test_lowercases(self):
        out = normalize_title("Will THE Senate Flip in 2026?")
        assert out == out.lower()

    def test_empty_input(self):
        assert normalize_title("") == ""
        assert normalize_title("   ") == ""

    def test_strips_parens(self):
        out = normalize_title("Fed funds rate decision (FOMC June 2026)")
        assert "fomc" not in out


class TestEntityExtractor:
    def test_extracts_team_names(self):
        ents = extract_entities(normalize_title("Will the Lakers win the 2026 NBA Finals?"))
        assert "lakers" in ents
        assert "nba" in ents
        assert "2026" in ents

    def test_drops_generic_event_words(self):
        ents = extract_entities(normalize_title("Will Lakers win the 2026 NBA championship?"))
        # "championship" is a generic event word, should be filtered
        assert "championship" not in ents

    def test_extracts_currency_thresholds(self):
        ents = extract_entities(normalize_title("Bitcoin close above $100k by end of 2026"))
        assert "$100k" in ents or "100k" in ents

    def test_two_unrelated_titles_have_low_overlap(self):
        a = extract_entities(normalize_title("Will Arsenal win the 2025-26 Champions League?"))
        b = extract_entities(normalize_title("Will Magnus Carlsen win the 2026 Norway Chess?"))
        # Even if "win" template inflates fuzzy ratio, entity overlap stays low
        overlap = a & b
        assert len(overlap) <= 1  # only "2026" might overlap

    def test_two_related_titles_have_high_overlap(self):
        a = extract_entities(normalize_title("Will the Lakers win the 2026 NBA Finals?"))
        b = extract_entities(normalize_title("NBAFINALS-26 — NBA Finals winner: Los Angeles Lakers"))
        overlap = a & b
        # Both share lakers, nba, finals
        assert "lakers" in overlap
        assert "nba" in overlap
