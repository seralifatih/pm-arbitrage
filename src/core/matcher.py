import re
from datetime import date

from rapidfuzz import fuzz

_STOPWORDS = frozenset({
    "a", "an", "the", "will", "would", "be", "is", "are", "was", "were",
    "in", "on", "at", "by", "for", "of", "to", "do", "does", "did",
    "after", "before", "above", "below", "over", "under", "it", "its",
    "this", "that", "with", "and", "or", "not", "no", "yes", "if",
    "than", "then", "from", "into", "during", "through",
})


def _parse_date(iso_str: str) -> date | None:
    try:
        return date.fromisoformat(iso_str[:10])
    except (ValueError, TypeError):
        return None


def _entity_tokens(title: str) -> set[str]:
    """Strip stopwords, numbers, and date-like tokens; return lowercase noun set."""
    tokens = re.sub(r"[^a-zA-Z\s]", " ", title).lower().split()
    return {t for t in tokens if t not in _STOPWORDS and len(t) > 1}


def _date_score(diff_days: int) -> float:
    """0–100 score: 100 if same day, 0 if > 3 days."""
    if diff_days == 0:
        return 100.0
    if diff_days == 1:
        return 67.0
    if diff_days == 2:
        return 33.0
    if diff_days == 3:
        return 10.0
    return 0.0


def match_markets(
    markets_a: list[dict],
    markets_b: list[dict],
    venue_a_name: str,
    venue_b_name: str,
    min_confidence: int = 70,
) -> list[dict]:
    results = []

    for ma in markets_a:
        # Step 5 pre-check: skip non-binary on side A early
        if not ma.get("is_binary"):
            continue

        date_a = _parse_date(ma.get("resolution_date", ""))
        category_a = ma.get("category", "")
        entities_a = _entity_tokens(ma.get("title", ""))

        for mb in markets_b:
            # Step 5: both must be binary
            if not mb.get("is_binary"):
                continue

            # Step 1: category pre-filter (only when both have a category)
            category_b = mb.get("category", "")
            if category_a and category_b and category_a != category_b:
                continue

            # Step 2: date window filter
            date_b = _parse_date(mb.get("resolution_date", ""))
            if date_a is None or date_b is None:
                diff_days = 999
            else:
                diff_days = abs((date_a - date_b).days)

            if diff_days > 3:
                continue

            # Step 3: title similarity
            title_a = ma.get("title", "")
            title_b = mb.get("title", "")
            title_score = fuzz.token_sort_ratio(title_a, title_b)

            if title_score < 75:
                continue

            # Step 4: entity overlap
            entities_b = _entity_tokens(title_b)
            if entities_a and entities_b:
                union = entities_a | entities_b
                intersection = entities_a & entities_b
                overlap_pct = len(intersection) / len(union) * 100
            else:
                overlap_pct = 0.0

            # Weighted confidence: title 50%, date 30%, entity 20%
            date_sc = _date_score(diff_days)
            entity_sc = min(overlap_pct, 100.0)
            confidence = int(
                round(title_score * 0.50 + date_sc * 0.30 + entity_sc * 0.20)
            )

            if confidence < min_confidence:
                continue

            results.append({
                "market_a": ma,
                "market_b": mb,
                "venue_a_name": venue_a_name,
                "venue_b_name": venue_b_name,
                "match_confidence": confidence,
                "date_diff_days": diff_days,
            })

    # Sort best confidence first
    results.sort(key=lambda x: x["match_confidence"], reverse=True)
    return results
