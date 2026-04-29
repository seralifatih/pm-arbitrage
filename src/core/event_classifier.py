"""Classify Polymarket events into arb-eligible structures.

Only two event structures generate real arbitrage:

  1. WINNER_TAKE_ALL: exactly one outcome resolves YES (Σ YES = 1.0)
     e.g. "2028 Democratic Nominee", "NBA Finals winner", "Who becomes Pope"

  2. TOP_K: exactly K outcomes resolve YES (Σ YES = K)
     e.g. "Top 4 Serie A finish" (K=4), "Champions League finalists" (K=2)

Everything else is NOT arbitrage:

  - CUMULATIVE: "X happens by date Y" with multiple dates — nested, not exclusive
  - LADDER: "Price reaches $X" with multiple thresholds — nested, not exclusive
  - INDEPENDENT: prop bets, multi-condition questions — outcomes can co-resolve

Misclassifying any of these as arb produces false positives that look like
huge edge (Σ YES = 0.05 → 1900% return) but represent zero real opportunity.
The classifier is INTENTIONALLY conservative — when in doubt, return NOT_ARB.
"""
import re
from enum import Enum


class EventType(Enum):
    WINNER_TAKE_ALL = "winner_take_all"  # Σ YES = 1.0
    TOP_K = "top_k"                       # Σ YES = K
    NOT_ARB = "not_arb"                   # no sum constraint


# --------------------------------------------------------------------------
# Signals that an event is CUMULATIVE / time-laddered (NOT arb)
# --------------------------------------------------------------------------

# "by April 30", "by Q4", "by EOY", "by year end" in question text
_BY_DATE_RE = re.compile(
    r"\bby\s+("
    r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?|"
    r"q[1-4]|eoy|year\s+end|end\s+of"
    r")\b",
    re.IGNORECASE,
)

# Outcome label looks like a date: "April 30", "May 31", "June 30, 2026"
_DATE_LABEL_RE = re.compile(
    r"^(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
    r"\s+\d{1,2}",
    re.IGNORECASE,
)


# --------------------------------------------------------------------------
# Signals that an event is a PRICE/THRESHOLD LADDER (NOT arb)
# --------------------------------------------------------------------------

# Outcome labels with directional arrows: "↑ 110", "↓ 70", "↑110"
_ARROW_LABEL_RE = re.compile(r"[↑↓⬆⬇]")

# Outcome labels that are pure thresholds: "80+", "60+", "$100k", "300M"
_THRESHOLD_LABEL_RE = re.compile(
    r"^(?:\$?\d+(?:[.,]\d+)?[kmbKMB]?\+?|\d+°[CFcf]?)$"
)

# Outcome labels with units suggesting ladder: "300M", "375M", "$100k"
_UNITS_LABEL_RE = re.compile(r"\d+\s*[°%]|\d+[kmbKMB]\b")


# --------------------------------------------------------------------------
# Signals that an event is INDEPENDENT (player props, multi-condition)
# --------------------------------------------------------------------------

# "O/U" appears in question (over/under prop bet)
_OU_RE = re.compile(r"\bO/U\b|\bover/under\b|\bover\b\s+\d", re.IGNORECASE)

# "Will Trump publicly insult someone on April 26 / 28 / 29 / 30" — same predicate,
# different dates, but each can co-resolve. Caught by _BY_DATE / _DATE_LABEL.

# Question pattern "What X will Y do" / "What X will happen" / "Which X will..."
# that lists multiple distinct possibilities (each can co-resolve)
_WHAT_WILL_AGREE_RE = re.compile(
    r"\bwhat\s+\w+\s+will\b|\bwhich\s+\w+\s+will\b",
    re.IGNORECASE,
)


# --------------------------------------------------------------------------
# Whitelist: explicit winner-take-all / top-K patterns
# --------------------------------------------------------------------------

# Title contains "Top N" → top-K event with parseable K
_TOP_K_RE = re.compile(r"\btop\s*(\d+)\b", re.IGNORECASE)

# "Reach (the) final/finals" → top-K with K=2
_REACH_FINAL_RE = re.compile(r"\breach\s+(?:the\s+)?final(?:s)?\b", re.IGNORECASE)

# "to reach final" / "team to reach final" → top-K with K=2
_TO_REACH_FINAL_RE = re.compile(r"\bto\s+reach\s+(?:the\s+)?final(?:s)?\b", re.IGNORECASE)

# "Make it to" / "advance to" the final → top-K with K=2
_ADVANCE_FINAL_RE = re.compile(
    r"\b(?:make\s+it\s+to|advance\s+to)\s+(?:the\s+)?final(?:s)?\b",
    re.IGNORECASE,
)

