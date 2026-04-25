"""Person C — builder + validator.

Step 2 (this commit): stub that writes a renamed copy of the champion
source so Person E can validate the full generation pipeline before the
real builder lands. Step 4 replaces ``build_engine`` with a real
Sonnet/Opus call using a ``submit_engine`` tool, plus the FORBIDDEN
regex backstop. See plans/person-c-agents.md.
"""

from pathlib import Path

from cubist.agents.strategist import Question

# We import GENERATED_DIR lazily so this module is importable even before
# Person A's registry stub is unstubbed (they share a circular relationship
# only at use-time).
_GENERATED_DIR = (
    Path(__file__).parent.parent / "engines" / "generated"
)


async def build_engine(
    champion_code: str,
    champion_name: str,
    generation: int,
    question: Question,
) -> Path:
    """Write a candidate engine module and return its path.

    Stub: copies the champion source verbatim into ``engines/generated/``,
    rewriting the engine ``name=`` literal so the registry sees a fresh
    name. Real implementation lands in Step 4. We keep the contract
    (returns a Path, raises on failure) stable across the swap.
    """
    name = f"gen{generation}-{question.category}-stub{question.index}"
    safe_filename = name.replace("-", "_") + ".py"
    _GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    out_path = _GENERATED_DIR / safe_filename

    # The stub literally renames the champion. The real builder will modify
    # the implementation per the question, but the name-rewrite step is the
    # same — the registry uses ``engine.name`` for de-duping.
    rewritten = champion_code.replace(f'"{champion_name}"', f'"{name}"', 1)
    out_path.write_text(rewritten)
    return out_path


async def validate_engine(module_path: Path) -> tuple[bool, str | None]:
    """Smoke-test a candidate.

    Stub: every candidate validates. Real implementation in Step 4 loads
    the module via ``cubist.engines.registry.load_engine`` and plays one
    short game vs ``RandomEngine`` using ``cubist.tournament.referee.play_game``.
    """
    del module_path  # unused in stub
    return True, None
