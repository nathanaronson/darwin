"""Probe what happens when the builder emits realistic broken patterns.

Each scenario constructs an engine source that resembles something the
real Sonnet/Opus builder might emit, then drives that source through:

    1. FORBIDDEN regex (build-time)
    2. registry.load_engine (validator phase 2 — module load)
    3. play_game vs RandomEngine (validator phase 3 — smoke game)
    4. round_robin (real tournament path)

For each scenario we print:
    - whether the source loads
    - whether the validator passes
    - how many tournament games actually finished
    - what termination reason

This pins down which failure modes the user is actually seeing.

Run from backend/:
    uv run python scripts/diagnose_broken_engines.py
"""

from __future__ import annotations

import asyncio
import logging
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.WARNING, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


SCENARIOS: dict[str, str] = {

    # ----------------------------------------------------------------- #
    # 1. The followup-2 bug: aliases the MODULE, settings.player_model
    #    raises AttributeError, which the engine's try/except catches →
    #    every game becomes "next(iter(legal))" forever.
    # ----------------------------------------------------------------- #
    "broken_config_alias": """\
import chess

from cubist.engines.base import BaseLLMEngine
from cubist.llm import complete_text
from cubist import config as settings   # <-- BROKEN: module, not Settings()


class CandidateEngine(BaseLLMEngine):
    def __init__(self):
        super().__init__(name="broken_config_alias", generation=1, lineage=["baseline-v0"])

    async def select_move(self, board, time_remaining_ms):
        try:
            text = await complete_text(
                settings.player_model,    # <-- AttributeError, swallowed below
                "You are a chess engine.",
                f"FEN: {board.fen()}\\nYour move:",
                max_tokens=10,
            )
            return board.parse_san(text.strip().split()[0])
        except Exception:
            return next(iter(board.legal_moves))


engine = CandidateEngine()
""",

    # ----------------------------------------------------------------- #
    # 2. Imports a non-existent submodule. ImportError at load time.
    # ----------------------------------------------------------------- #
    "missing_module": """\
import chess

from cubist.engines.base import BaseLLMEngine
from cubist.tools import settings   # <-- no such submodule


class CandidateEngine(BaseLLMEngine):
    def __init__(self):
        super().__init__(name="missing_module", generation=1, lineage=["baseline-v0"])

    async def select_move(self, board, time_remaining_ms):
        return next(iter(board.legal_moves))


engine = CandidateEngine()
""",

    # ----------------------------------------------------------------- #
    # 3. Forgets the top-level `engine = ...` symbol. Loader can't find it.
    # ----------------------------------------------------------------- #
    "missing_engine_symbol": """\
import chess

from cubist.engines.base import BaseLLMEngine


class CandidateEngine(BaseLLMEngine):
    def __init__(self):
        super().__init__(name="missing_engine_symbol", generation=1, lineage=["baseline-v0"])

    async def select_move(self, board, time_remaining_ms):
        return next(iter(board.legal_moves))


# (no `engine = CandidateEngine()` line — common LLM forgetfulness)
""",

    # ----------------------------------------------------------------- #
    # 4. Syntax error somewhere in the body.
    # ----------------------------------------------------------------- #
    "syntax_error": """\
import chess

from cubist.engines.base import BaseLLMEngine


class CandidateEngine(BaseLLMEngine):
    def __init__(self):
        super().__init__(name="syntax_error", generation=1, lineage=["baseline-v0"])

    async def select_move(self, board, time_remaining_ms):
        return next(iter(board.legal_moves)
                    # missing close paren


engine = CandidateEngine()
""",

    # ----------------------------------------------------------------- #
    # 5. select_move uses `board.turn` after a `for move in board.legal_moves:`
    #    loop that pushed but didn't pop — corrupts state. Move returned
    #    is illegal in the post-corruption position.
    # ----------------------------------------------------------------- #
    "illegal_move_returned": """\
import chess

from cubist.engines.base import BaseLLMEngine


class CandidateEngine(BaseLLMEngine):
    def __init__(self):
        super().__init__(name="illegal_move_returned", generation=1, lineage=["baseline-v0"])

    async def select_move(self, board, time_remaining_ms):
        # Build a "best move" from a *fictional* square so referee rejects it.
        return chess.Move.from_uci("e2e6")


engine = CandidateEngine()
""",

    # ----------------------------------------------------------------- #
    # 6. select_move raises uncaught — game ends with termination=error.
    # ----------------------------------------------------------------- #
    "raises_at_play": """\
import chess

from cubist.engines.base import BaseLLMEngine


class CandidateEngine(BaseLLMEngine):
    def __init__(self):
        super().__init__(name="raises_at_play", generation=1, lineage=["baseline-v0"])

    async def select_move(self, board, time_remaining_ms):
        raise RuntimeError("simulated runtime crash")


engine = CandidateEngine()
""",

    # ----------------------------------------------------------------- #
    # 7. The "good" baseline behaviour — first legal move forever.
    #    This is the floor: with every candidate behaving like this, do
    #    tournament games complete?
    # ----------------------------------------------------------------- #
    "always_first_legal": """\
import chess

from cubist.engines.base import BaseLLMEngine


class CandidateEngine(BaseLLMEngine):
    def __init__(self):
        super().__init__(name="always_first_legal", generation=1, lineage=["baseline-v0"])

    async def select_move(self, board, time_remaining_ms):
        return next(iter(board.legal_moves))


engine = CandidateEngine()
""",
}


