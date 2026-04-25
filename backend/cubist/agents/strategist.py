"""Person C — strategist agent.

EXPERIMENTAL pure-code branch: the strategist is deterministic and does
NOT call an LLM. Pure-code engines have no LLM dependencies at runtime,
so it makes no sense for the strategist to consult an LLM either —
that just spends API quota on questions we can author ahead of time.

Each generation we hand the builders 4 distinct questions, one per
category in ``CATEGORIES_USED``. For variety across generations we keep
a pool of multiple template questions per category and rotate through
them based on the generation number — so gen 1, gen 2, gen 5 each see
different angles on "search", different angles on "evaluation", etc.

The async ``propose_questions`` signature is preserved so the
orchestrator doesn't need to change. ``champion_code``,
``runner_up_code``, and ``history`` are accepted but ignored — the
question pool is canned ahead of time.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

CATEGORIES = ["prompt", "search", "book", "evaluation", "sampling"]

# Pure-code engines have no LLM-prompt component, so "prompt" is dropped
# from the active rotation. The remaining four categories all map cleanly
# to classical chess-engine techniques.
CATEGORIES_USED = ["search", "evaluation", "book", "sampling"]


# Each pool holds multiple concrete improvement directions. We pick by
# ``(gen_number - 1) % len(pool)`` so the same pool produces a new
# direction every generation until it cycles. Pool sizes are different
# across categories — that's fine; each rotates independently.
QUESTION_POOLS: dict[str, list[str]] = {
    "search": [
        "Add iterative deepening up to depth 4. Start at depth 1, "
        "deepen until ~50% of the move budget is spent, return the "
        "best move found at the deepest completed iteration.",
        "Implement principal-variation search (PVS) on top of alpha-"
        "beta. Search the first move full-window, the rest with a "
        "null window, re-search if the null-window result raises "
        "alpha.",
        "Add a transposition table keyed by board.fen() (or zobrist "
        "hash if you prefer). Each entry stores (depth, score, "
        "flag). Probe at the top of the search; cut off on exact "
        "score at the same depth or better.",
        "Add MVV-LVA (most-valuable-victim, least-valuable-attacker) "
        "move ordering for captures, then the rest by material gain. "
        "Better ordering means more alpha-beta cutoffs at the same "
        "depth.",
        "Implement late-move reductions: search the first 4 moves "
        "full depth, the rest with depth-1 first, only re-search "
        "full-depth if the reduced search beats alpha.",
    ],
    "evaluation": [
        "Add a piece-square table for each piece type (knight in "
        "the center > knight on the edge, bishop on long diagonals, "
        "etc.). Keep the table small — 64 entries per piece type, "
        "tuned by intuition rather than learning.",
        "Add a king-safety penalty: count attacker pieces near each "
        "king's square (within Chebyshev distance 2) and subtract a "
        "weighted penalty from the side under attack.",
        "Add a pawn-structure term: penalize doubled pawns, "
        "isolated pawns, and bonus for passed pawns (a pawn whose "
        "advance is not blocked by enemy pawns on adjacent files).",
        "Add a mobility term: count legal moves for each side after "
        "the position is reached, weight at ~10 cp per extra move "
        "for the side to move.",
        "Add a center-control bonus: each piece attacking d4/d5/e4/"
        "e5 contributes +5 cp to its side. Encourages early central "
        "presence.",
    ],
    "book": [
        "Hardcode a small opening book (~10 lines) of common "
        "responses by FEN-prefix. e.g. e4 → e5 / c5 / e6, etc. If "
        "the position matches a book entry, play the book move; "
        "otherwise fall through to your search code.",
        "Add a 'best response' table for the most common ~20 "
        "starting positions after move 1. Lookup by FEN, fall "
        "through to search if no match.",
        "Implement opening principles as soft heuristics in the "
        "first 8 plies: prefer central pawn moves, prefer "
        "developing minor pieces over moving the same piece twice, "
        "prefer king-side castling.",
        "Build an endgame mate-pattern recognizer for K+R vs K and "
        "K+Q vs K. When the position matches, drive the lone king "
        "to the edge using simple distance heuristics rather than "
        "search.",
    ],
    "sampling": [
        "Monte Carlo Tree Search (light): for each legal root move, "
        "play 20 random rollouts to a fixed ply depth, score by "
        "material at the end of each rollout, pick the move with "
        "the best average score.",
        "Random move sampling with eval filter: generate 10 random "
        "candidate moves, evaluate the resulting position with your "
        "eval function, pick the highest-scoring.",
        "Stochastic best-first: at each node in your search, try "
        "moves in a random order rather than legal-moves order. "
        "Reduces alpha-beta efficiency but expands the search space.",
        "Multi-armed-bandit move selection: track for each move a "
        "running average of its score across the search; bias future "
        "exploration toward high-mean / high-uncertainty moves "
        "(simple UCB1 formula).",
    ],
}


@dataclass
class Question:
    index: int
    category: str
    text: str


# Kept for back-compat — orchestrator may still inspect this. Inert
# under the deterministic regime since no model is being prompted.
PROMPT = (Path(__file__).parent / "prompts" / "strategist_v1.md").read_text()


async def propose_questions(
    champion_code: str,
    history: list[dict],
    runner_up_code: str | None = None,
    champion_question: dict | None = None,
) -> list[Question]:
    """Return 4 distinct improvement questions across the locked categories.

    Deterministic on this experimental branch: no LLM call. The pool
    rotates by ``len(history) + 1`` so different generations exercise
    different angles. ``champion_code``, ``runner_up_code``, and
    ``champion_question`` are accepted (preserving the API) but ignored.

    Returns:
        Length-4 list of ``Question`` records, one per category in
        ``CATEGORIES_USED``.
    """
    # Generation number determines which question we pick from each
    # pool. ``len(history)+1`` gives us the gen we're currently
    # building for (history is the list of *prior* gen summaries).
    gen_number = max(1, len(history) + 1)

    out: list[Question] = []
    for i, cat in enumerate(CATEGORIES_USED):
        pool = QUESTION_POOLS[cat]
        text = pool[(gen_number - 1) % len(pool)]
        out.append(Question(index=i, category=cat, text=text))
    return out
