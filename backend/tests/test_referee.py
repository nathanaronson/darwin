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
