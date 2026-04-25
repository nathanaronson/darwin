"""Tests for cubist.orchestration.generation.run_generation_task."""
from __future__ import annotations

from datetime import datetime

import pytest
from sqlmodel import Session, SQLModel, create_engine

from cubist.storage.models import EngineRow, GenerationRow


class FakeEngine:
    def __init__(self, name: str) -> None:
        self.name = name
        self.generation = 1
        self.lineage: list[str] = []

    async def select_move(self, board, time_remaining_ms):  # pragma: no cover
        raise NotImplementedError


@pytest.fixture()
def mem_db(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr("cubist.storage.db._engine", engine)
    return engine


@pytest.mark.asyncio
async def test_run_generation_task_resumes_from_last_champion(mem_db, monkeypatch):
    """After gen 1, the API path must start gen 2 from gen 1's champion."""
    gen1_winner = "gen1_prompt_abc123"
    gen1_path = "/absolute/path/gen1_prompt_abc123.py"

    with Session(mem_db) as s:
        s.add(GenerationRow(
            number=1,
            champion_before="baseline-v0",
            champion_after=gen1_winner,
            strategist_questions_json="[]",
            finished_at=datetime.utcnow(),
        ))
        s.add(EngineRow(
            name=gen1_winner,
            generation=1,
            parent_name="baseline-v0",
            code_path=gen1_path,
        ))
        s.commit()

    fake_champion = FakeEngine(gen1_winner)
    monkeypatch.setattr(
        "cubist.orchestration.generation.load_engine",
        lambda path: fake_champion,
    )

    called: dict = {}

    async def fake_run_generation(champion, generation_number):
        called["champion"] = champion
        called["generation_number"] = generation_number
        return champion

    monkeypatch.setattr(
        "cubist.orchestration.generation.run_generation",
        fake_run_generation,
    )

    from cubist.orchestration.generation import run_generation_task

    await run_generation_task()

    assert called["champion"].name == gen1_winner
    assert called["generation_number"] == 2


@pytest.mark.asyncio
async def test_run_generation_task_first_run_uses_baseline(mem_db, monkeypatch):
    """With an empty DB, the first generation must start from baseline-v0."""
    called: dict = {}

    async def fake_run_generation(champion, generation_number):
        called["champion"] = champion
        called["generation_number"] = generation_number
        return champion

    monkeypatch.setattr(
        "cubist.orchestration.generation.run_generation",
        fake_run_generation,
    )

    from cubist.orchestration.generation import run_generation_task

    await run_generation_task()

    assert called["champion"].name == "baseline-v0"
    assert called["generation_number"] == 1