# Strong winner-take-all signals
_WINNER_TAKE_ALL_PATTERNS = [
    re.compile(r"\bnominee\b", re.IGNORECASE),
    re.compile(r"\bnomination\b", re.IGNORECASE),
    re.compile(r"\bwinner\b", re.IGNORECASE),
    re.compile(r"\bwins?\s+the\s+\d{4}", re.IGNORECASE),  # "wins the 2028 X"
    re.compile(r"\bchampion(?:ship)?\b", re.IGNORECASE),
    re.compile(r"\bnext\s+(?:president|ceo|pope|monarch|prime\s+minister)\b", re.IGNORECASE),
]


def _looks_cumulative(event_title: str, leg_questions: list[str], leg_labels: list[str]) -> bool:
    """Detect 'happens by date X' cumulative structure."""
    # Title says "by..."
    if "by" in event_title.lower() and any(
        word in event_title.lower() for word in [
            "april", "may", "june", "july", "august", "september",
            "october", "november", "december", "january", "february", "march",
            "eoy", "q1", "q2", "q3", "q4",
        ]
    ):
        # Title shape "...by..." is suspicious; confirm with leg labels.
        return True

    # Multiple leg questions all use "by <date>" pattern
    by_date_count = sum(1 for q in leg_questions if _BY_DATE_RE.search(q))
    if by_date_count >= len(leg_questions) - 1 and by_date_count >= 2:
        return True

    # Multiple leg labels are dates
    date_label_count = sum(1 for label in leg_labels if _DATE_LABEL_RE.match(label))
    if date_label_count >= len(leg_labels) - 1 and date_label_count >= 2:
        return True

    return False


def _looks_like_ladder(leg_labels: list[str]) -> bool:
    """Detect price ladder / threshold structure."""
    # Any leg uses arrow notation
    if any(_ARROW_LABEL_RE.search(label) for label in leg_labels):
        return True

    # Most legs are pure threshold labels
    threshold_count = sum(1 for label in leg_labels if _THRESHOLD_LABEL_RE.match(label.strip()))
    if threshold_count >= len(leg_labels) - 1 and threshold_count >= 2:
        return True

    # Labels look like units (300M, 375M, 250M / 17°C, 18°C / 5%, 7%)
    units_count = sum(1 for label in leg_labels if _UNITS_LABEL_RE.search(label))
    if units_count >= len(leg_labels) - 1 and units_count >= 2:
        return True

    return False


def _looks_like_props(event_title: str, leg_questions: list[str]) -> bool:
    """Player props: 'X: Stat O/U Y' across different stats. Independent outcomes."""
    ou_count = sum(1 for q in leg_questions if _OU_RE.search(q))
    return ou_count >= 2


def _looks_like_multi_condition(event_title: str) -> bool:
    """'What X will Y' / 'Which X will Y' — multiple possibilities can co-resolve."""
    # Skip if it's a clear winner-take-all
    if any(pat.search(event_title) for pat in _WINNER_TAKE_ALL_PATTERNS):
        return False
    return bool(_WHAT_WILL_AGREE_RE.search(event_title))


def _is_winner_take_all(event_title: str) -> bool:
    return any(pat.search(event_title) for pat in _WINNER_TAKE_ALL_PATTERNS)


def _top_k_value(event_title: str) -> int | None:
    """Return K if event is top-K structured, else None."""
    m = _TOP_K_RE.search(event_title)
    if m:
        try:
            k = int(m.group(1))
            if 2 <= k <= 20:
                return k
        except ValueError:
            return None

    if (_REACH_FINAL_RE.search(event_title)
            or _TO_REACH_FINAL_RE.search(event_title)
            or _ADVANCE_FINAL_RE.search(event_title)):
        return 2

    return None


def classify_event(
    event_title: str,
    leg_questions: list[str],
    leg_labels: list[str],
) -> tuple[EventType, float | None]:
    """Classify event and return (type, expected_sum_yes).

    expected_sum_yes:
      - 1.0 for WINNER_TAKE_ALL
      - K   for TOP_K
      - None for NOT_ARB
    """
    title = event_title or ""

    # NOT_ARB checks first (conservative): if any disqualifying signal present,
    # reject regardless of whitelist matches.
    if _looks_cumulative(title, leg_questions, leg_labels):
        return EventType.NOT_ARB, None
    if _looks_like_ladder(leg_labels):
        return EventType.NOT_ARB, None
    if _looks_like_props(title, leg_questions):
        return EventType.NOT_ARB, None
    if _looks_like_multi_condition(title):
        return EventType.NOT_ARB, None

    # Now whitelist: must have a clear arb structure to qualify.
    k = _top_k_value(title)
    if k is not None:
        return EventType.TOP_K, float(k)

    if _is_winner_take_all(title):
        return EventType.WINNER_TAKE_ALL, 1.0

    # Default: not provably arb-eligible.
    return EventType.NOT_ARB, None
