import random

import chess

from darwin.tournament.referee import GameResult
from darwin.tournament.runner import Standings
from darwin.tournament.selection import select_champion, select_top_n


class FakeEngine:
    def __init__(self, name: str) -> None:
        self.name = name
        self.generation = 0
        self.lineage: list[str] = []

    async def select_move(
        self, board: chess.Board, time_remaining_ms: int
    ) -> chess.Move:
        return next(iter(board.legal_moves))


def test_promotes_higher_overall_score():
    """Score-based selection: highest tournament score wins regardless of h2h."""
    incumbent = FakeEngine("inc")
    candidate = FakeEngine("cand")
    games = [
        GameResult("cand", "inc", "1-0", "checkmate", ""),
        GameResult("inc", "cand", "0-1", "checkmate", ""),
    ]
    standings = Standings(scores={"inc": 0.0, "cand": 2.0}, games=games)

    new_champion, promoted = select_champion(standings, incumbent, [candidate])

    assert new_champion is candidate
    assert promoted is True


def test_keeps_incumbent_when_score_lower_for_candidate():
    """If the incumbent outscored the candidate overall, no promotion."""
    incumbent = FakeEngine("inc")
    candidate = FakeEngine("cand")
    games = [
        GameResult("inc", "cand", "1-0", "checkmate", ""),
        GameResult("cand", "inc", "0-1", "checkmate", ""),
    ]
    standings = Standings(scores={"inc": 5.0, "cand": 1.0}, games=games)

    new_champion, promoted = select_champion(standings, incumbent, [candidate])

    assert new_champion is incumbent
    assert promoted is False


def test_random_tiebreak_picks_a_winner_on_equal_score():
    """Tied scores resolve randomly — across many trials we should see both
    sides win some of the time, never deadlock on a single one."""
    incumbent = FakeEngine("inc")
    candidate = FakeEngine("cand")
    games = [
        GameResult("inc", "cand", "1/2-1/2", "draw", ""),
        GameResult("cand", "inc", "1/2-1/2", "draw", ""),
    ]
    standings = Standings(scores={"inc": 1.0, "cand": 1.0}, games=games)

    random.seed(0)
    winners = {
        select_champion(standings, incumbent, [candidate])[0].name
        for _ in range(50)
    }

    # With 50 random tiebreak draws between two equally-scored engines,
    # the chance of all-incumbent or all-candidate is 2 / 2**50 — negligible.
    assert winners == {"inc", "cand"}


def test_select_top_n_returns_ranked_list_of_size_n():
    incumbent = FakeEngine("inc")
    a = FakeEngine("a")
    b = FakeEngine("b")
    c = FakeEngine("c")
    # Each engine plays the same number of games (round-robin), so
    # ranking by win rate matches ranking by raw score. Scores below
    # come out to {inc:1, a:4, b:2, c:3}; rates are inc:1/6, a:4/6,
    # b:2/6, c:3/6 — same ordering.
    games = [
        GameResult("a", "inc", "1-0", "checkmate", ""),
        GameResult("a", "b", "1-0", "checkmate", ""),
        GameResult("a", "c", "1-0", "checkmate", ""),
        GameResult("inc", "a", "0-1", "checkmate", ""),
        GameResult("c", "a", "0-1", "checkmate", ""),
        GameResult("c", "b", "1-0", "checkmate", ""),
        GameResult("c", "inc", "1-0", "checkmate", ""),
        GameResult("b", "c", "0-1", "checkmate", ""),
        GameResult("b", "inc", "1-0", "checkmate", ""),
        GameResult("inc", "b", "0-1", "checkmate", ""),
        GameResult("inc", "c", "1-0", "checkmate", ""),
    ]
    standings = Standings(
        scores={"inc": 1.0, "a": 4.0, "b": 2.0, "c": 3.0},
        games=games,
    )

    top = select_top_n(standings, incumbent, [a, b, c], n=2)

    assert [e.name for e in top] == ["a", "c"]


def test_select_top_n_n_one_returns_just_winner():
    incumbent = FakeEngine("inc")
    a = FakeEngine("a")
    games = [
        GameResult("a", "inc", "1-0", "checkmate", ""),
    ]
    standings = Standings(scores={"inc": 0.0, "a": 1.0}, games=games)

    top = select_top_n(standings, incumbent, [a], n=1)

    assert [e.name for e in top] == ["a"]


