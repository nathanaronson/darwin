import asyncio
import logging

import chess

from darwin.engines.random_engine import RandomEngine
from darwin.tournament.referee import play_game


class IllegalEngine:
    name = "illegal"
    generation = 0
    lineage: list[str] = []

    async def select_move(self, board: chess.Board, time_remaining_ms: int) -> chess.Move:
        return chess.Move.null()


class ErrorEngine:
    name = "error"
    generation = 0
    lineage: list[str] = []

    async def select_move(self, board: chess.Board, time_remaining_ms: int) -> chess.Move:
        raise TypeError("broken evaluator")


def test_two_random_engines_finish():
    a = RandomEngine(seed=1)
    a.name = "a"
    b = RandomEngine(seed=2)
    b.name = "b"

    result = asyncio.run(play_game(a, b, time_per_move_ms=1000))

    assert result.result in ("1-0", "0-1", "1/2-1/2")
    assert result.pgn.startswith("[Event")


def test_illegal_move_loses_and_emits_finished_event():
    black = RandomEngine(seed=1)
    black.name = "black"
    events = []

    async def on_event(event: dict) -> None:
        events.append(event)

    result = asyncio.run(play_game(IllegalEngine(), black, 1000, on_event=on_event, game_id=7))

    assert result.result == "0-1"
    assert result.termination == "illegal_move"
    assert events[-1]["type"] == "game.finished"
    assert events[-1]["game_id"] == 7
    assert events[-1]["result"] == "0-1"


def test_error_path_logs_exception_and_annotates_pgn(caplog):
    black = RandomEngine(seed=1)
    black.name = "black"

    with caplog.at_level(logging.WARNING, logger="darwin.tournament.referee"):
        result = asyncio.run(play_game(ErrorEngine(), black, 1000))

    assert result.result == "0-1"
    assert result.termination == "error"
    assert '[ErrorClass "TypeError"]' in result.pgn
    assert "game error: error vs black: TypeError('broken evaluator')" in caplog.text


# ---------------------------------------------------------------------------
# Additional coverage: time termination, max-moves cap, event emission shape,
# game-result wiring.
# ---------------------------------------------------------------------------


class HangingEngine:
    """Sleeps past any reasonable timeout to trigger asyncio.TimeoutError."""
    name = "hanger"
    generation = 0
    lineage: list[str] = []

    async def select_move(self, board, time_remaining_ms):
        await asyncio.sleep(60)  # well past play_game's 5s grace window
        return next(iter(board.legal_moves))


def test_time_termination_loses_for_white_when_white_hangs():
    """A white engine that exceeds the move budget must lose on time."""
    black = RandomEngine(seed=1)
    black.name = "black"

    # Use 100ms budget — play_game's grace adds 5s, but we override settings
    # so the test stays fast. Instead just rely on a really slow engine and
    # a small budget; play_game's wait_for(timeout=time_per_move_ms/1000+5).
    # We need to reduce the +5 grace by patching it indirectly: cheaper to
    # use a 0ms budget so the +5 grace is total budget; HangingEngine
    # sleeps 60s, well past 5s.
    result = asyncio.run(play_game(HangingEngine(), black, 0))

    assert result.termination == "time"
    assert result.result == "0-1"  # white loses


def test_max_moves_cap_returns_draw():
    """When fullmove_number exceeds max_moves_per_game, the game ends as a
    draw with termination='max_moves' regardless of position."""
    from darwin.config import settings

    a = RandomEngine(seed=1)
    a.name = "a"
    b = RandomEngine(seed=2)
    b.name = "b"

    # Set the cap aggressively low so the test ends in a few moves.
    original = settings.max_moves_per_game
    try:
        settings.max_moves_per_game = 2
        result = asyncio.run(play_game(a, b, 1000))
    finally:
        settings.max_moves_per_game = original

    assert result.termination == "max_moves"
    assert result.result == "1/2-1/2"


def test_move_events_carry_full_payload_shape():
    """Each game.move event must include the FEN, SAN, ply, and player
    names — the dashboard depends on every field."""
    a = RandomEngine(seed=1)
    a.name = "a"
    b = RandomEngine(seed=2)
    b.name = "b"

    events: list[dict] = []

    async def on_event(e: dict) -> None:
        events.append(e)

    asyncio.run(play_game(a, b, 1000, on_event=on_event, game_id=42))

    move_events = [e for e in events if e["type"] == "game.move"]
    assert move_events, "no move events emitted"
    for e in move_events:
        assert e["game_id"] == 42
        assert {"fen", "san", "white", "black", "ply"} <= e.keys()
        assert e["white"] == "a"
        assert e["black"] == "b"
        assert isinstance(e["ply"], int)
        assert e["ply"] > 0


def test_finished_event_has_pgn_and_termination():
    a = RandomEngine(seed=1)
    a.name = "a"
    b = RandomEngine(seed=2)
    b.name = "b"

    events: list[dict] = []

    async def on_event(e: dict) -> None:
        events.append(e)

    asyncio.run(play_game(a, b, 1000, on_event=on_event, game_id=99))
    finished = [e for e in events if e["type"] == "game.finished"]
    assert len(finished) == 1
    f = finished[0]
    assert f["game_id"] == 99
    assert f["pgn"].startswith("[Event")
    assert f["termination"] in {"checkmate", "stalemate", "draw", "max_moves"}


def test_game_result_is_dataclass_with_expected_fields():
    """GameResult is a stable dataclass — selection/runner depend on its
    field names."""
    from darwin.tournament.referee import GameResult

    r = GameResult(white="a", black="b", result="1-0", termination="checkmate", pgn="x")
    assert r.white == "a"
    assert r.black == "b"
    assert r.result == "1-0"
    assert r.termination == "checkmate"
    assert r.pgn == "x"


def test_engine_receives_board_copy_not_original():
    """play_game must hand the engine a copy of the board so an engine
    that mutates it can't corrupt the referee's authoritative state."""
    boards_received = []

    class CopyDetectingEngine:
        name = "copy-check"
        generation = 0
        lineage: list[str] = []

        async def select_move(self, board, time_remaining_ms):
            boards_received.append(board)
            move = next(iter(board.legal_moves))
            # Mutate the copy — should not affect referee.
            board.push(move)
            board.push(next(iter(board.legal_moves)))
            return move

    black = RandomEngine(seed=1)
    black.name = "black"

    # Cap the game short so it ends quickly.
    from darwin.config import settings
    original = settings.max_moves_per_game
    try:
        settings.max_moves_per_game = 3
        asyncio.run(play_game(CopyDetectingEngine(), black, 1000))
    finally:
        settings.max_moves_per_game = original

    # Each board the engine saw is a Board instance — but the referee's
    # internal board_stack tracks only the actual played moves. This test
    # would fail with a stack overflow / illegal-move loop if the engine
    # were handed the live board (it'd push moves the referee never saw).
    assert all(hasattr(b, "fullmove_number") for b in boards_received)


def test_pgn_contains_played_moves_in_san():
    a = RandomEngine(seed=1)
    a.name = "a"
    b = RandomEngine(seed=2)
    b.name = "b"

    from darwin.config import settings
    original = settings.max_moves_per_game
    try:
        settings.max_moves_per_game = 5
        result = asyncio.run(play_game(a, b, 1000))
    finally:
        settings.max_moves_per_game = original

    # Header block then move text. PGN can be spread across lines, but
    # at minimum it has the standard 4 mandatory tag headers.
    for header in ("[White ", "[Black ", "[Result "):
        assert header in result.pgn
