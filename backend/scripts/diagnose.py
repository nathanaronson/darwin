"""End-to-end diagnostic: are we even running tournament games?

Mocks `cubist.llm.complete` so the strategist + builder return canned
responses, then drives `run_generation` against the real baseline,
real registry, real referee, real round-robin. Prints every event
that flows through `bus.emit`. Tells us in <10 s whether the
orchestration plumbing actually invokes ``play_game`` or stalls on
an empty candidate set.

Run from backend/:
    uv run python scripts/diagnose.py
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

# This engine source uses the import pattern *the prompt teaches* — i.e. NOT the
# `from cubist import config as settings` bug that follow-up 2 documents.
# It mostly just returns a legal move via python-chess; that's enough to
# verify play_game / round_robin actually run games.
GOOD_ENGINE_SOURCE = """\
import chess

from cubist.engines.base import BaseLLMEngine


class CandidateEngine(BaseLLMEngine):
    def __init__(self):
        super().__init__(name=\"PLACEHOLDER\", generation=1, lineage=[\"baseline-v0\"])

    async def select_move(self, board, time_remaining_ms):
        # Always pick the first legal move (deterministic; doesn't call LLM).
        return next(iter(board.legal_moves))


engine = CandidateEngine()
"""


def fake_strategist_blocks() -> list[SimpleNamespace]:
    return [
        SimpleNamespace(
            type="tool_use",
            name="submit_questions",
            input={
                "questions": [
                    {"category": "prompt", "text": "diagnostic question on prompt category — verify orchestration."},
                    {"category": "search", "text": "diagnostic question on search category — verify orchestration."},
                ]
            },
        )
    ]


def fake_builder_blocks(engine_name: str) -> list[SimpleNamespace]:
    code = GOOD_ENGINE_SOURCE.replace("PLACEHOLDER", engine_name)
    return [SimpleNamespace(type="tool_use", name="submit_engine", input={"code": code})]


async def fake_complete(**kwargs) -> list:
    """Mock that branches by tools[0]['name']."""
    tools = kwargs.get("tools") or []
    name = tools[0]["name"] if tools else ""
    if name == "submit_questions":
        return fake_strategist_blocks()
    if name == "submit_engine":
        # Pull the engine name out of the user prompt — the build_engine
        # call template inserts it as ``engine_name``.
        user = kwargs.get("user", "")
        # Look for the "name=\"...\"" line from the prompt's super().__init__ block.
        eng_name = "candidate-fallback"
        for line in user.splitlines():
            line = line.strip()
            if line.startswith('name="') and line.endswith('",'):
                eng_name = line[len('name="'):-2]
                break
        return fake_builder_blocks(eng_name)
    return []


async def main() -> None:
    # Patch at module-load time so build_engine + propose_questions both see the fake.
    import cubist.agents.builder as B
    import cubist.agents.strategist as S
    B.complete = fake_complete
    S.complete = fake_complete

    # Capture every event the bus emits.
    from cubist.api.websocket import bus

    events: list[dict] = []

    async def emit_capture(payload: dict) -> None:
        events.append(payload)
        print(f"  [event] {payload.get('type', '?'):28s} {payload!r}", flush=True)

    bus.emit = emit_capture  # type: ignore[assignment]

    # Initialize the DB so generation.py's persistence path doesn't blow up.
    from cubist.storage.db import init_db
    init_db()

    from cubist.engines.baseline import engine as baseline
    from cubist.orchestration.generation import run_generation

    print("\n=== run_generation(baseline, 1) starting ===\n", flush=True)
    try:
        new_champion = await run_generation(baseline, 1)
        print(f"\n=== run_generation completed, new_champion = {new_champion.name} ===\n")
    except Exception as e:
        print(f"\n!!! run_generation crashed: {type(e).__name__}: {e}", flush=True)
        import traceback
        traceback.print_exc()

    # Summary
    print("\n=== EVENT TIMELINE ===")
    for e in events:
        t = e.get("type", "?")
        print(f"  {t}")

    # How many game.move + game.finished events did we see?
    moves = sum(1 for e in events if e.get("type") == "game.move")
    finishes = sum(1 for e in events if e.get("type") == "game.finished")
    builders = [e for e in events if e.get("type") == "builder.completed"]
    print(f"\n  game.move events     = {moves}")
    print(f"  game.finished events = {finishes}")
    print(f"  builder.completed: ok = {sum(1 for b in builders if b.get('ok'))}, "
          f"failed = {sum(1 for b in builders if not b.get('ok'))}")
    if builders:
        for b in builders:
            print(f"    builder[{b.get('question_index')}] = {b.get('engine_name')!r} "
                  f"ok={b.get('ok')} err={b.get('error')!r}")


if __name__ == "__main__":
    asyncio.run(main())
