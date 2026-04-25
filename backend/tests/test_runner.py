import asyncio

import pytest

from darwin.config import settings
from darwin.engines.random_engine import RandomEngine
from darwin.tournament.referee import GameResult
from darwin.tournament.runner import round_robin


@pytest.fixture(autouse=True)
def _force_local_backend(monkeypatch):
    """Tests in this file exercise the local asyncio path. The .env may
    set ``TOURNAMENT_BACKEND=modal`` for the dev server; force-override
    to ``local`` so the tests don't try to dispatch to Modal."""
    monkeypatch.setattr(settings, "tournament_backend", "local")


def test_round_robin_4_engines():
    engines = [RandomEngine(seed=i) for i in range(4)]
    for i, engine in enumerate(engines):
        engine.name = f"r{i}"

    standings = asyncio.run(round_robin(engines, games_per_pairing=1, time_per_move_ms=1000))

    expected_games = 4 * 3
    assert len(standings.games) == expected_games
    assert sum(standings.scores.values()) == expected_games
    assert set(standings.scores) == {"r0", "r1", "r2", "r3"}


def test_round_robin_rejects_negative_games_per_pairing():
    with pytest.raises(ValueError):
        asyncio.run(round_robin([], games_per_pairing=-1, time_per_move_ms=1000))


@pytest.mark.asyncio
async def test_round_robin_caps_in_flight_games(monkeypatch):
    current = 0
    max_seen = 0

    async def fake_play_game(white, black, time_per_move_ms, on_event=None, game_id=0):
        nonlocal current, max_seen
        current += 1
        max_seen = max(max_seen, current)
        await asyncio.sleep(0.01)
        current -= 1
        return GameResult(white.name, black.name, "1/2-1/2", "draw", "")

    import darwin.tournament.runner as runner

    monkeypatch.setattr(runner, "play_game", fake_play_game)
    monkeypatch.setattr(runner.settings, "max_parallel_games", 2)

    engines = [RandomEngine(seed=i) for i in range(4)]
    for i, engine in enumerate(engines):
        engine.name = f"r{i}"

    standings = await round_robin(engines, games_per_pairing=1, time_per_move_ms=1000)

    assert len(standings.games) == 12
    assert max_seen == 2


@pytest.mark.asyncio
async def test_pairings_skip_self_play():
    """An engine never plays itself — verify by inspecting the pairings list."""
    from darwin.tournament.runner import _build_pairings

    engines = [RandomEngine(seed=i) for i in range(3)]
    for i, e in enumerate(engines):
        e.name = f"r{i}"

    pairings = _build_pairings(engines, games_per_pairing=1)

    for white, black, _ in pairings:
        assert white.name != black.name


@pytest.mark.asyncio
async def test_pairings_count_scales_correctly():
    """N engines × games_per_pairing → N*(N-1)*games_per_pairing total games.
    Every ordered pair (white, black) plays games_per_pairing games."""
    from darwin.tournament.runner import _build_pairings

    engines = [RandomEngine(seed=i) for i in range(4)]
    for i, e in enumerate(engines):
        e.name = f"r{i}"

    assert len(_build_pairings(engines, games_per_pairing=1)) == 4 * 3
    assert len(_build_pairings(engines, games_per_pairing=2)) == 4 * 3 * 2
    assert len(_build_pairings(engines, games_per_pairing=5)) == 4 * 3 * 5


@pytest.mark.asyncio
async def test_pairings_assign_unique_game_ids():
    """game_id must be unique across the whole tournament — the dashboard
    keys live boards on it."""
    from darwin.tournament.runner import _build_pairings

    engines = [RandomEngine(seed=i) for i in range(3)]
    for i, e in enumerate(engines):
        e.name = f"r{i}"

    pairings = _build_pairings(engines, games_per_pairing=2)
    game_ids = [gid for _, _, gid in pairings]
    assert len(set(game_ids)) == len(game_ids)
    assert sorted(game_ids) == list(range(len(game_ids)))


