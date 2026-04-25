"""Tests for darwin.agents.strategist on the experimental pure-code branch.

The strategist is deterministic now — no LLM calls. Tests cover:
  - 4 questions returned, one per category in CATEGORIES_USED
  - All four categories distinct, all from the allowed set
  - Different generations get different question text (rotation works)
  - Optional kwargs (champion_code, runner_up_code, champion_question)
    are accepted without error and don't affect the output
"""

from __future__ import annotations

import pytest

from darwin.agents.strategist import (
    CATEGORIES_USED,
    QUESTION_POOLS,
    Question,
    propose_questions,
)


@pytest.mark.asyncio
async def test_propose_questions_returns_4_distinct_categories():
    qs = await propose_questions(champion_code="x = 1", history=[])

    assert len(qs) == 4
    categories = [q.category for q in qs]
    assert len(set(categories)) == 4
    assert set(categories) == set(CATEGORIES_USED)
    assert all(isinstance(q, Question) for q in qs)
    assert all(len(q.text) >= 20 for q in qs)


@pytest.mark.asyncio
async def test_propose_questions_rotates_with_history_length():
    """Different gen numbers (encoded as len(history)) must hit different
    pool entries. With pools of size >=4, gen 1 and gen 2 should differ."""
    qs1 = await propose_questions(champion_code="x = 1", history=[])
    qs2 = await propose_questions(
        champion_code="x = 1", history=[{"generation": 1}]
    )

    movable = [c for c in CATEGORIES_USED if len(QUESTION_POOLS[c]) > 1]
    assert movable, "expected at least one rotating pool"

    cat_to_text_1 = {q.category: q.text for q in qs1}
    cat_to_text_2 = {q.category: q.text for q in qs2}
    for cat in movable:
        assert cat_to_text_1[cat] != cat_to_text_2[cat], (
            f"category {cat} did not rotate between gen 1 and gen 2"
        )


@pytest.mark.asyncio
async def test_propose_questions_accepts_optional_kwargs():
    """The signature retains the LLM-era kwargs for orchestrator
    compatibility, but they're ignored in the deterministic path."""
    qs_no_extras = await propose_questions(champion_code="x = 1", history=[])
    qs_with_extras = await propose_questions(
        champion_code="x = 1",
        history=[],
        runner_up_code="y = 2",
        champion_question={"category": "search", "text": "old question"},
    )

    assert [q.text for q in qs_no_extras] == [q.text for q in qs_with_extras]


@pytest.mark.asyncio
async def test_propose_questions_index_field_is_unique():
    qs = await propose_questions(champion_code="x = 1", history=[])
    indexes = [q.index for q in qs]
    assert sorted(indexes) == list(range(len(qs)))


@pytest.mark.asyncio
async def test_explicit_generation_number_overrides_history_length():
    """When the orchestrator passes generation_number=N, that beats
    len(history)+1 — so a stale/empty history doesn't pin the rotation
    to gen 1."""
    qs_gen5_via_history = await propose_questions(
        champion_code="x", history=[{"generation": i} for i in range(4)]
    )
    qs_gen5_explicit = await propose_questions(
        champion_code="x", history=[], generation_number=5
    )
    by_cat_history = {q.category: q.text for q in qs_gen5_via_history}
    by_cat_explicit = {q.category: q.text for q in qs_gen5_explicit}
    # Both routes should pick the same pool entries: gen 5 with no
    # winning bias hits index (5-1)=4 % len(pool) for each category.
    for cat in by_cat_history:
        assert by_cat_history[cat] == by_cat_explicit[cat]


@pytest.mark.asyncio
async def test_winning_category_advances_pointer_one_extra_step():
    """A champion in 'search' should advance search's rotation pointer
    one step beyond the gen-number-only baseline. With two history
    entries, both winning in 'search', search's text should be the
    SAME as gen 4's plain rotation (gen 3 + 2 wins = 5 ≡ gen 5)."""
    base_gen3 = await propose_questions(
        champion_code="x", history=[], generation_number=3
    )
    biased = await propose_questions(
        champion_code="x",
        history=[
            {"generation": 1, "champion_category": "search"},
            {"generation": 2, "champion_category": "search"},
        ],
        generation_number=3,
    )
    cat_to_text = {q.category: q.text for q in base_gen3}
    biased_to_text = {q.category: q.text for q in biased}

    # 'search' should differ from baseline (winning bias kicks in).
    assert biased_to_text["search"] != cat_to_text["search"]
    # Other categories still rotate by gen number alone — unchanged.
    for cat in ("evaluation", "book", "sampling"):
        assert biased_to_text[cat] == cat_to_text[cat]


@pytest.mark.asyncio
async def test_history_with_unknown_category_is_ignored():
    """A champion_category outside CATEGORIES_USED ('prompt' was dropped)
    must not crash and must not bias any pool."""
    base = await propose_questions(
        champion_code="x", history=[], generation_number=2
    )
    with_garbage_history = await propose_questions(
        champion_code="x",
        history=[{"generation": 1, "champion_category": "prompt"}],
        generation_number=2,
    )
    # Identical output — the unknown 'prompt' category is filtered out.
    assert [q.text for q in base] == [q.text for q in with_garbage_history]


@pytest.mark.asyncio
async def test_each_pool_entry_eventually_appears_within_one_full_cycle():
    """Across the largest pool size's worth of consecutive generations,
    every pool entry for that category must surface at least once."""
    # Find the longest pool to bound the cycle.
    longest_cat = max(CATEGORIES_USED, key=lambda c: len(QUESTION_POOLS[c]))
    cycle = len(QUESTION_POOLS[longest_cat])

    seen: set[str] = set()
    for gen in range(1, cycle + 1):
        qs = await propose_questions(
            champion_code="x", history=[], generation_number=gen
        )
        for q in qs:
            if q.category == longest_cat:
                seen.add(q.text)

    assert seen == set(QUESTION_POOLS[longest_cat])


@pytest.mark.asyncio
async def test_question_text_matches_chosen_pool():
    """Every returned question's text must come from the pool for its
    category — no cross-pollution."""
    qs = await propose_questions(
        champion_code="x", history=[], generation_number=1
    )
    for q in qs:
        assert q.text in QUESTION_POOLS[q.category]
