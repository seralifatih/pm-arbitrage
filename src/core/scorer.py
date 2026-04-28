"""Signal score for multi-outcome arbitrage opportunities.

0–100 composite. Components:
  - net_return_pct      → 0 pts at 0%, 50 pts at 5%+ (linear, clamped)
  - all_legs_fillable   → 30 pts True, 0 pts False, 15 pts None
  - leg_count bonus     → fewer legs = easier to execute, more credible signal
  - days_to_resolution  → shorter = better (less holding cost / settlement risk)

Labels:
  ≥ 80 + net > 0 → "Pure arbitrage"
  60–79          → "Strong EV+ signal"
  40–59          → "EV+ with edge"
  < 40           → "Marginal"
"""
from typing import Optional


def _net_return_points(net_return_pct: float) -> float:
    """0% → 0 pts, 5%+ → 50 pts. Clamp at both ends."""
    if net_return_pct <= 0:
        # Allow small negative returns to score *something* so EV+ signals
        # land above the floor. -1% net → 0, -3% → -10 (clamped to 0).
        return max(0.0, 10.0 + net_return_pct * 10.0)
    if net_return_pct >= 5.0:
        return 50.0
    return (net_return_pct / 5.0) * 50.0


def _liquidity_points(all_fillable: Optional[bool]) -> float:
    if all_fillable is True:
        return 30.0
    if all_fillable is False:
        return 0.0
    return 15.0  # None / unknown → partial credit


def _leg_count_points(leg_count: int) -> float:
    """Fewer legs = easier to execute. 3 legs full credit; 10+ tapers to 0."""
    if leg_count <= 3:
        return 10.0
    if leg_count >= 10:
        return 0.0
    return round(10.0 * (10 - leg_count) / 7.0, 2)


def _days_points(days_to_resolution: int) -> float:
    if days_to_resolution < 0:
        return 0.0
    if days_to_resolution <= 30:
        return 10.0
    if days_to_resolution <= 90:
        return 5.0
    return 0.0


def _label(score: int, net_return_pct: float) -> str:
    if score >= 80 and net_return_pct > 0:
        return "Pure arbitrage"
    if score >= 60:
        return "Strong EV+ signal"
    if score >= 40:
        return "EV+ with edge"
    return "Marginal"


def score_opportunity(
    gross_return_pct: float,
    net_return_pct: float,
    all_fillable: Optional[bool],
    leg_count: int,
    days_to_resolution: int,
) -> tuple[int, str]:
    raw = (
        _net_return_points(net_return_pct)
        + _liquidity_points(all_fillable)
        + _leg_count_points(leg_count)
        + _days_points(days_to_resolution)
    )
    score = int(round(max(0.0, min(100.0, raw))))
    return score, _label(score, net_return_pct)
