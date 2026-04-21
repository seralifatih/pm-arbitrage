FEE_POLYMARKET = 0.02
FEE_KALSHI = 0.07
FEE_MANIFOLD = 0.0
FEE_MYRIAD = 0.02

VENUE_FEES: dict[str, float] = {
    "polymarket": FEE_POLYMARKET,
    "kalshi": FEE_KALSHI,
    "manifold": FEE_MANIFOLD,
    "myriad": FEE_MYRIAD,
}


def calculate_spread(
    yes_price: float,
    no_price: float,
    venue_a: str,
    venue_b: str,
) -> dict[str, float]:
    gross_spread_pct = (1.0 - yes_price - no_price) / (yes_price + no_price) * 100
    fees_pct = (VENUE_FEES[venue_a] + VENUE_FEES[venue_b]) * 100
    net_spread_pct = gross_spread_pct - fees_pct
    return {
        "gross_spread_pct": round(gross_spread_pct, 4),
        "fees_pct": round(fees_pct, 4),
        "net_spread_pct": round(net_spread_pct, 4),
    }