def test_select_champion_with_no_candidates_keeps_incumbent():
    """An empty candidate list (every builder rejected) must hold the throne."""
    incumbent = FakeEngine("inc")
    standings = Standings(scores={"inc": 0.0}, games=[])

    new_champion, promoted = select_champion(standings, incumbent, [])

    assert new_champion is incumbent
    assert promoted is False


def test_win_rate_normalizes_partial_cohorts():
    """If one engine errored out and played fewer games, win rate
    (not raw score) must drive ranking. A 2-for-2 candidate beats a
    3-for-6 incumbent on RATE even with a lower raw score."""
    incumbent = FakeEngine("inc")
    candidate = FakeEngine("cand")
    # incumbent: played 6, scored 3.0 → 0.5 rate
    # candidate: played 2, scored 2.0 → 1.0 rate
    games = [
        GameResult("inc", "x", "1-0", "checkmate", ""),
        GameResult("inc", "y", "1-0", "checkmate", ""),
        GameResult("inc", "z", "1-0", "checkmate", ""),
        GameResult("inc", "x", "0-1", "checkmate", ""),
        GameResult("inc", "y", "0-1", "checkmate", ""),
        GameResult("inc", "z", "0-1", "checkmate", ""),
        GameResult("cand", "inc", "1-0", "checkmate", ""),
        GameResult("cand", "x", "1-0", "checkmate", ""),
    ]
    standings = Standings(
        scores={"inc": 3.0, "cand": 2.0},
        games=games,
    )

    new_champion, promoted = select_champion(standings, incumbent, [candidate])
    assert new_champion is candidate
    assert promoted is True


def test_win_rate_zero_when_no_games_played():
    """A nominal incumbent who didn't appear in any game has rate 0.0,
    which lets a 1-game candidate displace them."""
    from darwin.tournament.selection import win_rate

    incumbent = FakeEngine("inc")
    standings = Standings(scores={"inc": 0.0}, games=[])
    assert win_rate(standings, "inc") == 0.0


def test_select_top_n_clamps_n_to_at_least_1():
    """n=0 is treated as n=1 — the orchestrator never wants an empty top-N."""
    incumbent = FakeEngine("inc")
    a = FakeEngine("a")
    standings = Standings(
        scores={"inc": 0.0, "a": 1.0},
        games=[GameResult("a", "inc", "1-0", "checkmate", "")],
    )

    top = select_top_n(standings, incumbent, [a], n=0)
    assert len(top) == 1


def test_select_top_n_n_larger_than_pool_returns_full_pool():
    """Asking for top-10 of a 3-engine pool returns all 3, not crashes."""
    incumbent = FakeEngine("inc")
    a = FakeEngine("a")
    b = FakeEngine("b")
    games = [
        GameResult("a", "inc", "1-0", "checkmate", ""),
        GameResult("b", "inc", "1-0", "checkmate", ""),
        GameResult("a", "b", "1-0", "checkmate", ""),
    ]
    standings = Standings(
        scores={"inc": 0.0, "a": 2.0, "b": 1.0},
        games=games,
    )

    top = select_top_n(standings, incumbent, [a, b], n=10)
    assert len(top) == 3
    # Highest-rate engine is at the front.
    assert top[0].name == "a"


def test_promotion_requires_strict_higher_rank_not_just_appearance():
    """Even a candidate with score == incumbent must beat them on the
    random tiebreak to promote — otherwise the throne holds. We can't
    deterministically test the random outcome here, but we CAN assert
    that the result is one of the two and `promoted` matches whoever
    won."""
    random.seed(1)
    incumbent = FakeEngine("inc")
    candidate = FakeEngine("cand")
    games = [
        GameResult("inc", "cand", "1/2-1/2", "draw", ""),
        GameResult("cand", "inc", "1/2-1/2", "draw", ""),
    ]
    standings = Standings(scores={"inc": 1.0, "cand": 1.0}, games=games)

    new_champion, promoted = select_champion(standings, incumbent, [candidate])
    assert new_champion.name in {"inc", "cand"}
    assert promoted == (new_champion.name == "cand")
