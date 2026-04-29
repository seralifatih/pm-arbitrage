"""Classifier acceptance tests using the actual false positives from
live Polymarket data on 2026-04-28. Every event the v0.2.0 scanner
incorrectly flagged as 'Pure arbitrage' must now classify as NOT_ARB.

Plus positive cases: real winner-take-all and top-K events must
classify correctly.
"""
from src.core.event_classifier import EventType, classify_event


# ---------------------------------------------------------------------------
# REJECT: cumulative "by date" events — outcomes are nested, not exclusive
# ---------------------------------------------------------------------------

class TestRejectsCumulativeByDate:
    def test_drake_iceman_release(self):
        et, _ = classify_event(
            "Will Drake release Iceman by...?",
            [
                "Will Drake officially release Iceman by April 30, 2026?",
                "Will Drake officially release Iceman by May 31, 2026?",
                "Will Drake officially release Iceman by June 30, 2026?",
            ],
            ["April 30", "May 31", "June 30"],
        )
        assert et == EventType.NOT_ARB

    def test_internet_iran(self):
        et, _ = classify_event(
            "Internet Access restored in Iran by...?",
            [
                "Internet Access restored in Iran by April 30, 2026?",
                "Internet Access restored in Iran by May 31, 2026?",
                "Internet Access restored in Iran by June 30, 2026?",
            ],
            ["April 30", "May 31", "June 30"],
        )
        assert et == EventType.NOT_ARB

    def test_trump_visit_china(self):
        et, _ = classify_event(
            "Will Trump visit China by...?",
            [
                "Will Trump visit China by May 31?",
                "Will Trump visit China by June 30?",
                "Will Trump visit China by May 8?",
                "Will Trump visit China by May 15?",
            ],
            ["May 31", "June 30", "May 8", "May 15"],
        )
        assert et == EventType.NOT_ARB

    def test_powell_out_as_fed_chair(self):
        et, _ = classify_event(
            "Jerome Powell out as Fed Chair by...?",
            [
                "Jerome Powell out as Fed Chair by May 14, 2026?",
                "Jerome Powell out as Fed Chair by May 31, 2026?",
                "Jerome Powell out as Fed Chair by June 30, 2026?",
            ],
            ["May 14", "May 31", "June 30"],
        )
        assert et == EventType.NOT_ARB

    def test_dhs_shutdown_duration(self):
        et, _ = classify_event(
            "How long will the DHS shutdown last?",
            [
                "Will the DHS shutdown last 80 days or more?",
                "Will the DHS shutdown last 90 days or more?",
                "Will the DHS shutdown last 110 days or more?",
                "Will the DHS shutdown last 120 days or more?",
            ],
            ["80+ days", "90+ days", "110+ days", "120+ days"],
        )
        assert et == EventType.NOT_ARB


# ---------------------------------------------------------------------------
# REJECT: price ladders / threshold structures
# ---------------------------------------------------------------------------

class TestRejectsPriceLadders:
    def test_solana_price_arrows(self):
        et, _ = classify_event(
            "What price will Solana hit in April?",
            [
                "Will Solana reach $110 in April?",
                "Will Solana dip to $70 in April?",
                "Will Solana reach $100 in April?",
            ],
            ["↑ 110", "↓ 70", "↑ 100"],
        )
        assert et == EventType.NOT_ARB

    def test_xrp_price_ladder(self):
        et, _ = classify_event(
            "What price will XRP hit in April?",
            [
                "Will XRP reach $2.60 in April?",
                "Will XRP reach $1.60 in April?",
                "Will XRP reach $1.80 in April?",
                "Will XRP dip to $1.20 in April?",
            ],
            ["↑ 2.60", "↑ 1.60", "↑ 1.80", "↓ 1.20"],
        )
        assert et == EventType.NOT_ARB

    def test_strait_of_hormuz_threshold(self):
        et, _ = classify_event(
            "Will __ ships transit the Strait of Hormuz on any day by end of April?",
            [
                "Will 80 ships transit the Strait of Hormuz on any day by April 30?",
                "Will 60 ships transit the Strait of Hormuz on any day by April 30?",
                "Will 40 ships transit the Strait of Hormuz on any day by April 30?",
            ],
            ["80+", "60+", "40+"],
        )
        assert et == EventType.NOT_ARB

    def test_oil_reserves_threshold(self):
        et, _ = classify_event(
            "Will US crude oil reserves fall to __ by May 1?",
            [
                "Will US crude oil reserves fall to 300M by May 1?",
                "Will US crude oil reserves fall to 375M by May 1?",
                "Will US crude oil reserves fall to 250M by May 1?",
            ],
            ["300M", "375M", "250M"],
        )
        assert et == EventType.NOT_ARB

    def test_temperature_threshold(self):
        et, _ = classify_event(
            "Highest temperature in Toronto on April 28?",
            [
                "Will the highest temperature in Toronto be 17°C on April 28?",
                "Will the highest temperature in Toronto be 18°C on April 28?",
                "Will the highest temperature in Toronto be 19°C or higher on April 28?",
            ],
            ["17°C", "18°C", "19°C or higher"],
        )
        assert et == EventType.NOT_ARB


