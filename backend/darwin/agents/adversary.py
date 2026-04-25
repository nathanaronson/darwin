"""Adversary agent — critiques builder-generated engine code.

Sits between the builder and the validator in the per-candidate chain:

    strategist (propose) → builder (code) → adversary (critique) → fixer (revise) → validator

The adversary reads the builder's source and the originating question
and returns a focused critique paragraph: what's likely to forfeit a
game, what drifted off the question's category, what the validator
would reject. The fixer then runs a second builder-style call with the
critique baked into its prompt.

The adversary is intentionally a different model role from the builder
— pairing the same model family on both sides tends to rubber-stamp
its own output. ``settings.adversary_provider`` and
``settings.adversary_model`` exist so the operator can pin the
adversary to a different provider (e.g. builder=gemini, adversary=
claude) without restarting other roles.

Failure mode: if the LLM call errors out, returns ``""``. The
orchestrator treats an empty critique as "no fixes needed" and skips
the fixer step, so an adversary outage degrades cleanly to the
pre-adversary pipeline.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from darwin.agents.strategist import Question
from darwin.config import settings
from darwin.llm import complete_text

logger = logging.getLogger("darwin.agents.adversary")

PROMPT = (Path(__file__).parent / "prompts" / "adversary_v1.md").read_text()

# Hard cap so a malformed `SUMMARY:` line doesn't blow up the dashboard
# layout. The prompt asks for two sentences ≤ 220 chars; we trim to be safe.
_SUMMARY_MAX_CHARS = 280


@dataclass
class Critique:
    """Result of a single adversary call.

    ``summary`` is one short sentence intended for the dashboard.
    ``full`` is the multi-sentence paragraph fed verbatim to the fixer.
    Both are empty strings when the call failed or produced nothing
    usable; orchestrator code uses ``bool(crit.full)`` as the gate for
    "should I run the fixer?".
    """

    summary: str
    full: str


_EMPTY = Critique(summary="", full="")


def _parse_response(text: str) -> Critique:
    """Split the LLM response into (summary, full) per the prompt contract.

    Expected shape::

        SUMMARY: one short sentence
        <blank>
        full critique paragraph...

    Tolerant of a missing blank line and of the model writing something
    like ``Summary:`` instead of all-caps. If no SUMMARY: prefix is
    found, falls back to first sentence as summary + full text as full.
    """
    text = (text or "").strip()
    if not text:
        return _EMPTY

    lines = text.splitlines()
    summary = ""
    body_start = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.lower().startswith("summary:"):
            summary = stripped.split(":", 1)[1].strip()
            body_start = i + 1
            break

    if summary:
        full_lines = lines[body_start:]
        # Drop a single leading blank line (the prompt-mandated separator).
        if full_lines and not full_lines[0].strip():
            full_lines = full_lines[1:]
        full = "\n".join(full_lines).strip()
    else:
        # Fallback: derive a two-sentence summary from the start of the
        # full text. Better than rejecting a non-conforming response.
        full = text
        summary = _first_n_sentences(text, n=2) or text[:_SUMMARY_MAX_CHARS]

    summary = summary[:_SUMMARY_MAX_CHARS].strip()
    if not full:
        full = summary
    return Critique(summary=summary, full=full)


def _first_n_sentences(text: str, n: int) -> str:
    """Return the first ``n`` sentences of ``text``, joined with spaces.

    Sentence terminators we recognize: ``. ``, ``! ``, ``? ``, and a
    bare newline. Falls back to the whole text if fewer than ``n``
    sentences are present.
    """
    remaining = text.strip()
    out: list[str] = []
    for _ in range(n):
        if not remaining:
            break
        idx = -1
        terminator_len = 0
        for sep in (". ", "! ", "? ", "\n"):
            j = remaining.find(sep)
            if j != -1 and (idx == -1 or j < idx):
                idx = j
                terminator_len = len(sep)
        if idx == -1:
            out.append(remaining.strip())
            remaining = ""
            break
        # Include the terminator punctuation but drop the trailing space.
        end = idx + terminator_len
        sentence = remaining[:end].strip()
        if sentence:
            out.append(sentence)
        remaining = remaining[end:].lstrip()
    return " ".join(out).strip()


async def critique_engine(question: Question, code: str, engine_name: str) -> Critique:
    """Return an adversarial critique of ``code`` for ``question``.

    Returns an empty ``Critique(summary="", full="")`` on any failure
    (LLM error, empty response, exception). Callers should treat empty
    ``full`` as "skip the fixer pass" rather than blocking the candidate.
    """
    user = PROMPT.format(
        category=question.category,
        question_text=question.text,
        engine_name=engine_name,
        engine_code=code,
    )

    logger.info(
        "critique_engine starting engine=%s category=%s",
        engine_name, question.category,
    )

    try:
        text = await complete_text(
            model=settings.adversary_model,
            system=(
                "You are a critical reviewer of classical chess-engine code. "
                "Be specific, terse, and grounded in the code in front of you."
            ),
            user=user,
            max_tokens=600,
            provider=settings.provider_for("adversary"),
        )
    except Exception as exc:
        logger.warning(
            "adversary LLM call for engine=%s failed, skipping critique: %s",
            engine_name, exc,
        )
        return _EMPTY

    text = (text or "").strip()
    if len(text) < 20:
        logger.info(
            "critique_engine produced short/empty critique engine=%s len=%d — skipping fixer",
            engine_name, len(text),
        )
        return _EMPTY

    crit = _parse_response(text)
    logger.info(
        "critique_engine ok engine=%s summary_chars=%d full_chars=%d",
        engine_name, len(crit.summary), len(crit.full),
    )
    return crit