async def probe(name: str, source: str) -> dict:
    """Run one scenario through the build → validate → tournament path."""
    from cubist.agents.builder import FORBIDDEN, validate_engine
    from cubist.engines.registry import load_engine

    out: dict = {"name": name}
    out["FORBIDDEN_match"] = bool(FORBIDDEN.search(source))

    # Write to a tmp path under engines/generated/ so the validator's lazy
    # imports point at the right registry view of the file.
    gen_dir = Path(__file__).resolve().parent.parent / "cubist" / "engines" / "generated"
    gen_dir.mkdir(parents=True, exist_ok=True)
    p = gen_dir / f"_diag_{name}.py"
    p.write_text(source)

    # 1. Direct registry load (mimics validator phase 2)
    try:
        eng = load_engine(str(p))
        out["load_ok"] = True
        out["load_err"] = None
    except Exception as e:
        out["load_ok"] = False
        out["load_err"] = f"{type(e).__name__}: {e}"
        eng = None

    # 2. Validator (which itself wraps load + smoke game)
    try:
        ok, err = await validate_engine(p)
        out["validator_ok"] = ok
        out["validator_err"] = err
    except Exception as e:
        out["validator_ok"] = False
        out["validator_err"] = f"unexpected raise: {type(e).__name__}: {e}"

    # 3. If we have a loaded engine, run a real round-robin against
    #    RandomEngine to see if games actually finish.
    if eng is not None:
        from cubist.engines.random_engine import RandomEngine
        from cubist.tournament.runner import round_robin

        try:
            standings = await round_robin(
                [eng, RandomEngine(seed=1)],
                games_per_pairing=1,
                time_per_move_ms=2_000,
            )
            out["games_played"] = len(standings.games)
            out["terminations"] = [g.termination for g in standings.games]
            out["results"] = [g.result for g in standings.games]
        except Exception as e:
            out["games_played"] = -1
            out["terminations"] = []
            out["round_robin_err"] = f"{type(e).__name__}: {e}"

    return out


async def main() -> None:
    print(f"\n{'scenario':<28s} | FORBIDDEN | load_ok | validator | games | terminations")
    print("-" * 110)
    for name, src in SCENARIOS.items():
        try:
            r = await probe(name, src)
        except Exception as e:
            traceback.print_exc()
            print(f"{name:<28s} | exception in probe: {e}")
            continue

        forbidden = "match" if r["FORBIDDEN_match"] else "ok"
        load = "OK" if r.get("load_ok") else f"FAIL ({r.get('load_err', '')[:50]})"
        validator = "OK" if r.get("validator_ok") else f"FAIL ({(r.get('validator_err') or '')[:60]})"
        games = r.get("games_played", "n/a")
        terms = r.get("terminations", [])

        print(f"{name:<28s} | {forbidden:<9s} | {load:<7s} | {validator:<35s} | {games!s:<5s} | {terms}")

    # cleanup
    gen_dir = Path(__file__).resolve().parent.parent / "cubist" / "engines" / "generated"
    for p in gen_dir.glob("_diag_*.py"):
        p.unlink()


if __name__ == "__main__":
    asyncio.run(main())
