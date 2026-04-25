"""Tests for cubist.agents.strategist.

We mock ``cubist.llm.complete`` so the test suite never hits the
Anthropic API. The mock returns a single ``tool_use`` block whose
``input`` matches the real submit_questions schema.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from cubist.agents.strategist import CATEGORIES, Question, propose_questions


def _fake_tool_use_block(payload: dict) -> SimpleNamespace:
    """Build a stand-in for an Anthropic ContentBlock of type=tool_use."""
    return SimpleNamespace(type="tool_use", name="submit_questions", input=payload)


def _fake_text_block(text: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=text)


@pytest.mark.asyncio
async def test_propose_questions_happy_path(monkeypatch):
    """Strategist returns one Question per locked category in order."""
    payload = {
        "questions": [
            {"category": cat, "text": f"Make the {cat} better please" * 2}
            for cat in CATEGORIES
        ]
    }

    async def fake_complete(**kwargs):
        return [_fake_text_block("Sure thing"), _fake_tool_use_block(payload)]

    monkeypatch.setattr("cubist.agents.strategist.complete", fake_complete)

    qs = await propose_questions(champion_code="x = 1", history=[])

    assert len(qs) == 5
    assert {q.category for q in qs} == set(CATEGORIES)
    assert all(isinstance(q, Question) for q in qs)
    assert all(len(q.text) >= 20 for q in qs)


@pytest.mark.asyncio
async def test_propose_questions_dedupes_repeated_category(monkeypatch):
    """Two prompt-categories: the first wins, the second is dropped, raising."""
    payload = {
        "questions": [
            {"category": "prompt", "text": "first prompt question is fine"},
            {"category": "prompt", "text": "second prompt question is fine"},
            {"category": "search", "text": "search idea is fine and proper"},
            {"category": "book", "text": "book idea is fine and proper"},
            {"category": "evaluation", "text": "evaluation idea is fine"},
        ]
    }

    async def fake_complete(**kwargs):
        return [_fake_tool_use_block(payload)]

    monkeypatch.setattr("cubist.agents.strategist.complete", fake_complete)

    with pytest.raises(ValueError, match="distinct categories"):
        await propose_questions(champion_code="x = 1", history=[])


@pytest.mark.asyncio
async def test_propose_questions_parses_json_without_tool_use(monkeypatch):
    """Gemini may return schema-shaped text instead of a tool call."""

    payload = {
        "questions": [
            {"category": cat, "text": f"valid fallback question for {cat} category"}
            for cat in CATEGORIES
        ]
    }

    async def fake_complete(**kwargs):
        return [_fake_text_block(f"```json\n{payload!r}\n```".replace("'", '"'))]

    monkeypatch.setattr("cubist.agents.strategist.complete", fake_complete)

    qs = await propose_questions(champion_code="x = 1", history=[])

    assert len(qs) == 5
    assert {q.category for q in qs} == set(CATEGORIES)


@pytest.mark.asyncio
async def test_propose_questions_parses_labeled_text_without_tool_use(monkeypatch):
    """Plain labeled text is accepted as a second fallback."""
    text = "\n".join(
        f"{cat}: valid fallback question for {cat} category" for cat in CATEGORIES
    )

    async def fake_complete(**kwargs):
        return [_fake_text_block(text)]

    monkeypatch.setattr("cubist.agents.strategist.complete", fake_complete)

    qs = await propose_questions(champion_code="x = 1", history=[])

    assert len(qs) == 5
    assert {q.category for q in qs} == set(CATEGORIES)


@pytest.mark.asyncio
async def test_propose_questions_rejects_unparseable_no_tool_use(monkeypatch):
    """Unstructured text without a tool_use block still surfaces a clear error."""

    async def fake_complete(**kwargs):
        return [_fake_text_block("I refuse to use the tool.")]

    monkeypatch.setattr("cubist.agents.strategist.complete", fake_complete)

    with pytest.raises(RuntimeError, match="parseable questions"):
        await propose_questions(champion_code="x = 1", history=[])


@pytest.mark.asyncio
async def test_propose_questions_passes_history_into_prompt(monkeypatch):
    """The user prompt should include the JSON-encoded history."""
    captured: dict = {}
    payload = {
        "questions": [
            {"category": cat, "text": f"valid question for {cat} category"}
            for cat in CATEGORIES
        ]
    }

    async def fake_complete(**kwargs):
        captured.update(kwargs)
        return [_fake_tool_use_block(payload)]

    monkeypatch.setattr("cubist.agents.strategist.complete", fake_complete)

    history = [{"generation": 1, "champion": "baseline-v0", "delta": 0.0}]
    await propose_questions(champion_code="x = 1", history=history)

    assert "baseline-v0" in captured["user"]
    assert "delta" in captured["user"]
