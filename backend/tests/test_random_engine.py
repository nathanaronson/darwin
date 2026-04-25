"""Tests for darwin.engines.random_engine.RandomEngine.

The random engine is the cheap test partner for referee/runner/builder
validation paths. Tests guard:

  - It returns a legal move from any non-terminal position.
  - Seeded instances are deterministic across constructions (reproducible
    test fixtures depend on this).
  - Different seeds produce different move sequences with high probability.
  - The Engine Protocol shape (name/generation/lineage) is intact.
"""

from __future__ import annotations

import asyncio

import chess
import pytest

from darwin.engines.base import Engine
from darwin.engines.random_engine import RandomEngine, engine as module_engine


@pytest.mark.asyncio
async def test_returns_legal_move_from_starting_position():
    eng = RandomEngine(seed=0)
    move = await eng.select_move(chess.Board(), 1000)
    assert move in chess.Board().legal_moves


@pytest.mark.asyncio
async def test_returns_chess_move_type():
    eng = RandomEngine(seed=0)
    move = await eng.select_move(chess.Board(), 1000)
    assert isinstance(move, chess.Move)


@pytest.mark.asyncio
async def test_returns_legal_move_from_endgame_position():
    """K+R vs K — only a few legal moves; result must be one of them."""
    board = chess.Board("8/8/8/8/8/3k4/3R4/3K4 w - - 0 1")
    eng = RandomEngine(seed=42)
    move = await eng.select_move(board, 1000)
    assert move in board.legal_moves


@pytest.mark.asyncio
async def test_seeded_engines_are_deterministic():
    """Same seed → same move sequence, run-to-run."""
    a = RandomEngine(seed=123)
    b = RandomEngine(seed=123)

    board_a = chess.Board()
    board_b = chess.Board()
    moves_a: list[chess.Move] = []
    moves_b: list[chess.Move] = []
    for _ in range(20):
        if board_a.is_game_over() or board_b.is_game_over():
            break
        ma = await a.select_move(board_a, 1000)
        mb = await b.select_move(board_b, 1000)
        moves_a.append(ma)
        moves_b.append(mb)
        board_a.push(ma)
        board_b.push(mb)

    assert moves_a == moves_b


@pytest.mark.asyncio
async def test_different_seeds_diverge():
    """Two different seeds should produce different move sequences within
    the first 20 plies. The probability of accidental collision is
    vanishingly small for any non-degenerate seed pair."""
    a = RandomEngine(seed=1)
    b = RandomEngine(seed=99999)

    board_a = chess.Board()
    board_b = chess.Board()
    seen_divergence = False
    for _ in range(20):
        if board_a.is_game_over() or board_b.is_game_over():
            break
        ma = await a.select_move(board_a, 1000)
        mb = await b.select_move(board_b, 1000)
        if ma != mb:
            seen_divergence = True
            break
        board_a.push(ma)
        board_b.push(mb)
    assert seen_divergence


@pytest.mark.asyncio
async def test_unseeded_engine_uses_system_randomness():
    """Unseeded RandomEngine instances should not collide deterministically."""
    a = RandomEngine()
    b = RandomEngine()
    board = chess.Board()

    # We'd expect at least one of 10 plies to differ between two
    # independent system-seeded engines on the 20-move-deep starting tree.
    diffs = 0
    for _ in range(10):
        ma = await a.select_move(board.copy(), 1000)
        mb = await b.select_move(board.copy(), 1000)
        if ma != mb:
            diffs += 1
    assert diffs > 0


def test_protocol_shape():
    """Must satisfy the runtime-checkable Engine Protocol."""
    eng = RandomEngine(seed=0)
    assert isinstance(eng, Engine)
    assert eng.name == "random"
    assert eng.generation == -1
    assert eng.lineage == []


def test_module_level_engine_singleton_is_a_random_engine():
    """`from darwin.engines.random_engine import engine` must yield a usable engine."""
    assert isinstance(module_engine, RandomEngine)
    assert module_engine.name == "random"


@pytest.mark.asyncio
async def test_concurrent_calls_dont_share_state():
    """Two concurrent select_move calls on the SAME engine must each
    return a legal move (the engine's RNG is not async-safe, but we
    rely on it not crashing under concurrent awaits even if results
    are correlated)."""
    eng = RandomEngine(seed=7)
    boards = [chess.Board() for _ in range(8)]
    results = await asyncio.gather(*[eng.select_move(b, 1000) for b in boards])
    for board, move in zip(boards, results):
        assert move in board.legal_moves
