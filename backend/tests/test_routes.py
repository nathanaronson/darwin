"""Tests for darwin.api.routes — the REST surface area.

The fixture pins SQLAlchemy to a single in-memory connection (StaticPool)
so the schema/data created in the test thread is visible to the
TestClient thread that handles the request. Mutating endpoints that
delegate to the orchestrator (``/run``, ``/stop``, ``/state/clear``) have
their downstream calls stubbed so the tests don't spawn real generations.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from darwin.api.routes import router
from darwin.storage.models import EngineRow, GameRow, GenerationRow


@pytest.fixture()
def mem_db(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr("darwin.storage.db._engine", engine)
    return engine


@pytest.fixture()
def client(mem_db) -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return TestClient(app)


def test_list_engines_empty_returns_empty_list(client):
    r = client.get("/api/engines")
    assert r.status_code == 200
    assert r.json() == []


def test_list_engines_returns_inserted_rows(client, mem_db):
    with Session(mem_db) as s:
        s.add(EngineRow(name="baseline-v0", generation=0, code_path="x"))
        s.add(EngineRow(name="gen1-search-aaaaaa", generation=1, code_path="y"))
        s.commit()

    r = client.get("/api/engines")
    assert r.status_code == 200
    names = {row["name"] for row in r.json()}
    assert names == {"baseline-v0", "gen1-search-aaaaaa"}


def test_list_generations_orders_by_number(client, mem_db):
    """Insert in scrambled order; response must be sorted by `number`."""
    with Session(mem_db) as s:
        for n in (3, 1, 2):
            s.add(GenerationRow(
                number=n,
                champion_before="a",
                champion_after="b",
                strategist_questions_json="[]",
                finished_at=datetime.utcnow(),
            ))
        s.commit()

    r = client.get("/api/generations")
    assert r.status_code == 200
    nums = [row["number"] for row in r.json()]
    assert nums == [1, 2, 3]


def test_list_games_unfiltered_returns_all(client, mem_db):
    with Session(mem_db) as s:
        for gen in (1, 2, 2, 3):
            s.add(GameRow(
                generation=gen,
                white_name="a",
                black_name="b",
                pgn="",
                result="1-0",
                termination="checkmate",
            ))
        s.commit()

    r = client.get("/api/games")
    assert r.status_code == 200
    assert len(r.json()) == 4


def test_list_games_filters_by_generation_query(client, mem_db):
    with Session(mem_db) as s:
        for gen in (1, 2, 2, 3):
            s.add(GameRow(
                generation=gen,
                white_name="a",
                black_name="b",
                pgn="",
                result="1-0",
                termination="checkmate",
            ))
        s.commit()

    r = client.get("/api/games?gen=2")
    assert r.status_code == 200
    assert len(r.json()) == 2
    assert all(row["generation"] == 2 for row in r.json())


def test_engine_code_404_for_unknown_name(client):
    r = client.get("/api/engines/does-not-exist/code")
    assert r.status_code == 404


def test_engine_code_streams_file_for_existing_engine(client, mem_db, tmp_path):
    src = tmp_path / "fake_engine.py"
    src.write_text("# fake engine\nengine = None\n")

    with Session(mem_db) as s:
        s.add(EngineRow(name="fake", generation=1, code_path=str(src)))
        s.commit()

    r = client.get("/api/engines/fake/code")
    assert r.status_code == 200
    assert "fake engine" in r.text
    assert "fake.py" in r.headers.get("content-disposition", "")


def test_engine_code_resolves_baseline_dotted_path_when_row_missing(client):
    """After /state/clear wipes the engines table, the dashboard still
    asks for baseline-v0's source. Routes must fall back to the dotted
    module path."""
    r = client.get("/api/engines/baseline-v0/code")
    assert r.status_code == 200
    assert "baseline-v0.py" in r.headers.get("content-disposition", "")
    assert "BaselineEngine" in r.text


def test_engine_code_404_when_dotted_path_unresolvable(client, mem_db):
    """A row with a bogus single-segment dotted path must surface 404."""
    with Session(mem_db) as s:
        # Single-segment name with no parent package — find_spec returns
        # None.
        s.add(EngineRow(name="ghost", generation=1, code_path="thisisnotamodule"))
        s.commit()
    r = client.get("/api/engines/ghost/code")
    assert r.status_code == 404


def test_engine_code_404_when_parent_package_missing(client, mem_db):
    """A dotted path whose intermediate package doesn't exist (e.g.
    'darwin.nope.notreal' — 'darwin.nope' is missing) raises
    ModuleNotFoundError from importlib. The route must catch it and
    return 404 instead of surfacing 500."""
    with Session(mem_db) as s:
        s.add(EngineRow(
            name="ghost",
            generation=1,
            code_path="darwin.nope.notreal",
        ))
        s.commit()
    r = client.get("/api/engines/ghost/code")
    assert r.status_code == 404


def test_run_endpoint_dispatches_to_orchestrator(client, monkeypatch):
    called = {}

    async def fake_start():
        called["was_called"] = True

    monkeypatch.setattr(
        "darwin.orchestration.generation.start_or_replace_generation_task",
        fake_start,
    )

    r = client.post("/api/generations/run")
    assert r.status_code == 200
    assert r.json() == {"started": True}
    assert called.get("was_called") is True


def test_stop_endpoint_returns_stopped_flag(client, monkeypatch):
    async def fake_stop():
        return True

    monkeypatch.setattr(
        "darwin.orchestration.generation.stop_current_generation_task",
        fake_stop,
    )

    r = client.post("/api/generations/stop")
    assert r.status_code == 200
    assert r.json() == {"stopped": True}


def test_stop_endpoint_returns_false_when_nothing_running(client, monkeypatch):
    async def fake_stop():
        return False

    monkeypatch.setattr(
        "darwin.orchestration.generation.stop_current_generation_task",
        fake_stop,
    )

    r = client.post("/api/generations/stop")
    assert r.status_code == 200
    assert r.json() == {"stopped": False}


def test_state_clear_wipes_tables_and_emits_event(client, mem_db, monkeypatch, tmp_path):
    """Insert rows, fire /clear: all three tables empty AND a state.cleared
    event hits the bus. The on-disk generated/ tree is reached via
    ``Path(__file__).parent.parent`` from routes.py — we redirect via a
    spoofed __file__ so the real engines/generated/ is untouched."""
    with Session(mem_db) as s:
        s.add(EngineRow(name="e", generation=0, code_path="x"))
        s.add(GameRow(
            generation=1, white_name="a", black_name="b",
            pgn="", result="1-0", termination="checkmate",
        ))
        s.add(GenerationRow(
            number=1, champion_before="a", champion_after="b",
            strategist_questions_json="[]",
        ))
        s.commit()

    async def fake_stop():
        return False
    monkeypatch.setattr(
        "darwin.orchestration.generation.stop_current_generation_task",
        fake_stop,
    )

    emitted: list[dict] = []

    async def fake_emit(payload):
        emitted.append(payload)
    monkeypatch.setattr("darwin.api.websocket.bus.emit", fake_emit)

    # Build a spoof tree such that
    #   Path(spoofed_file).parent.parent / "engines" / "generated"
    # resolves to a tmp directory we control. Spoofed file lives at
    # <tmp>/api/routes.py so parent.parent = <tmp>.
    api_dir = tmp_path / "api"
    api_dir.mkdir()
    generated = tmp_path / "engines" / "generated"
    generated.mkdir(parents=True)
    (generated / "_failures").mkdir()
    (generated / "candidate.py").write_text("# candidate")
    (generated / "_failures" / "log.txt").write_text("# failure log")

    import darwin.api.routes as routes_mod
    monkeypatch.setattr(routes_mod, "__file__", str(api_dir / "routes.py"))

    r = client.post("/api/state/clear")
    assert r.status_code == 200
    body = r.json()
    assert body["cleared"] is True
    assert body["deleted_engine_files"] == 1
    assert body["deleted_failure_files"] == 1

    with Session(mem_db) as s:
        assert s.exec(select(EngineRow)).all() == []
        assert s.exec(select(GameRow)).all() == []
        assert s.exec(select(GenerationRow)).all() == []

    assert any(p.get("type") == "state.cleared" for p in emitted)


def test_state_clear_handles_missing_generated_dir(client, mem_db, monkeypatch, tmp_path):
    """If the generated/ tree doesn't exist (fresh checkout), clearing
    must still succeed and report 0 deletions."""
    async def fake_stop():
        return False
    monkeypatch.setattr(
        "darwin.orchestration.generation.stop_current_generation_task",
        fake_stop,
    )

    async def fake_emit(_):
        pass
    monkeypatch.setattr("darwin.api.websocket.bus.emit", fake_emit)

    # Spoof to a tmp path where engines/generated does not exist.
    api_dir = tmp_path / "api"
    api_dir.mkdir()
    import darwin.api.routes as routes_mod
    monkeypatch.setattr(routes_mod, "__file__", str(api_dir / "routes.py"))

    r = client.post("/api/state/clear")
    assert r.status_code == 200
    body = r.json()
    assert body["deleted_engine_files"] == 0
    assert body["deleted_failure_files"] == 0
