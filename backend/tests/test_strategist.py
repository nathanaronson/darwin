"""Tests for darwin.agents.strategist (LLM-based)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from darwin.agents.strategist import (
    CATEGORIES_USED,
    EXAMPLE_IDEAS,
    Question,
    propose_questions,
)


@pytest.mark.asyncio
async def test_propose_questions_returns_one_per_category():
    with patch(
        "darwin.agents.strategist.complete_text",
        new=AsyncMock(return_value="stub proposal text"),
    ):
        qs = await propose_questions(champion_code="x = 1", history=[])

    assert len(qs) == len(CATEGORIES_USED)
    assert [q.category for q in qs] == list(CATEGORIES_USED)
    assert all(isinstance(q, Question) for q in qs)
    assert all(q.text == "stub proposal text" for q in qs)
    assert sorted(q.index for q in qs) == list(range(len(CATEGORIES_USED)))


@pytest.mark.asyncio
async def test_prompt_contains_chosen_category_examples_and_past_wins():
    captured: list[dict] = []

    async def _capture(model, system, user, max_tokens, provider):
        captured.append({"system": system, "user": user})
        return "stub"

    history = [
        {
            "generation": 1,
            "champion_category": "search",
            "champion_question_text": "Add iterative deepening to depth 4.",
        },
        {
            "generation": 2,
            "champion_category": "evaluation",
            "champion_question_text": "Add a king-safety penalty term.",
        },
    ]

    with patch(
        "darwin.agents.strategist.complete_text", side_effect=_capture
    ):
        await propose_questions(champion_code="x = 1", history=history)

    user_prompts_by_category = {
        cat: captured[i]["user"] for i, cat in enumerate(CATEGORIES_USED)
    }

    for cat, prompt in user_prompts_by_category.items():
        assert f"Category: {cat}" in prompt
        assert "Add iterative deepening to depth 4." in prompt
        assert "Add a king-safety penalty term." in prompt
        for example in EXAMPLE_IDEAS[cat]:
            assert example in prompt
        # Examples for *other* categories should not leak in.
        for other in CATEGORIES_USED:
            if other == cat:
                continue
            for example in EXAMPLE_IDEAS[other]:
                assert example not in prompt


@pytest.mark.asyncio
async def test_prompt_handles_empty_history():
    captured: list[str] = []

    async def _capture(model, system, user, max_tokens, provider):
        captured.append(user)
        return "stub"

    with patch(
        "darwin.agents.strategist.complete_text", side_effect=_capture
    ):
        await propose_questions(champion_code="x = 1", history=[])

    assert captured, "expected at least one LLM call"
    for prompt in captured:
        assert "(no prior winners yet)" in prompt


@pytest.mark.asyncio
async def test_calls_run_in_parallel():
    """All category prompts dispatch through asyncio.gather, so the total
    latency should be ~one call's worth, not the sum."""
    import asyncio
    import time

    async def _slow(model, system, user, max_tokens, provider):
        await asyncio.sleep(0.1)
        return "stub"

    with patch(
        "darwin.agents.strategist.complete_text", side_effect=_slow
    ):
        t0 = time.monotonic()
        await propose_questions(champion_code="x = 1", history=[])
        elapsed = time.monotonic() - t0

    # 4 sequential calls would take ~0.4s; gathered should take ~0.1s.
    assert elapsed < 0.3, f"calls did not run in parallel (took {elapsed:.2f}s)"
