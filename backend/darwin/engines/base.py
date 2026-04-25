"""FROZEN CONTRACT — do not change without team sync.

Every engine in Darwin (baseline, candidate, champion) conforms to the Engine
Protocol so the tournament runner is engine-agnostic. Builder agents emit
Python modules whose top-level `engine` symbol satisfies this Protocol.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import chess


@runtime_checkable
class Engine(Protocol):
    """Anything that can pick a move from a board state."""

    name: str
    generation: int
    lineage: list[str]

    async def select_move(
        self,
        board: chess.Board,
        time_remaining_ms: int,
    ) -> chess.Move:
        """Return a legal move for `board.turn`. Must complete within
        `time_remaining_ms` or the referee will adjudicate a loss on time."""
        ...


class BaseLLMEngine:
    """Convenience base class for LLM-backed engines.

    Builder-generated engines may subclass this or implement Engine directly.
    Subclasses must implement `select_move`. Helper methods for prompt
    construction and SAN parsing live here so builders don't reinvent them.
    """

    name: str
    generation: int
    lineage: list[str]

    def __init__(self, name: str, generation: int, lineage: list[str] | None = None):
        self.name = name
        self.generation = generation
        self.lineage = lineage or []

    async def select_move(
        self,
        board: chess.Board,
        time_remaining_ms: int,
    ) -> chess.Move:
        raise NotImplementedError
