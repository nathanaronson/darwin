"""Strategist agent — LLM-based.

For each category in ``CATEGORIES_USED`` we make one strategist LLM call
in parallel. Each call gets a compact prompt: the chosen category, the
list of past winning categories and questions, and a handful of example
ideas in that category. The model returns a 30–50 word description of
one concrete improvement to try.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from darwin.config import settings
from darwin.llm import complete_text

logger = logging.getLogger("darwin.strategist")


CATEGORIES = ["prompt", "search", "book", "evaluation", "sampling"]

# Pure-code engines have no LLM-prompt component, so "prompt" is dropped
# from the active rotation.
CATEGORIES_USED = ["search", "evaluation", "book", "sampling"]


# Seed examples shown to the model so it knows the style and granularity
# of a useful suggestion. The instruction tells it not to copy them
# verbatim — they're stylistic anchors, not the answer set.
EXAMPLE_IDEAS: dict[str, list[str]] = {
    "search": [
        "Iterative deepening up to depth 4; deepen until ~50% of the move budget is spent and return the best move at the deepest completed iteration.",
        "Principal-variation search on top of alpha-beta: full window for the first move, null window for the rest, re-search on alpha raises.",
        "Transposition table keyed by board.fen() storing (depth, score, flag); cut off on exact score at the same depth or better.",
        "MVV-LVA capture ordering, then quiet moves by static gain — better ordering means more alpha-beta cutoffs at the same depth.",
        "Late-move reductions: full depth for the first 4 moves, depth-1 for the rest, re-search full only if the reduced search beats alpha.",
    ],
    "evaluation": [
        "Piece-square tables per piece type (knight in the center > knight on the edge, bishop on long diagonals); 64 entries per piece, hand-tuned.",
        "King-safety penalty: count attacker pieces within Chebyshev distance 2 of each king and subtract a weighted penalty from the side under attack.",
        "Pawn-structure term: penalize doubled and isolated pawns, bonus for passed pawns whose advance is unblocked on adjacent files.",
        "Mobility term: count legal moves for each side at the position, weight ~10cp per extra move for the side to move.",
        "Center-control bonus: each piece attacking d4/d5/e4/e5 contributes +5cp to its side.",
    ],
    "book": [
        "Hardcoded ~10-line opening book keyed by FEN-prefix (e4 → e5 / c5 / e6, etc.); fall through to search if no match.",
        "Best-response table for the ~20 most common positions after move 1; lookup by FEN, fall through to search if no match.",
        "Soft opening principles in the first 8 plies: prefer central pawn moves, prefer minor-piece development over moving the same piece twice, prefer king-side castling.",
        "Endgame mate-pattern recognizer for K+R vs K and K+Q vs K; drive the lone king to the edge with simple distance heuristics.",
    ],
    "sampling": [
        "Light MCTS: for each legal root move, play 20 random rollouts to a fixed ply depth, score by end-position material, pick the move with the best average.",
        "Random move sampling with eval filter: generate 10 random candidate moves, evaluate each resulting position, pick the highest-scoring.",
        "Stochastic best-first: at each search node try moves in random order; reduces alpha-beta efficiency but expands the search space.",
        "Multi-armed-bandit move selection: track running mean score per move and bias exploration toward high-mean / high-uncertainty moves (UCB1).",
    ],
}


@dataclass
class Question:
    index: int
    category: str
    text: str


_SYSTEM_PROMPT = (
    "You propose one concrete improvement to a classical (pure-Python) "
    "chess engine. Reply with a single 30-50 word description of the "
    "change to make. No preamble, no rationale, no code, no headings — "
    "just the proposal."
)


def _format_past_wins(history: list[dict]) -> str:
    lines = []
    for h in history:
        cat = h.get("champion_category")
        text = h.get("champion_question_text")
        if cat in CATEGORIES_USED and text:
            lines.append(f"- [{cat}] {text}")
    if not lines:
        return "(no prior winners yet)"
    return "\n".join(lines)


def _build_user_prompt(category: str, past_wins_block: str) -> str:
    examples = "\n".join(f"- {e}" for e in EXAMPLE_IDEAS[category])
    return (
        f"Category: {category}\n\n"
        f"Past winning questions (oldest → newest):\n{past_wins_block}\n\n"
        f"Example {category} ideas (for style only — do not repeat):\n{examples}\n\n"
        f"Propose one new {category} improvement in 30-50 words."
    )


async def _propose_one(index: int, category: str, past_wins_block: str) -> Question:
    user = _build_user_prompt(category, past_wins_block)
    text = await complete_text(
        model=settings.strategist_model,
        system=_SYSTEM_PROMPT,
        user=user,
        max_tokens=200,
        provider=settings.provider_for("strategist"),
    )
    return Question(index=index, category=category, text=text.strip())


async def propose_questions(
    champion_code: str,
    history: list[dict],
    runner_up_code: str | None = None,
    champion_question: dict | None = None,
    generation_number: int | None = None,
) -> list[Question]:
    """Return one improvement question per category in ``CATEGORIES_USED``.

    Each entry of ``history`` should contain ``champion_category`` and
    ``champion_question_text`` for past *promoted* generations — these
    are the only fields the strategist reads. ``champion_code``,
    ``runner_up_code``, ``champion_question``, and ``generation_number``
    are accepted for orchestrator API compatibility but are not part of
    the prompt.
    """
    past_wins_block = _format_past_wins(history)
    questions = await asyncio.gather(
        *[
            _propose_one(i, cat, past_wins_block)
            for i, cat in enumerate(CATEGORIES_USED)
        ]
    )
    return list(questions)
