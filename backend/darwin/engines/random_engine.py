"""Random-move engine. Person A owns. Used by:
  - Person B for referee/runner tests (no API cost)
  - Person C's validator for smoke-testing builder output
"""

import random

import chess

from darwin.engines.base import BaseLLMEngine


class RandomEngine(BaseLLMEngine):
    def __init__(self, seed: int | None = None) -> None:
        super().__init__(name="random", generation=-1, lineage=[])
        self._rng = random.Random(seed)

    async def select_move(
        self,
        board: chess.Board,
        time_remaining_ms: int,
    ) -> chess.Move:
        return self._rng.choice(list(board.legal_moves))


engine = RandomEngine()
