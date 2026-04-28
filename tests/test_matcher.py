import pytest
from src.core.matcher import match_markets


def _market(
    title: str,
    resolution_date: str,
    is_binary: bool = True,
    category: str = "",
    market_id: str = "test-id",
) -> dict:
    return {
        "id": market_id,
        "title": title,
        "resolution_date": resolution_date,
        "yes_price": 0.5,
        "no_price": 0.5,
        "liquidity_usd": 10000,
        "volume_usd": 50000,
        "market_url": f"https://example.com/{market_id}",
        "is_binary": is_binary,
        "category": category,
        "raw": {},
    }


# ---------------------------------------------------------------------------
# Clear match
# ---------------------------------------------------------------------------

class TestClearMatch:
    def test_high_confidence_on_similar_titles(self):
        # v2: titles need ≥2 shared distinguishing entities post-normalization.
        a = [_market("Will the Lakers win the 2026 NBA Finals?", "2026-06-22")]
        b = [_market("NBAFINALS-26 — NBA Finals winner: Los Angeles Lakers", "2026-06-22")]
        results = match_markets(a, b, "polymarket", "kalshi")
        assert len(results) == 1
        assert results[0]["match_confidence"] >= 70

    def test_result_has_required_keys(self):
        a = [_market("Will the Boston Celtics win the 2026 NBA Finals?", "2026-06-22")]
        b = [_market("NBAFINALS-26 — NBA Finals winner: Boston Celtics", "2026-06-22")]
        results = match_markets(a, b, "polymarket", "kalshi")
        assert len(results) == 1
        r = results[0]
        assert "market_a" in r
        assert "market_b" in r
        assert "match_confidence" in r
        assert "date_diff_days" in r
        assert r["venue_a_name"] == "polymarket"
        assert r["venue_b_name"] == "kalshi"

    def test_date_diff_days_correct(self):
        a = [_market("Will the Lakers win the 2026 NBA Finals?", "2026-06-22")]
        b = [_market("NBAFINALS-26 — NBA Finals winner: Los Angeles Lakers", "2026-06-23")]
        results = match_markets(a, b, "polymarket", "kalshi")
        assert len(results) == 1
        assert results[0]["date_diff_days"] == 1

    def test_sorted_by_confidence_descending(self):
        a = [
            _market("Will the Lakers win the 2026 NBA Finals?", "2026-06-22", market_id="a1"),
            _market("Will Democrats control the Senate after the 2026 elections?", "2026-11-04", market_id="a2"),
        ]
        b = [
            _market("NBAFINALS-26 — NBA Finals winner: Los Angeles Lakers", "2026-06-22", market_id="b1"),
            _market("SENATE-26 — Democrats win Senate majority in 2026 elections", "2026-11-04", market_id="b2"),
        ]
        results = match_markets(a, b, "polymarket", "kalshi")
        confidences = [r["match_confidence"] for r in results]
        assert confidences == sorted(confidences, reverse=True)


# ---------------------------------------------------------------------------
# Date filter
# ---------------------------------------------------------------------------

class TestDateFilter:
    # Use richer cross-venue titles that survive v2 entity gate.
    _A_TITLE = "Will the Lakers win the 2026 NBA Finals?"
    _B_TITLE = "NBAFINALS-26 — NBA Finals winner: Los Angeles Lakers"

    def test_45_days_apart_excluded(self):
        # v2: window widened to 30d. 45d is outside the window.
        a = [_market(self._A_TITLE, "2026-06-22")]
        b = [_market(self._B_TITLE, "2026-08-06")]
        assert match_markets(a, b, "polymarket", "kalshi") == []

    def test_exactly_3_days_included(self):
        a = [_market(self._A_TITLE, "2026-06-22")]
        b = [_market(self._B_TITLE, "2026-06-25")]
        assert len(match_markets(a, b, "polymarket", "kalshi")) == 1

    def test_within_30_day_window_included(self):
        # v2: ~1 week drift between venues should match comfortably.
        a = [_market(self._A_TITLE, "2026-06-22")]
        b = [_market(self._B_TITLE, "2026-06-29")]  # 7d
        assert len(match_markets(a, b, "polymarket", "kalshi")) == 1

    def test_31_days_excluded(self):
        a = [_market(self._A_TITLE, "2026-06-22")]
        b = [_market(self._B_TITLE, "2026-07-23")]
        assert match_markets(a, b, "polymarket", "kalshi") == []


