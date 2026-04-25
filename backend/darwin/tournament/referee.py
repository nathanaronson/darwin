"""Play one game between two engines.

Handles legal-move check, time control, max-move cap, error adjudication,
and PGN serialization. Emits game.move and game.finished events as it goes.
See plans/person-b-tournament.md.
"""

from __future__ import annotations

import asyncio
import io
import logging
from dataclasses import dataclass
from typing import Awaitable, Callable

import chess
import chess.pgn

from darwin.config import settings
from darwin.engines.base import Engine

EventCb = Callable[[dict], Awaitable[None]] | None
log = logging.getLogger(__name__)


@dataclass
class GameResult:
    white: str
    black: str
    result: str  # "1-0" | "0-1" | "1/2-1/2"
    termination: str  # "checkmate" | "stalemate" | "time" | "max_moves" | "error"
    pgn: str


def _to_pgn(
    board: chess.Board,
    white: str,
    black: str,
    result: str,
    extra_headers: dict[str, str] | None = None,
) -> str:
    game = chess.pgn.Game()
    game.headers["White"] = white
    game.headers["Black"] = black
    game.headers["Result"] = result
    for key, value in (extra_headers or {}).items():
        game.headers[key] = value

    node = game
    for move in board.move_stack:
        node = node.add_variation(move)

    out = io.StringIO()
    print(game, file=out)
    return out.getvalue()


def _loss_result(loser_is_white: bool) -> str:
    return "0-1" if loser_is_white else "1-0"


def _game_over_termination(board: chess.Board) -> str:
    if board.is_checkmate():
        return "checkmate"
    if board.is_stalemate():
        return "stalemate"
    return "draw"


async def _finish(
    board: chess.Board,
    white: str,
    black: str,
    result: str,
    termination: str,
    on_event: EventCb,
    game_id: int,
    extra_headers: dict[str, str] | None = None,
) -> GameResult:
    pgn = _to_pgn(board, white, black, result, extra_headers)
    if on_event:
        await on_event(
            {
                "type": "game.finished",
                "game_id": game_id,
                "result": result,
                "termination": termination,
                "pgn": pgn,
                "white": white,
                "black": black,
            }
        )
    return GameResult(white=white, black=black, result=result, termination=termination, pgn=pgn)


async def play_game(
    white: Engine,
    black: Engine,
    time_per_move_ms: int,
    on_event: EventCb = None,
    game_id: int = 0,
) -> GameResult:
    board = chess.Board()
    # Allow provider/network jitter beyond the requested engine budget without
    # letting one stalled move block the tournament indefinitely.
    timeout_s = (time_per_move_ms / 1000) + 5

    while not board.is_game_over(claim_draw=True):
        if board.fullmove_number > settings.max_moves_per_game:
            return await _finish(
                board,
                white.name,
                black.name,
                "1/2-1/2",
                "max_moves",
                on_event,
                game_id,
            )

        engine = white if board.turn == chess.WHITE else black
        loser_is_white = board.turn == chess.WHITE

        try:
            move = await asyncio.wait_for(
                engine.select_move(board.copy(), time_per_move_ms),
                timeout=timeout_s,
            )
        except asyncio.TimeoutError:
            return await _finish(
                board,
                white.name,
                black.name,
                _loss_result(loser_is_white),
                "time",
                on_event,
                game_id,
            )
        except Exception as exc:
            log.warning("game error: %s vs %s: %r", white.name, black.name, exc)
            return await _finish(
                board,
                white.name,
                black.name,
                _loss_result(loser_is_white),
                "error",
                on_event,
                game_id,
                {"ErrorClass": type(exc).__name__},
            )

        if move not in board.legal_moves:
            return await _finish(
                board,
                white.name,
                black.name,
                _loss_result(loser_is_white),
                "illegal_move",
                on_event,
                game_id,
            )

        san = board.san(move)
        board.push(move)
        if on_event:
            await on_event(
                {
                    "type": "game.move",
                    "game_id": game_id,
                    "fen": board.fen(),
                    "san": san,
                    "white": white.name,
                    "black": black.name,
                    "ply": board.ply(),
                }
            )

    return await _finish(
        board,
        white.name,
        black.name,
        board.result(claim_draw=True),
        _game_over_termination(board),
        on_event,
        game_id,
    )
