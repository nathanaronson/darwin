"""Person C — strategist agent.

EXPERIMENTAL pure-code branch: the strategist is deterministic and does
NOT call an LLM. Pure-code engines have no LLM dependencies at runtime,
so it makes no sense for the strategist to consult an LLM either —
that just spends API quota on questions we can author ahead of time.

Each generation we hand the builders 8 distinct questions, one per
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

CATEGORIES = [
    "prompt",
    "search",
    "book",
    "evaluation",
    "sampling",
    "quiescence",
    "timing",
    "heuristics",
    "endgame",
]

# Pure-code engines have no LLM-prompt component, so "prompt" is dropped
# from the active rotation. The remaining eight categories all map cleanly
# to classical chess-engine techniques: depth-based search, board
# evaluation, opening/endgame book lookups, stochastic sampling, tactical
# leaf-search (quiescence), clock management (timing), move-ordering
# heuristics, and dedicated endgame play. Single-word names are required
# because the engine-name round-trip (hyphens → underscores → hyphens)
# garbles multi-word categories.
CATEGORIES_USED = [
    "search",
    "evaluation",
    "book",
    "sampling",
    "quiescence",
    "timing",
    "heuristics",
    "endgame",
]


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
    "quiescence": [
        "Add a quiescence search: at the leaves of alpha-beta, "
        "instead of returning eval immediately, recurse on captures-"
        "only until the position is 'quiet' (no captures available). "
        "Eliminates horizon-effect blunders where the search ends "
        "mid-exchange.",
        "Add Static Exchange Evaluation (SEE) for capture filtering: "
        "for each capture move, simulate the full sequence of "
        "recaptures on that square and score the net material. Only "
        "enter quiescence on captures with SEE >= 0; prune losing "
        "captures cheaply.",
        "Add a check extension: when the side-to-move is in check, "
        "search the response one ply deeper without decrementing the "
        "depth counter. Forced sequences get the focus they deserve "
        "without burning depth on quiet branches.",
        "Implement null-move pruning: at non-PV nodes with depth >= 3, "
        "let the side-to-move 'pass' and search the resulting position "
        "with depth-3. If the score still exceeds beta, prune the "
        "node — the position is so good that any real move is at "
        "least as strong as passing.",
    ],
    "timing": [
        "Switch from a fixed time-per-move budget to soft/hard "
        "thresholds. Aim for ~5% of remaining clock per move (soft); "
        "allow up to ~10% (hard) when the search just produced a "
        "fail-low at higher depth and re-search would help. Stop "
        "thinking the moment soft is hit on a stable best move.",
        "Add an instamove for forced positions: if there's exactly "
        "one legal move, play it immediately and skip search entirely. "
        "Saves seconds on forced recaptures, forced-mate-defense, and "
        "single-legal-response check escapes.",
        "Add a panic mode for low-clock situations: when remaining "
        "time drops below ~10s, hard-cap search at depth 1 and pick "
        "by material+capture-ordering only. Prevents flagging while "
        "still playing reasonable moves.",
        "Make search depth adaptive to position complexity: count "
        "legal moves at the root. If < 8 legal moves, search 1 ply "
        "deeper (likely-forced lines reward depth); if > 30 legal "
        "moves, search 1 ply shallower (broad positions don't reward "
        "deep tactical search).",
    ],
    "heuristics": [
        "Add the killer-move heuristic for move ordering: track up to "
        "2 quiet moves per ply that caused a beta cutoff, and try "
        "them first (after captures) at sibling nodes. Cheap to "
        "maintain (per-ply 2-slot array), measurable cutoff-ordering "
        "improvement.",
        "Add a history heuristic: maintain a 64×64 from-to integer "
        "table that gets += depth² each time a quiet move beats beta. "
        "Sort quiet moves by their history score during ordering. "
        "Builds search-wide knowledge about which moves tend to cut.",
        "Add the counter-move heuristic: when the opponent's last "
        "move was M (from-to), remember which of our responses caused "
        "a cutoff after M. Try that counter-move first whenever M "
        "reappears. Tiny 64×64 table, surprisingly effective.",
        "Combine history with a butterfly table (total tries per "
        "from-to square) and order by relative history "
        "(history / butterfly). Prevents popular-but-rarely-cuts "
        "moves from dominating the ordering once their history saturates.",
    ],
    "endgame": [
        "Add a pawn-endgame king-activation bonus: when the position "
        "has zero minor and major pieces (just kings + pawns), add "
        "+30cp per square the king is closer to e4/e5/d4/d5. The eval "
        "should reward king centralization in pawn endings rather than "
        "leaving it on the back rank where middlegame king-safety put it.",
        "Implement opposition recognition for K vs K+P endings: when "
        "the kings are on the same file or rank with one square between "
        "them, the side NOT to move has the opposition. Add a +50cp "
        "bonus for the side with opposition in king-pawn endings — the "
        "engine will play to gain or keep it.",
        "Add the rule-of-the-square for passed pawns: for each passed "
        "pawn, compute Chebyshev distance from the lone defending king "
        "to the pawn's promotion square. If the king is outside the "
        "square (distance > squares-to-promotion), the pawn is unstoppable "
        "and gets a huge bonus; otherwise a normal passed-pawn bonus.",
        "Add a bishop-pair endgame bonus: when only bishops and pawns "
        "remain on the board, the side with both bishops gets +50cp and "
        "the eval prefers open positions (count pawn-blocked squares, "
        "subtract from the bonus). Distinct from a generic mobility term "
        "in middlegame eval.",
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
    generation_number: int | None = None,
) -> list[Question]:
    """Return 4 distinct improvement questions across the locked categories.

    Deterministic on this experimental branch — no LLM. Two layers of
    selection logic, both performance-aware:

    Within each category, advance the rotation pointer based on how
    many times that category has already been *tried* across previous
    gens (i.e. ``history`` length, or ``generation_number`` if passed).
    So if a category's pool has 5 entries, gens 1-5 hit each one once,
    gen 6 cycles back to entry 0 with one variation tried again.

    But also: bias the pool selection toward what's been *winning*. If
    a prior gen's champion came from category X, the next gen's pool
    pointer for X advances *one extra step* — the strategist tries the
    next most-related variant in that category to see if doubling down
    on a winning theme produces another champion. This is the closest
    deterministic analogue to "build on the best models" without an
    LLM looking at the source.

    Args:
        champion_code, runner_up_code: accepted but unused (kept for
            API compatibility with the LLM-driven version).
        history: list of prior gen records. Each record is a dict with
            optional ``generation`` (int) and ``champion_category``
            (str — the category whose candidate became this gen's
            champion, or None on retention). The strategist uses this
            for performance-aware bias.
        champion_question: ignored under deterministic mode.
        generation_number: explicit gen number override. If passed,
            takes precedence over ``len(history)+1`` for rotation.
            Lets the orchestrator be authoritative about gen number
            even if it builds an empty history.
    """
    if generation_number is None:
        generation_number = max(1, len(history) + 1)

    # Performance-aware bias: count how often each category has produced
    # a champion in past gens. Each champion-promotion pushes that
    # category's rotation pointer forward by 1 — so winning categories
    # get re-explored with new variants faster than losing ones.
    champion_wins_per_category: dict[str, int] = {c: 0 for c in CATEGORIES_USED}
    for h in history:
        cat = h.get("champion_category")
        if cat in champion_wins_per_category:
            champion_wins_per_category[cat] += 1

    out: list[Question] = []
    for i, cat in enumerate(CATEGORIES_USED):
        pool = QUESTION_POOLS[cat]
        # Base rotation by gen number + extra advance for winning cats.
        rotation = (generation_number - 1) + champion_wins_per_category[cat]
        text = pool[rotation % len(pool)]
        out.append(Question(index=i, category=cat, text=text))
    return out