# ---------------------------------------------------------------------------
# REJECT: independent / multi-condition events
# ---------------------------------------------------------------------------

class TestRejectsIndependent:
    def test_what_will_trump_agree_to(self):
        et, _ = classify_event(
            "What Iranian demands will Trump agree to in April?",
            [
                "Will Trump agree to Iranian Oil sanction relief in April?",
                "Will Trump agree to Iranian transit fees in the Strait of Hormuz in April?",
                "Will Trump agree to unfreeze Iranian assets in April?",
            ],
            ["Oil Sanction Relief", "Transit Fees", "Unfreeze Iranian Assets"],
        )
        assert et == EventType.NOT_ARB

    def test_player_props_o_u(self):
        et, _ = classify_event(
            "Magic vs. Pistons",
            [
                "Franz Wagner: Points O/U 17.5",
                "Franz Wagner: Rebounds O/U 4.5",
                "Franz Wagner: Assists O/U 3.5",
            ],
            ["Franz Wagner: Points O/U 17.5", "Rebounds O/U 4.5", "Assists O/U 3.5"],
        )
        assert et == EventType.NOT_ARB

    def test_trump_insult_by_date(self):
        et, _ = classify_event(
            "Will Trump publicly insult someone on...?",
            [
                "Will Donald Trump publicly insult someone on April 26, 2026?",
                "Will Donald Trump publicly insult someone on April 28, 2026?",
                "Will Donald Trump publicly insult someone on April 29, 2026?",
                "Will Donald Trump publicly insult someone on April 30, 2026?",
            ],
            ["April 26", "April 28", "April 29", "April 30"],
        )
        # Each date is independent — Trump can insult on multiple days.
        assert et == EventType.NOT_ARB

    def test_spacex_starship_independent_questions(self):
        et, _ = classify_event(
            "SpaceX Starship Flight Test 12",
            [
                "Will SpaceX Starship Flight Test 12 Superheavy explode?",
                "Will the Starship achieve a successful splashdown?",
                "Will the chopsticks catch Superheavy booster?",
                "Will SpaceX Starship Flight Test 12 launch by April 30?",
            ],
            ["Super Heavy explodes?", "Successful splash down?", "Chopsticks catch?", "April 30"],
        )
        # Different questions on the same launch — independent outcomes.
        assert et == EventType.NOT_ARB


# ---------------------------------------------------------------------------
# ACCEPT: top-K events
# ---------------------------------------------------------------------------

class TestAcceptsTopK:
    def test_serie_a_top_4(self):
        et, k = classify_event(
            "Serie A - Top 4 Finish ",
            [f"Will {team} finish in the top 4 in the 2025-26 Serie A season?"
             for team in ["Napoli", "Atalanta", "AC Milan", "Roma", "Como"]],
            ["Napoli", "Atalanta", "AC Milan", "Roma", "Como"],
        )
        assert et == EventType.TOP_K
        assert k == 4

    def test_champions_league_reach_final(self):
        et, k = classify_event(
            "UEFA Champions League: Team to reach final",
            [
                "Will Paris Saint-Germain (PSG) reach the UEFA Champions League final?",
                "Will Arsenal reach the UEFA Champions League final?",
                "Will Bayern München reach the UEFA Champions League final?",
                "Will Atlético Madrid reach the UEFA Champions League final?",
            ],
            ["PSG", "Arsenal", "Bayern München", "Atlético Madrid"],
        )
        assert et == EventType.TOP_K
        assert k == 2


# ---------------------------------------------------------------------------
# ACCEPT: winner-take-all events
# ---------------------------------------------------------------------------

class TestAcceptsWinnerTakeAll:
    def test_democratic_nominee_2028(self):
        et, k = classify_event(
            "Democratic Presidential Nominee 2028",
            [f"Will {n} win the 2028 Democratic presidential nomination?"
             for n in ["Buttigieg", "Whitmer", "Ossoff"]],
            ["Buttigieg", "Whitmer", "Ossoff"],
        )
        assert et == EventType.WINNER_TAKE_ALL
        assert k == 1.0

    def test_nba_finals_winner(self):
        et, k = classify_event(
            "NBA Finals Winner 2026",
            ["Will the Lakers win the 2026 NBA Finals?",
             "Will the Celtics win the 2026 NBA Finals?",
             "Will the Warriors win the 2026 NBA Finals?"],
            ["Lakers", "Celtics", "Warriors"],
        )
        assert et == EventType.WINNER_TAKE_ALL
        assert k == 1.0

    def test_next_pope(self):
        et, k = classify_event(
            "Who will be the next Pope?",
            ["Will Cardinal X be the next Pope?", "Will Cardinal Y be the next Pope?"],
            ["Cardinal X", "Cardinal Y"],
        )
        assert et == EventType.WINNER_TAKE_ALL
        assert k == 1.0
