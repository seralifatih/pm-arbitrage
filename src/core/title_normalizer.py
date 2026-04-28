"""Normalize prediction-market titles so cross-venue fuzzy matching works.

Polymarket and Kalshi phrase the same event very differently:
  Polymarket: "Will the Lakers win the 2026 NBA Finals?"
  Kalshi:     "NBA Finals winner — Los Angeles Lakers"

Both share the core phrase ("lakers nba finals 2026"). Raw token_sort_ratio
on the originals scores ~50; on normalized strings it scores 80+.
"""
import re

# Leading question forms — Polymarket loves these.
_LEAD_QUESTION = re.compile(
    r"^(will|would|does|do|did|is|are|was|were|has|have|had|can|could|should)\s+",
    re.IGNORECASE,
)

# "the/a/an" right after the question word.
_LEAD_ARTICLE = re.compile(r"^(the|a|an)\s+", re.IGNORECASE)

# Kalshi-style ticker prefix: "FED-25JUN-T5.25 — ..." or "NBAFINALS25 — ..."
_KALSHI_TICKER_PREFIX = re.compile(r"^[A-Z][A-Z0-9._-]{2,}\s*[—–-]\s*")

# Parenthesized aside: "(FOMC)", "(Q4)", "(by end of year)"
_PAREN_ASIDE = re.compile(r"\s*\([^)]*\)")

# Date phrases that add no semantic value once entities are matched.
# Months
_MONTHS = (
    r"(?:jan|january|feb|february|mar|march|apr|april|may|jun|june|"
    r"jul|july|aug|august|sep|september|oct|october|nov|november|dec|december)"
)
_DATE_PHRASES = [
    re.compile(rf"\bby\s+(?:the\s+)?end\s+of\s+\d{{4}}\b", re.IGNORECASE),
    re.compile(rf"\bby\s+(?:the\s+)?end\s+of\s+{_MONTHS}\b", re.IGNORECASE),
    re.compile(rf"\bafter\s+(?:the\s+)?{_MONTHS}\s+\d{{4}}(?:\s+meeting)?\b", re.IGNORECASE),
    re.compile(rf"\bin\s+{_MONTHS}\s+\d{{4}}\b", re.IGNORECASE),
    re.compile(rf"\bat\s+(?:the\s+)?{_MONTHS}\s+\d{{4}}(?:\s+(?:fomc|meeting))?\b", re.IGNORECASE),
    re.compile(r"\bby\s+(?:eoy|year\s+end|end\s+of\s+year)\b", re.IGNORECASE),
    re.compile(r"\bby\s+q[1-4]\s+\d{4}\b", re.IGNORECASE),
    re.compile(rf"\b{_MONTHS}\s+\d{{1,2}}(?:st|nd|rd|th)?\s+\d{{4}}\b", re.IGNORECASE),
    re.compile(rf"\b{_MONTHS}\s+\d{{4}}\b", re.IGNORECASE),
    re.compile(r"\b\d{4}[–-]\d{2}\s+(?:season|tournament|cup)\b", re.IGNORECASE),
]

# Connective fluff that adds no entity value.
_FLUFF_PHRASES = [
    re.compile(r"\bend\s+of\s+(?:the\s+)?", re.IGNORECASE),
    re.compile(r"\bby\s+the\s+end\s+of\b", re.IGNORECASE),
    re.compile(r"\bmeeting\b", re.IGNORECASE),
    re.compile(r"\bwinner\b", re.IGNORECASE),
    re.compile(r"\bnominee\b", re.IGNORECASE),
]

_MULTISPACE = re.compile(r"\s+")
_PUNCT_TAIL = re.compile(r"[?!.,;:]+$")


def normalize_title(title: str) -> str:
    """Strip boilerplate/template noise from a prediction-market title.

    Returns lowercased, whitespace-collapsed string of just the core entities.
    """
    if not title:
        return ""

    s = title.strip()

    # Strip Kalshi ticker prefix first (case-sensitive on uppercase).
    s = _KALSHI_TICKER_PREFIX.sub("", s)

    # Strip parenthesized asides.
    s = _PAREN_ASIDE.sub("", s)

    # Strip leading "Will / Does / Is ..." then optional "the / a / an".
    s = _LEAD_QUESTION.sub("", s)
    s = _LEAD_ARTICLE.sub("", s)

    # Strip date phrases.
    for pat in _DATE_PHRASES:
        s = pat.sub("", s)

    # Strip fluff phrases.
    for pat in _FLUFF_PHRASES:
        s = pat.sub("", s)

    # Lowercase, collapse whitespace, drop trailing punctuation.
    s = s.lower()
    s = _PUNCT_TAIL.sub("", s.strip())
    s = _MULTISPACE.sub(" ", s).strip()

    return s


# ---------------------------------------------------------------------------
# Entity extraction — proper nouns + numbers (currency thresholds, years).
# Used as a tighter signal than raw word overlap.
# ---------------------------------------------------------------------------

_ENTITY_STOPWORDS = frozenset({
    # Articles / prepositions that occasionally survive normalization.
    "the", "a", "an", "in", "on", "at", "of", "to", "for", "by", "with",
    "after", "before", "from", "into", "as", "than",
    # Common verbs / connectives.
    "win", "wins", "won", "winning",
    "cut", "cuts", "raise", "raises", "hike", "hikes",
    "control", "controls", "lead", "leads",
    "close", "closes", "open", "opens",
    "decision", "exceed", "exceeds", "reach", "reaches",
    "above", "below", "over", "under", "more", "less",
    "next", "first", "last", "between",
    "and", "or", "vs", "versus",
    # Generic event nouns — too common to distinguish events.
    "race", "match", "game",
    "championship", "championships",
    "season", "playoffs",
    # Election structure words. "election"/"presidential" alone aren't
    # entity-distinguishing — the country/year + candidate names are.
    "election", "elections", "presidential",
    "round", "first", "second", "third", "1st", "2nd", "3rd",
})

# Numbers and currency thresholds (e.g. "100k", "$3000", "5.25", "2026").
_NUMBER = re.compile(r"\$?\d+(?:[.,]\d+)?[kmb]?", re.IGNORECASE)


def extract_entities(normalized_title: str) -> set[str]:
    """Pull proper-noun-like tokens + numbers from an already-normalized title.

    Heuristics (no NER, no model dep):
    - Numbers / currency thresholds count as entities.
    - All other multi-char tokens that aren't generic stopwords count.
      Normalization already removed dates/articles/question form,
      so what's left is overwhelmingly entities + verbs. We strip the verbs.
    """
    if not normalized_title:
        return set()

    entities: set[str] = set()
    for raw in normalized_title.split():
        token = raw.strip("'\".,;:!?()[]{}—–-").lower()
        if not token or len(token) < 2:
            continue
        if _NUMBER.fullmatch(token):
            entities.add(token)
            continue
        if token in _ENTITY_STOPWORDS:
            continue
        entities.add(token)

    return entities
