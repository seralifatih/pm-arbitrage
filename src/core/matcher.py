"""Cross-venue market matcher (v2).

Scores pairs of normalized markets across two venues. Goal: identify when
both venues are pricing the same real-world event, even when the title
phrasings diverge sharply (Polymarket question form vs Kalshi ticker form).

Pipeline per candidate pair:
  1. Both must be binary (is_binary=True)
  2. Same category if both expose one
  3. Resolution dates within MAX_DATE_DIFF_DAYS (venues drift on same event)
  4. Title similarity ≥ TITLE_SIMILARITY_THRESHOLD (on normalized titles)
  5. ENTITY GATE: at least MIN_SHARED_ENTITIES distinguishing entities
     in common AND no critical entity mismatch (different numeric thresholds
     on the same metric = different events)
  6. Weighted confidence threshold

Confidence weighting (v2):
  - Entity overlap (Szymkiewicz–Simpson): 60%   ← primary signal
  - Title similarity (normalized):        25%
  - Date proximity:                       15%
"""
from datetime import date

from rapidfuzz import fuzz

from .title_normalizer import extract_entities, normalize_title

# v2: widened from 3d → 30d. Same event resolves on different "close" dates
# across venues (Kalshi closes mid-day before resolution; Polymarket on
# resolution day; election markets have multi-week settlement windows).
MAX_DATE_DIFF_DAYS = 30

# Loose title threshold: cross-venue phrasings legitimately differ. Real
# matches score 50–70 even after normalization. Entity gate does the lift.
TITLE_SIMILARITY_THRESHOLD = 50

# Entity gate: a real cross-venue match shares ≥2 distinguishing entities.
# Single-entity overlaps ("Pittsburgh", "Trump") collide across unrelated
# events; two or more in common is overwhelmingly the same event.
MIN_SHARED_ENTITIES = 2


def _parse_date(iso_str: str) -> date | None:
    try:
        return date.fromisoformat(iso_str[:10])
    except (ValueError, TypeError):
        return None


def _date_score(diff_days: int) -> float:
    """0–100 score: 100 if same day, decays linearly to 0 at MAX_DATE_DIFF_DAYS."""
    if diff_days <= 0:
        return 100.0
    if diff_days >= MAX_DATE_DIFF_DAYS:
        return 0.0
    return round(100.0 * (1.0 - diff_days / MAX_DATE_DIFF_DAYS), 2)


def _entity_overlap_pct(entities_a: set[str], entities_b: set[str]) -> float:
    """Szymkiewicz–Simpson overlap coefficient ×100.

    |A ∩ B| / min(|A|, |B|). Better than Jaccard for cross-venue matching
    because Kalshi titles include extra ticker words (`funds`, `target`,
    `decision`) that are not in the Polymarket version. Jaccard penalizes
    that asymmetry; Szymkiewicz–Simpson does not — it asks "does the
    smaller set fit inside the larger one?"

    Empty sets → 0.
    """
    if not entities_a or not entities_b:
        return 0.0
    intersection = entities_a & entities_b
    smaller = min(len(entities_a), len(entities_b))
    return len(intersection) / smaller * 100.0


def _conflicting_thresholds(entities_a: set[str], entities_b: set[str]) -> bool:
    """Detect when both sides have currency/percent thresholds but they differ.

    Catches: "$100k vs $80k", "5% vs 7%". A real match on a *threshold* market
    needs the same threshold; otherwise they're different events even if every
    other entity matches (Bitcoin/close/2026/EOY).
    """
    def _thresholds(es: set[str]) -> set[str]:
        out = set()
        for e in es:
            # Currency: $100k, $3000
            if e.startswith("$"):
                out.add(e)
            # Percent: 5%, 50%
            elif e.endswith("%"):
                out.add(e)
        return out

    ta, tb = _thresholds(entities_a), _thresholds(entities_b)
    if ta and tb and ta != tb:
        return True
    return False


def match_markets(
    markets_a: list[dict],
    markets_b: list[dict],
    venue_a_name: str,
    venue_b_name: str,
    min_confidence: int = 70,
) -> list[dict]:
    results = []

    # Pre-normalize side A once.
    norm_a = []
    for ma in markets_a:
        if not ma.get("is_binary"):
            continue
        title_a = ma.get("title", "")
        normalized_a = normalize_title(title_a)
        if not normalized_a:
            continue
        norm_a.append({
            "market": ma,
            "date": _parse_date(ma.get("resolution_date", "")),
            "category": ma.get("category", ""),
            "normalized_title": normalized_a,
            "entities": extract_entities(normalized_a),
        })

    # Pre-normalize side B once.
    norm_b = []
    for mb in markets_b:
        if not mb.get("is_binary"):
            continue
        title_b = mb.get("title", "")
        normalized_b = normalize_title(title_b)
        if not normalized_b:
            continue
        norm_b.append({
            "market": mb,
            "date": _parse_date(mb.get("resolution_date", "")),
            "category": mb.get("category", ""),
            "normalized_title": normalized_b,
            "entities": extract_entities(normalized_b),
        })

    for a in norm_a:
        for b in norm_b:
            # Step 2: category pre-filter (only if both have one)
            if a["category"] and b["category"] and a["category"] != b["category"]:
                continue

            # Step 3: date window
            if a["date"] is None or b["date"] is None:
                diff_days = MAX_DATE_DIFF_DAYS + 1
            else:
                diff_days = abs((a["date"] - b["date"]).days)

            if diff_days > MAX_DATE_DIFF_DAYS:
                continue

            # Step 4: title similarity (loose, on normalized titles)
            title_score = fuzz.token_sort_ratio(a["normalized_title"], b["normalized_title"])
            if title_score < TITLE_SIMILARITY_THRESHOLD:
                continue

            # Step 5: entity gate — primary signal
            shared = a["entities"] & b["entities"]
            if len(shared) < MIN_SHARED_ENTITIES:
                continue

            # Reject if both sides have conflicting thresholds (different
            # numeric strikes = different events even if everything else matches).
            if _conflicting_thresholds(a["entities"], b["entities"]):
                continue

            entity_score = _entity_overlap_pct(a["entities"], b["entities"])

            # Step 6: weighted confidence
            date_score = _date_score(diff_days)
            confidence = int(round(
                entity_score * 0.60
                + title_score * 0.25
                + date_score * 0.15
            ))

            if confidence < min_confidence:
                continue

            results.append({
                "market_a": a["market"],
                "market_b": b["market"],
                "venue_a_name": venue_a_name,
                "venue_b_name": venue_b_name,
                "match_confidence": confidence,
                "date_diff_days": diff_days,
            })

    results.sort(key=lambda x: x["match_confidence"], reverse=True)
    return results
