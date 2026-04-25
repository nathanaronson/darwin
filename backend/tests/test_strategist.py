"""Tests for darwin.agents.strategist (LLM-driven version).

The strategist makes one LLM call per category in parallel. Tests mock
``complete_text`` so we don't hit a real provider. Cover:
  - 4 questions returned, one per category in CATEGORIES_USED
  - Each LLM call sees the champion source and category in its prompt
  - Past winning questions are formatted into the prompt and not the
    same text proposed again
  - LLM failures fall back to a deterministic pool (no exception
    propagates to the orchestrator)
  - Optional kwargs (runner_up_code, champion_question) are accepted
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from darwin.agents.strategist import (
    CATEGORIES_USED,
    EXAMPLE_IDEAS,
    Question,
    propose_questions,
)


async def _fake_complete_text(model, system, user, max_tokens, provider):
    # Echo the category back so tests can verify per-category dispatch
    # and that each call gets a category-specific prompt.
    for cat in CATEGORIES_USED:
        if f"Category: {cat}" in user:
            return f"proposed {cat} idea: do something specific"
    return "fallback echo"


@pytest.mark.asyncio
async def test_propose_questions_returns_one_per_category():
    with patch("darwin.agents.strategist.complete_text", _fake_complete_text):
        qs = await propose_questions(champion_code="def select_move(): pass", history=[])

    assert len(qs) == 4
    categories = [q.category for q in qs]
    assert set(categories) == set(CATEGORIES_USED)
    assert all(isinstance(q, Question) for q in qs)
    assert all(q.text.startswith("proposed ") for q in qs)


@pytest.mark.asyncio
async def test_propose_questions_includes_champion_code_in_prompt():
    captured_prompts: list[str] = []

    async def capture(model, system, user, max_tokens, provider):
        captured_prompts.append(user)
        return "x" * 50

    with patch("darwin.agents.strategist.complete_text", capture):
        await propose_questions(champion_code="MAGIC_CHAMPION_MARKER", history=[])

    assert len(captured_prompts) == len(CATEGORIES_USED)
    assert all("MAGIC_CHAMPION_MARKER" in p for p in captured_prompts)


@pytest.mark.asyncio
async def test_propose_questions_includes_past_wins():
    captured_prompts: list[str] = []

    async def capture(model, system, user, max_tokens, provider):
        captured_prompts.append(user)
        return "x" * 50

    history = [
        {
            "generation": 1,
            "champion_category": "search",
            "champion_question_text": "PAST_WINNER_TEXT_FOR_TEST",
        }
    ]
    with patch("darwin.agents.strategist.complete_text", capture):
        await propose_questions(champion_code="x", history=history)

    assert all("PAST_WINNER_TEXT_FOR_TEST" in p for p in captured_prompts)


@pytest.mark.asyncio
async def test_propose_questions_falls_back_on_llm_failure():
    async def boom(model, system, user, max_tokens, provider):
        raise RuntimeError("API down")

    with patch("darwin.agents.strategist.complete_text", boom):
        qs = await propose_questions(champion_code="x", history=[])

    assert len(qs) == len(CATEGORIES_USED)
    for q in qs:
        # Fallback texts come from the canned pool for that category.
        assert q.text in EXAMPLE_IDEAS[q.category]


@pytest.mark.asyncio
async def test_propose_questions_falls_back_on_empty_response():
    async def empty(model, system, user, max_tokens, provider):
        return "   "

    with patch("darwin.agents.strategist.complete_text", empty):
        qs = await propose_questions(champion_code="x", history=[])

    for q in qs:
        assert q.text in EXAMPLE_IDEAS[q.category]


@pytest.mark.asyncio
async def test_propose_questions_accepts_optional_kwargs():
    with patch("darwin.agents.strategist.complete_text", _fake_complete_text):
        qs = await propose_questions(
            champion_code="x",
            history=[],
            runner_up_code="y",
            champion_question={"category": "search", "text": "old"},
            generation_number=3,
        )

    assert len(qs) == len(CATEGORIES_USED)


@pytest.mark.asyncio
async def test_propose_questions_index_field_is_unique():
    with patch("darwin.agents.strategist.complete_text", _fake_complete_text):
        qs = await propose_questions(champion_code="x", history=[])

    indexes = [q.index for q in qs]
    assert sorted(indexes) == list(range(len(qs)))