# ---------------------------------------------------------------------------
# Binary filter
# ---------------------------------------------------------------------------

class TestBinaryFilter:
    def test_non_binary_market_a_excluded(self):
        a = [_market("Who wins the 2025 NBA Championship?", "2025-06-22", is_binary=False)]
        b = [_market("Who wins the 2025 NBA Championship?", "2025-06-22", is_binary=True)]
        results = match_markets(a, b, "polymarket", "kalshi")
        assert results == []

    def test_non_binary_market_b_excluded(self):
        a = [_market("Who wins the 2025 NBA Championship?", "2025-06-22", is_binary=True)]
        b = [_market("Who wins the 2025 NBA Championship?", "2025-06-22", is_binary=False)]
        results = match_markets(a, b, "polymarket", "kalshi")
        assert results == []

    def test_both_non_binary_excluded(self):
        a = [_market("UK election winner 2025?", "2025-05-01", is_binary=False)]
        b = [_market("UK election winner 2025?", "2025-05-01", is_binary=False)]
        results = match_markets(a, b, "polymarket", "kalshi")
        assert results == []


# ---------------------------------------------------------------------------
# Title similarity filter
# ---------------------------------------------------------------------------

class TestTitleSimilarity:
    def test_unrelated_markets_excluded(self):
        a = [_market("Will the Fed cut rates in June 2025?", "2025-06-18")]
        b = [_market("Will Elon Musk resign from Tesla by 2026?", "2025-12-31")]
        results = match_markets(a, b, "polymarket", "kalshi")
        assert results == []

    def test_slightly_different_wording_still_matches(self):
        # token_sort_ratio handles word-order differences well
        a = [_market("US unemployment rate above 5% in 2025?", "2025-12-31")]
        b = [_market("Will US unemployment rate exceed 5% in 2025?", "2025-12-31")]
        results = match_markets(a, b, "polymarket", "kalshi")
        assert len(results) == 1


# ---------------------------------------------------------------------------
# Category filter
# ---------------------------------------------------------------------------

class TestCategoryFilter:
    def test_different_categories_excluded(self):
        a = [_market("Fed rate cut June 2025?", "2025-06-18", category="economics")]
        b = [_market("Fed rate cut June 2025?", "2025-06-18", category="sports")]
        results = match_markets(a, b, "polymarket", "kalshi")
        assert results == []

    def test_same_category_included(self):
        a = [_market("Fed rate cut June 2025?", "2025-06-18", category="economics")]
        b = [_market("Fed rate cut June 2025?", "2025-06-18", category="economics")]
        results = match_markets(a, b, "polymarket", "kalshi")
        assert len(results) == 1

    def test_missing_category_skips_filter(self):
        a = [_market("Fed rate cut June 2025?", "2025-06-18", category="")]
        b = [_market("Fed rate cut June 2025?", "2025-06-18", category="economics")]
        results = match_markets(a, b, "polymarket", "kalshi")
        assert len(results) == 1


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_empty_lists_return_empty(self):
        assert match_markets([], [], "polymarket", "kalshi") == []

    def test_empty_markets_a(self):
        b = [_market("Fed rate cut June 2025?", "2025-06-18")]
        assert match_markets([], b, "polymarket", "kalshi") == []

    def test_empty_markets_b(self):
        a = [_market("Fed rate cut June 2025?", "2025-06-18")]
        assert match_markets(a, [], "polymarket", "kalshi") == []

    def test_confidence_below_70_excluded(self):
        # Titles share only minor words — should fall below 70
        a = [_market("Will gold price hit $3000 in 2025?", "2025-12-31")]
        b = [_market("Will oil reach $100 per barrel by year end?", "2025-12-31")]
        results = match_markets(a, b, "polymarket", "kalshi")
        assert results == []

    def test_min_confidence_override(self):
        a = [_market("Will the Lakers win the 2026 NBA Finals?", "2026-06-22")]
        b = [_market("NBAFINALS-26 — NBA Finals winner: Los Angeles Lakers", "2026-06-22")]
        # Default min=70 should include it
        results = match_markets(a, b, "polymarket", "kalshi", min_confidence=70)
        assert len(results) == 1
        # Very high threshold should exclude it
        results_strict = match_markets(a, b, "polymarket", "kalshi", min_confidence=99)
        assert results_strict == []
