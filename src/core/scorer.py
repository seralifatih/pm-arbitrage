from typing import Optional


def _net_spread_points(net_spread_pct: float) -> float:
    """Linear 0% → 0 pts, 5%+ → 40 pts. Clamp at both ends."""
    if net_spread_pct <= 0:
        return 0.0
    if net_spread_pct >= 5.0:
        return 40.0
    return (net_spread_pct / 5.0) * 40.0


def _liquidity_points(fillable: Optional[bool]) -> float:
    if fillable is True:
        return 25.0
    if fillable is False:
        return 0.0
    return 12.0  # None/unknown → partial credit


def _match_confidence_points(match_confidence: int) -> float:
    """Scale 0–100 match_confidence to 0–20 pts."""
    return (max(0, min(100, match_confidence)) / 100.0) * 20.0


def _days_points(days_to_resolution: int) -> float:
    if days_to_resolution < 0:
        return 0.0
    if days_to_resolution <= 30:
        return 15.0
    if days_to_resolution <= 90:
        return 7.0
    return 0.0


def _label(score: int, net_spread_pct: float) -> str:
    if score >= 80 and net_spread_pct > 0:
        return "Pure arbitrage"
    if score >= 80:
        return "Strong EV+ signal"
    if score >= 60:
        return "Strong EV+ signal"
    if score >= 40:
        return "EV+ with edge"
    return "Marginal"


def score_opportunity(
    gross_spread_pct: float,
    net_spread_pct: float,
    fillable: Optional[bool],
    match_confidence: int,
    days_to_resolution: int,
) -> tuple[int, str]:
    raw = (
        _net_spread_points(net_spread_pct)
        + _liquidity_points(fillable)
        + _match_confidence_points(match_confidence)
        + _days_points(days_to_resolution)
    )
    score = int(round(max(0.0, min(100.0, raw))))
    return score, _label(score, net_spread_pct)
