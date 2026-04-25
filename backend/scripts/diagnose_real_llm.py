"""Single-shot probe of the real strategist + builder pipeline.

Calls the configured LLM provider once, captures the raw output, runs it
through every gate (build → load → validator → smoke game → tournament)
and prints exactly where the pipeline rejects it.

Saves the generated source under ``backend/cubist/engines/generated/_diag_real_*.py``
so you can inspect the file directly.

Run from backend/ with your real .env in repo root (ANTHROPIC_API_KEY or
GOOGLE_API_KEY set):

    uv run python scripts/diagnose_real_llm.py
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import sys
import textwrap
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


def _section(title: str) -> None:
    print("\n" + "=" * 78)
    print(f"  {title}")
    print("=" * 78)


def _excerpt(s: str, n: int = 40) -> str:
    lines = s.splitlines()
    if len(lines) <= n:
        return s
    head = "\n".join(lines[: n - 5])
    tail = "\n".join(lines[-5:])
    return f"{head}\n  ... ({len(lines) - n} lines elided) ...\n{tail}"


async def main() -> None:
    # Reach into the module by attribute access so this script works on
    # main (no BANNED_IMPORTS) AND on followup/builder-quality (BANNED_IMPORTS
    # exported) without requiring an import that varies per branch.
    from cubist.agents import builder as B
    from cubist.agents.strategist import propose_questions
    from cubist.config import settings
    from cubist.engines.baseline import engine as baseline
    from cubist.engines.registry import load_engine
    from cubist.engines.random_engine import RandomEngine
    from cubist.tournament.runner import round_robin

    _section("ENV + CONFIG")
    print(f"  llm_provider:      {settings.llm_provider}")
    print(f"  strategist_model:  {settings.strategist_model}")
    print(f"  builder_model:     {settings.builder_model}")
    print(f"  player_model:      {settings.player_model}")
    print(f"  time_per_move_ms:  {settings.time_per_move_ms}")
    print(f"  games_per_pairing: {settings.games_per_pairing}")

    _section("STEP 1 — strategist.propose_questions  (real LLM call)")
    champion_source = inspect.getsource(type(baseline))
    print(f"  champion_source: {len(champion_source)} chars, "
          f"{len(champion_source.splitlines())} lines")
    try:
        questions = await propose_questions(champion_source, history=[])
        print(f"  → {len(questions)} questions")
        for q in questions:
            text = q.text.replace("\n", " ")
            print(f"    [{q.index}] {q.category:10s}: {text[:120]}")
    except Exception as e:
        print(f"  STRATEGIST FAILED: {type(e).__name__}: {e}")
        traceback.print_exc()
        return

    if not questions:
        print("  no questions → builder cannot proceed.")
        return

    _section("STEP 2 — builder.build_engine for question[0]  (real LLM call)")
    q0 = questions[0]
    print(f"  question[0]: category={q0.category}")
    print(f"  text: {q0.text[:200]}")
    try:
        path = await B.build_engine(
            champion_code=champion_source,
            champion_name=baseline.name,
            generation=99_999,
            question=q0,
        )
    except Exception as e:
        print(f"  BUILDER FAILED at write time: {type(e).__name__}: {e}")
        traceback.print_exc()
        return

    src = path.read_text()
    print(f"  wrote: {path}")
    print(f"  source: {len(src)} chars, {len(src.splitlines())} lines")
    print("  ----- generated source (head/tail) -----")
    print(textwrap.indent(_excerpt(src, n=50), "  | "))
    print("  ---------------------------------------")

    # rename so it's clearly diagnostic and not consumed by the next real run
    diag_path = path.parent / f"_diag_real_{path.stem}.py"
    if diag_path.exists():
        diag_path.unlink()
    path.rename(diag_path)
    path = diag_path

    _section("STEP 3 — static checks")
    forb = bool(B.FORBIDDEN.search(src))
    print(f"  FORBIDDEN regex match: {forb}")
    banned_re = getattr(B, "BANNED_IMPORTS", None)
    if banned_re is not None:
        print(f"  BANNED_IMPORTS regex match: {bool(banned_re.search(src))}")
    else:
        print("  BANNED_IMPORTS: regex not present on this branch (followup-2 not merged)")
    if "from cubist import config as settings" in src:
        print("  ⚠ generated code aliases the cubist.config MODULE — silent")
        print("    AttributeError on every settings.player_model access; engine")
        print("    falls back to next(iter(legal)) forever (followup-2 bug).")

    _section("STEP 4 — registry.load_engine")
    try:
        eng = load_engine(str(path))
        print(f"  load OK: name={eng.name!r} generation={eng.generation}")
    except Exception as e:
        print(f"  LOAD FAILED: {type(e).__name__}: {e}")
        print("  → validator would return (False, 'load: …') and orchestration")
        print("    drops this candidate. With both candidates dropped → tournament")
        print("    has [champion] alone → 0 games scheduled (round-robin i==j).")
        traceback.print_exc()
        return

    _section("STEP 5 — validator full run (load + smoke game)")
    try:
        ok, err = await B.validate_engine(path)
        print(f"  validator → ok={ok}  err={err!r}")
    except Exception as e:
        print(f"  validator unexpectedly raised: {type(e).__name__}: {e}")
        return
    if not ok:
        print("  → orchestration drops this candidate.")
        return

    _section("STEP 6 — round-robin vs RandomEngine (sanity)")
    try:
        standings = await round_robin(
            [eng, RandomEngine(seed=1)],
            games_per_pairing=1,
            time_per_move_ms=2_000,
        )
        print(f"  games scheduled: {len(standings.games)}")
        for i, g in enumerate(standings.games):
            print(f"    game[{i}]  {g.white} vs {g.black}  →  {g.result}  ({g.termination})")
        print(f"  scores: {standings.scores}")
    except Exception as e:
        print(f"  round_robin FAILED: {type(e).__name__}: {e}")
        traceback.print_exc()
        return

    _section("DIAGNOSIS")
    if all(g.termination == "checkmate" or g.termination == "draw" for g in standings.games):
        first_white = standings.games[0].white if standings.games else "?"
        print(
            f"  ✓ candidate engine {first_white!r} loaded, validated, and played "
            f"games to natural termination. The pipeline is healthy from this "
            f"engine's perspective."
        )
        print(
            "  If you still see 'no games' in the dashboard, the most likely "
            "remaining cause is the OTHER question's builder also failing — "
            "re-run this script with a different question[i] index, or read "
            "`cubist.api.routes` logs for the WS event flow."
        )
    elif any(g.termination == "error" for g in standings.games):
        print("  ⚠ at least one game ended in 'error' — the engine raised during "
              "select_move. Inspect the source above for an obvious crash.")
    elif any(g.termination == "illegal_move" for g in standings.games):
        print("  ⚠ engine returned an illegal move. The current validator does "
              "NOT reject this case (it only checks termination=='error'); the "
              "engine slips through.")
    elif any(g.termination == "time" for g in standings.games):
        print("  ⚠ select_move timed out — usually means the LLM call inside the "
              "engine is taking too long for the time-per-move budget.")


if __name__ == "__main__":
    asyncio.run(main())
