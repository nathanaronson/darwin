"""Tests for darwin.agents.adversary.

The LLM call is mocked. Empty ``Critique(summary="", full="")`` return
on any failure is a load-bearing contract (the orchestrator skips the
fixer when ``crit.full`` is empty), so it gets dedicated coverage.
"""

from __future__ import annotations

import pytest

from darwin.agents import adversary
from darwin.agents.adversary import Critique, _parse_response, critique_engine
from darwin.agents.strategist import Question


@pytest.fixture
def question() -> Question:
    return Question(
        index=0,
        category="quiescence",
        text="Add capture-only quiescence search to depth 4.",
    )


@pytest.mark.asyncio
async def test_returns_summary_and_full_on_success(monkeypatch, question):
    captured: dict = {}

    async def fake_complete_text(model, system, user, max_tokens=256, provider=None):
        captured["model"] = model
        captured["provider"] = provider
        captured["user"] = user
        return (
            "SUMMARY: Quiescence is unbounded — will forfeit on time\n"
            "\n"
            "Quiescence has no depth bound — at high capture density this "
            "will exceed the 5s budget and forfeit on time. Cap the recursion "
            "at depth 4. The eval also has a sign error in the negamax return."
        )

    monkeypatch.setattr(adversary, "complete_text", fake_complete_text)

    crit = await critique_engine(question, "code goes here", "gen1-quiescence-abc123")

    assert isinstance(crit, Critique)
    assert crit.summary == "Quiescence is unbounded — will forfeit on time"
    assert crit.full.startswith("Quiescence has no depth bound")
    # Prompt must include the question text and code so the model can ground its review.
    assert "capture-only quiescence" in captured["user"]
    assert "code goes here" in captured["user"]


@pytest.mark.asyncio
async def test_returns_empty_critique_on_llm_failure(monkeypatch, question):
    async def boom(*args, **kwargs):
        raise RuntimeError("provider down")

    monkeypatch.setattr(adversary, "complete_text", boom)

    crit = await critique_engine(question, "code", "gen1-quiescence-abc123")
    assert crit == Critique(summary="", full="")


@pytest.mark.asyncio
async def test_returns_empty_critique_on_short_response(monkeypatch, question):
    async def fake(*args, **kwargs):
        return "ok"

    monkeypatch.setattr(adversary, "complete_text", fake)

    crit = await critique_engine(question, "code", "gen1-quiescence-abc123")
    assert crit == Critique(summary="", full="")


@pytest.mark.asyncio
async def test_uses_adversary_provider_override(monkeypatch, question):
    """Provider routing for adversary must come from settings.adversary_provider."""
    from darwin.config import settings

    monkeypatch.setattr(settings, "adversary_provider", "gemini")

    captured: dict = {}

    async def fake(model, system, user, max_tokens=256, provider=None):
        captured["provider"] = provider
        return (
            "SUMMARY: looks fine\n\n"
            "A long enough critique paragraph to clear the 20-char minimum threshold."
        )

    monkeypatch.setattr(adversary, "complete_text", fake)

    await critique_engine(question, "code", "gen1-quiescence-abc123")
    assert captured["provider"] == "gemini"


def test_parse_response_with_summary_prefix():
    crit = _parse_response(
        "SUMMARY: short hot take\n\nFull paragraph with multiple sentences. Goes on."
    )
    assert crit.summary == "short hot take"
    assert crit.full == "Full paragraph with multiple sentences. Goes on."


def test_parse_response_lowercase_summary_prefix():
    """Tolerance for `Summary:` instead of `SUMMARY:`."""
    crit = _parse_response("Summary: less strict\n\nThe body of the critique.")
    assert crit.summary == "less strict"
    assert crit.full == "The body of the critique."


def test_parse_response_without_blank_separator():
    """Model forgets the blank line — still parse cleanly."""
    crit = _parse_response("SUMMARY: tight\nThe critique body follows immediately.")
    assert crit.summary == "tight"
    assert crit.full == "The critique body follows immediately."


def test_parse_response_falls_back_when_no_summary():
    """No `SUMMARY:` prefix — derive summary from first two sentences."""
    crit = _parse_response(
        "Quiescence is unbounded. The eval has a sign bug. Search depth is fine."
    )
    assert crit.summary == "Quiescence is unbounded. The eval has a sign bug."
    assert crit.full.startswith("Quiescence is unbounded")


def test_parse_response_falls_back_with_one_sentence():
    """Edge case: only one sentence available, take what's there."""
    crit = _parse_response("Quiescence is unbounded.")
    assert crit.summary == "Quiescence is unbounded."
    assert crit.full == "Quiescence is unbounded."


def test_parse_response_truncates_long_summary():
    long_summary = "x" * 500
    crit = _parse_response(f"SUMMARY: {long_summary}\n\nbody")
    assert len(crit.summary) <= 280


def test_parse_response_empty_returns_empty():
    crit = _parse_response("")
    assert crit == Critique(summary="", full="")