@pytest.mark.asyncio
async def test_tally_credits_wins_to_white_on_one_zero():
    from darwin.tournament.runner import _tally

    engines = [RandomEngine(seed=i) for i in range(2)]
    engines[0].name = "a"
    engines[1].name = "b"
    results = [GameResult("a", "b", "1-0", "checkmate", "")]
    s = _tally(engines, results)
    assert s.scores["a"] == 1.0
    assert s.scores["b"] == 0.0


@pytest.mark.asyncio
async def test_tally_credits_wins_to_black_on_zero_one():
    from darwin.tournament.runner import _tally

    engines = [RandomEngine(seed=i) for i in range(2)]
    engines[0].name = "a"
    engines[1].name = "b"
    results = [GameResult("a", "b", "0-1", "checkmate", "")]
    s = _tally(engines, results)
    assert s.scores["a"] == 0.0
    assert s.scores["b"] == 1.0


@pytest.mark.asyncio
async def test_tally_splits_draws_half_half():
    from darwin.tournament.runner import _tally

    engines = [RandomEngine(seed=i) for i in range(2)]
    engines[0].name = "a"
    engines[1].name = "b"
    results = [GameResult("a", "b", "1/2-1/2", "draw", "")]
    s = _tally(engines, results)
    assert s.scores["a"] == 0.5
    assert s.scores["b"] == 0.5


@pytest.mark.asyncio
async def test_tally_includes_engines_with_zero_score():
    """An engine that played no games (or lost them all on zero-credit
    paths) still appears in `scores` at 0.0 — selection treats missing
    keys differently."""
    from darwin.tournament.runner import _tally

    engines = [RandomEngine(seed=i) for i in range(3)]
    for i, e in enumerate(engines):
        e.name = f"r{i}"
    results = [GameResult("r0", "r1", "1-0", "checkmate", "")]

    s = _tally(engines, results)
    assert "r2" in s.scores
    assert s.scores["r2"] == 0.0


@pytest.mark.asyncio
async def test_warm_modal_pool_is_noop_on_local(monkeypatch):
    """warm_modal_pool must be safe to call when backend != modal — the
    orchestrator calls it unconditionally at gen start."""
    import darwin.tournament.runner as runner_mod
    monkeypatch.setattr(runner_mod.settings, "tournament_backend", "local")

    # Should return immediately, no exception, no modal import attempted.
    await runner_mod.warm_modal_pool(20)


@pytest.mark.asyncio
async def test_cool_modal_pool_is_noop_on_local(monkeypatch):
    import darwin.tournament.runner as runner_mod
    monkeypatch.setattr(runner_mod.settings, "tournament_backend", "local")

    await runner_mod.cool_modal_pool()


@pytest.mark.asyncio
async def test_round_robin_single_engine_returns_empty_standings(monkeypatch):
    """Edge case: one engine = no pairings = empty result, scores dict
    still contains that engine at 0.0."""
    import darwin.tournament.runner as runner

    eng = RandomEngine(seed=0)
    eng.name = "lonely"

    standings = await runner.round_robin(
        [eng], games_per_pairing=1, time_per_move_ms=1000
    )
    assert standings.games == []
    assert standings.scores == {"lonely": 0.0}


@pytest.mark.asyncio
async def test_round_robin_zero_games_per_pairing_returns_empty(monkeypatch):
    """0 games per pairing should still produce a valid Standings shape
    and not raise — selection handles empty cohorts."""
    import darwin.tournament.runner as runner

    engines = [RandomEngine(seed=i) for i in range(3)]
    for i, e in enumerate(engines):
        e.name = f"r{i}"

    standings = await runner.round_robin(
        engines, games_per_pairing=0, time_per_move_ms=1000
    )
    assert standings.games == []
    assert set(standings.scores) == {"r0", "r1", "r2"}
    assert all(v == 0.0 for v in standings.scores.values())
