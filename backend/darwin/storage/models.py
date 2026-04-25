"""FROZEN CONTRACT — do not change without team sync.

SQLite schema. Owned by Person E; written to by A (engines), B (games),
and the orchestration loop (generations).
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class EngineRow(SQLModel, table=True):
    __tablename__ = "engines"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)
    generation: int = Field(index=True)
    parent_name: Optional[str] = None
    code_path: str  # absolute path to the engine module on disk
    elo: float = 1500.0
    created_at: datetime = Field(default_factory=datetime.utcnow)


class GameRow(SQLModel, table=True):
    __tablename__ = "games"

    id: Optional[int] = Field(default=None, primary_key=True)
    generation: int = Field(index=True)
    white_name: str = Field(index=True)
    black_name: str = Field(index=True)
    pgn: str
    result: str  # "1-0", "0-1", "1/2-1/2", or "*"
    termination: str  # "checkmate", "stalemate", "time", "max_moves", "error"
    created_at: datetime = Field(default_factory=datetime.utcnow)


class GenerationRow(SQLModel, table=True):
    __tablename__ = "generations"

    id: Optional[int] = Field(default=None, primary_key=True)
    number: int = Field(index=True, unique=True)
    champion_before: str
    champion_after: str
    strategist_questions_json: str  # JSON array of {category, text}
    started_at: datetime = Field(default_factory=datetime.utcnow)
    finished_at: Optional[datetime] = None
