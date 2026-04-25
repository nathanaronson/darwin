"""Champion selection — win-rate based.

Each generation's tournament produces a ``Standings`` with per-engine
score (wins + 0.5*draws). We rank everyone by **win rate** (score /
games_played) and #1 becomes the new champion. Ties resolve randomly.

Why win rate, not Elo: Elo is a noisy per-game update that depends on
the opponent's prior rating — across 5-10 games per cohort, Elo drifts
in ways that don't reliably reflect this gen's actual head-to-head
performance. Win rate is the simple, transparent thing: "how often did
you beat the field?". Elo is still computed and persisted for the
dashboard chart, but it never feeds back into selection.

Why win rate, not raw score: in a clean round-robin every engine plays
the same number of games and the two metrics give identical orderings.
But if a game errors out, one engine is short a game — raw score
penalizes them, win rate does not. Using rate keeps selection robust
to partial cohorts.

The previous head-to-head gate ("candidate must beat incumbent in their
direct subset") was discarded earlier — with 4 candidates per cohort
and only 2 head-to-head games per pair, that gate had high enough
variance to lock the demo on baseline indefinitely. Tournament-wide
win rate is a more stable signal.

``select_top_n`` returns the top N engines (default 2) so the orchestrator
can carry the runner-up forward as a second incumbent in the next gen —
giving the strategist+builder more genetic diversity to work with.
"""

import random

from darwin.engines.base import Engine
from darwin.tournament.runner import Standings


def win_rate(standings: Standings, name: str) -> float:
    """Score / games_played for ``name``. Returns 0.0 if it played nothing."""
    games_played = sum(
        1 for g in standings.games if g.white == name or g.black == name
    )
    if games_played == 0:
        return 0.0
    return standings.scores.get(name, 0.0) / games_played


def _ranked_engines(
    standings: Standings, engines: list[Engine]
) -> list[Engine]:
    """Sort engines by win rate descending, with random tiebreak."""
    # ``random.random()`` per key call is the standard "shuffle ties" trick.
    # The negative rate makes desc-order via the natural ascending sort.
    return sorted(
        engines,
        key=lambda e: (-win_rate(standings, e.name), random.random()),
    )


def select_champion(
    standings: Standings,
    incumbent: Engine,
    candidates: list[Engine],
) -> tuple[Engine, bool]:
    """Returns ``(new_champion, promoted)``.

    Highest win rate wins; ties are resolved randomly (so a flat
    "everyone went 50%" round still picks someone). ``promoted`` is True
    iff the winner is not the incumbent.
    """
    if not candidates:
        return incumbent, False
    ranked = _ranked_engines(standings, [incumbent, *candidates])
    winner = ranked[0]
    return winner, winner.name != incumbent.name


def select_top_n(
    standings: Standings,
    incumbent: Engine,
    candidates: list[Engine],
    n: int = 2,
) -> list[Engine]:
    """Return the top-N engines by win rate across ``[incumbent, *candidates]``.

    The first element is the new champion; subsequent elements are the
    runners-up that the orchestrator will carry into the next generation
    as additional incumbents. ``n`` defaults to 2 because the demo loop
    benchmarks "top-2 forward" — bumping it higher widens the round-
    robin quadratically (engines × games_per_pairing) and is rarely
    worth it.
    """
    pool = [incumbent, *candidates]
    if not pool:
        return []
    ranked = _ranked_engines(standings, pool)
    return ranked[: max(1, n)]
