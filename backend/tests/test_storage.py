"""Tests for darwin.storage (db.py + models.py).

These exercise schema invariants on an in-memory SQLite engine so the
real ``darwin.db`` file is never touched.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, SQLModel, create_engine, select

from darwin.storage.db import init_db
from darwin.storage.models import EngineRow, GameRow, GenerationRow


@pytest.fixture()
def mem_db(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr("darwin.storage.db._engine", engine)
    return engine


def test_init_db_is_idempotent(monkeypatch):
    """Calling init_db multiple times must not raise or duplicate tables."""
    engine = create_engine("sqlite:///:memory:")
    monkeypatch.setattr("darwin.storage.db._engine", engine)

    init_db()
    init_db()
    init_db()

    # Verify a known table exists by inserting a row.
    with Session(engine) as s:
        s.add(EngineRow(name="probe", generation=0, code_path="x"))
        s.commit()
        rows = s.exec(select(EngineRow)).all()
        assert len(rows) == 1


def test_engine_row_default_elo_is_1500(mem_db):
    """Default rating must be 1500.0 — the seed value the chart anchors on."""
    with Session(mem_db) as s:
        s.add(EngineRow(name="probe", generation=0, code_path="x"))
        s.commit()
        row = s.exec(select(EngineRow).where(EngineRow.name == "probe")).first()
        assert row is not None
        assert row.elo == 1500.0


def test_engine_row_created_at_is_set(mem_db):
    """created_at default_factory must populate on insert."""
    before = datetime.utcnow()
    with Session(mem_db) as s:
        s.add(EngineRow(name="probe", generation=0, code_path="x"))
        s.commit()
        row = s.exec(select(EngineRow).where(EngineRow.name == "probe")).first()
    assert row.created_at >= before


def test_engine_name_is_unique(mem_db):
    """The unique=True constraint on name must reject duplicates."""
    with Session(mem_db) as s:
        s.add(EngineRow(name="dup", generation=0, code_path="x"))
        s.commit()

        s.add(EngineRow(name="dup", generation=1, code_path="y"))
        with pytest.raises(IntegrityError):
            s.commit()


def test_generation_number_is_unique(mem_db):
    """Two GenerationRow entries with the same number must be rejected."""
    with Session(mem_db) as s:
        s.add(GenerationRow(
            number=1,
            champion_before="a",
            champion_after="b",
            strategist_questions_json="[]",
        ))
        s.commit()

        s.add(GenerationRow(
            number=1,
            champion_before="x",
            champion_after="y",
            strategist_questions_json="[]",
        ))
        with pytest.raises(IntegrityError):
            s.commit()


def test_generation_finished_at_is_optional(mem_db):
    """An in-flight generation has finished_at=None until completion."""
    with Session(mem_db) as s:
        s.add(GenerationRow(
            number=1,
            champion_before="a",
            champion_after="a",
            strategist_questions_json="[]",
        ))
        s.commit()
        row = s.exec(select(GenerationRow).where(GenerationRow.number == 1)).first()
        assert row.finished_at is None


def test_game_row_round_trips_pgn(mem_db):
    """PGN string with newlines/special chars must persist verbatim."""
    pgn = (
        '[Event "?"]\n[White "a"]\n[Black "b"]\n[Result "1-0"]\n\n'
        "1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 1-0"
    )
    with Session(mem_db) as s:
        s.add(GameRow(
            generation=1,
            white_name="a",
            black_name="b",
            pgn=pgn,
            result="1-0",
            termination="checkmate",
        ))
        s.commit()
        row = s.exec(select(GameRow)).first()
        assert row.pgn == pgn


def test_filter_games_by_generation(mem_db):
    with Session(mem_db) as s:
        for gen in (1, 1, 2, 3, 3, 3):
            s.add(GameRow(
                generation=gen,
                white_name="a",
                black_name="b",
                pgn="",
                result="1-0",
                termination="checkmate",
            ))
        s.commit()

        gen3 = s.exec(select(GameRow).where(GameRow.generation == 3)).all()
        assert len(gen3) == 3


def test_engine_row_parent_name_can_be_null(mem_db):
    """The seeded baseline has parent_name=None; nothing else relies on it."""
    with Session(mem_db) as s:
        s.add(EngineRow(name="root", generation=0, code_path="x", parent_name=None))
        s.commit()
        row = s.exec(select(EngineRow).where(EngineRow.name == "root")).first()
        assert row.parent_name is None
