"""Strategist agent — LLM-driven, with deterministic fallback.

For each category in ``CATEGORIES_USED`` we make one parallel LLM call.
Each call sees:
  - the chosen category,
  - the current champion's source code (so the proposal is specific to
    THIS engine, not a generic chess-textbook idea),
  - past winning questions (so the model doesn't propose the same
    direction we already promoted),
  - a handful of stylistic example ideas (anchor on length/granularity,
    not on content).

Each call returns one 30-50 word concrete proposal. If a call fails or
returns empty, that category falls back to the next entry in a small
canned pool — so one flaky LLM call never breaks an entire generation.
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


# Stylistic anchors — the model is told NOT to copy these, just to match
# their granularity. Also used as last-resort fallback if all else fails.
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
    "chess engine. Your proposal must be specific to the engine source "
    "you are shown — riff off what's already there, don't suggest a "
    "generic textbook technique that ignores the current code. Reply "
    "with a single 30-50 word description of the change to make. No "
    "preamble, no rationale, no code, no headings — just the proposal."
)


# Champion source can be many KB; truncate to keep prompts cheap and
# fast. The strategist mostly needs to see the *shape* (what features
# already exist) — full lines aren't required.
_MAX_CHAMPION_CHARS = 4000


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


def _truncate_code(code: str | None) -> str:
    if not code:
        return "(no champion code available)"
    if len(code) <= _MAX_CHAMPION_CHARS:
        return code
    return code[:_MAX_CHAMPION_CHARS] + "\n# ... (truncated)"


def _build_user_prompt(
    category: str, champion_code: str | None, past_wins_block: str
) -> str:
    examples = "\n".join(f"- {e}" for e in EXAMPLE_IDEAS[category])
    return (
        f"Category: {category}\n\n"
        f"Current champion source (the engine you are improving):\n"
        f"```python\n{_truncate_code(champion_code)}\n```\n\n"
        f"Past winning questions (oldest → newest) — do NOT repeat these:\n"
        f"{past_wins_block}\n\n"
        f"Example {category} ideas (for style/length only — do not copy):\n"
        f"{examples}\n\n"
        f"Propose one new {category} improvement, specific to this engine, "
        f"in 30-50 words. Build on what's already there."
    )


def _fallback_question(
    index: int, category: str, generation_number: int, wins: int
) -> Question:
    pool = EXAMPLE_IDEAS[category]
    rotation = (max(0, generation_number - 1) + wins) % len(pool)
    return Question(index=index, category=category, text=pool[rotation])


async def _propose_one(
    index: int,
    category: str,
    champion_code: str | None,
    past_wins_block: str,
    generation_number: int,
    wins: int,
) -> Question:
    user = _build_user_prompt(category, champion_code, past_wins_block)
    try:
        text = await complete_text(
            model=settings.strategist_model,
            system=_SYSTEM_PROMPT,
            user=user,
            max_tokens=200,
            provider=settings.provider_for("strategist"),
        )
    except Exception as exc:
        logger.warning(
            "strategist LLM call failed category=%s err=%r — using fallback",
            category, exc,
        )
        return _fallback_question(index, category, generation_number, wins)

    cleaned = (text or "").strip()
    if not cleaned:
        logger.warning(
            "strategist LLM returned empty category=%s — using fallback",
            category,
        )
        return _fallback_question(index, category, generation_number, wins)

    return Question(index=index, category=category, text=cleaned)


async def propose_questions(
    champion_code: str,
    history: list[dict],
    runner_up_code: str | None = None,
    champion_question: dict | None = None,
    generation_number: int | None = None,
) -> list[Question]:
    """Return one improvement question per category in ``CATEGORIES_USED``.

    Each entry of ``history`` should contain ``champion_category`` and
    (optionally) ``champion_question_text`` for past *promoted*
    generations — the strategist uses these to avoid re-proposing
    directions that already won.

    Args:
        champion_code: source of the current champion. Embedded in each
            per-category prompt so proposals are specific to this engine.
        history: list of prior gen records. Optional fields used:
            ``champion_category`` (str), ``champion_question_text`` (str).
        runner_up_code: accepted for API compatibility; not used in the
            prompt (would dilute focus on the champion).
        champion_question: accepted for API compatibility; ignored.
        generation_number: explicit gen number override; falls back to
            ``len(history) + 1``. Used by the deterministic fallback
            when an LLM call fails.
    """
    if generation_number is None:
        generation_number = max(1, len(history) + 1)

    past_wins_block = _format_past_wins(history)

    champion_wins_per_category: dict[str, int] = {c: 0 for c in CATEGORIES_USED}
    for h in history:
        cat = h.get("champion_category")
        if cat in champion_wins_per_category:
            champion_wins_per_category[cat] += 1

    questions = await asyncio.gather(
        *[
            _propose_one(
                i,
                cat,
                champion_code,
                past_wins_block,
                generation_number,
                champion_wins_per_category[cat],
            )
            for i, cat in enumerate(CATEGORIES_USED)
        ]
    )
    return list(questions)
