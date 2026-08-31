"""Pydantic contracts for every swarm artifact."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class Velocity(str, Enum):
    accelerating = "accelerating"
    steady = "steady"
    peaked = "peaked"
    unknown = "unknown"


class Coverage(str, Enum):
    none = "none"
    thin = "thin"
    crowded = "crowded"
    unknown = "unknown"


class DecayClass(str, Enum):
    fast = "fast"
    slow = "slow"
    evergreen = "evergreen"


class QuestionStatus(str, Enum):
    raw = "raw"
    duplicate = "duplicate"
    killed = "killed"
    curated = "curated"


class RunStatus(str, Enum):
    running = "running"
    completed = "completed"
    failed = "failed"
    degraded = "degraded"


class StageName(str, Enum):
    fetch = "fetch"
    scout = "scout"
    cross_pollinate = "cross_pollinate"
    smith = "smith"
    dedup = "dedup"
    curate = "curate"
    archive = "archive"


class Signal(BaseModel):
    source: str
    title: str
    url: str = ""
    snippet: str = ""
    score: float = 0.0
    vertical_hints: list[str] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)

    @field_validator("title")
    @classmethod
    def title_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("signal title is empty")
        return v


class SourceHealth(BaseModel):
    source: str
    ok: bool
    count: int = 0
    error: str | None = None
    elapsed_ms: int = 0


class Brief(BaseModel):
    id: str
    vertical: str
    headline: str
    what_is_happening: str
    why_now: str
    who_is_affected: str
    velocity: Velocity = Velocity.unknown
    sources: list[str] = Field(default_factory=list)
    raw_signals: list[str] = Field(default_factory=list)
    score: float = 0.0


class Intersection(BaseModel):
    id: str
    verticals: list[str]
    thesis: str
    surprise: float = Field(ge=0, le=1)
    plausibility: float = Field(ge=0, le=1)
    coverage: Coverage = Coverage.unknown
    coverage_notes: str = ""
    accepted: bool = True
    reject_reason: str = ""
    brief_ids: list[str] = Field(default_factory=list)


class Question(BaseModel):
    id: str
    text: str
    lens: str
    verticals: list[str] = Field(default_factory=list)
    coverage: Coverage = Coverage.unknown
    decay_class: DecayClass = DecayClass.slow
    status: QuestionStatus = QuestionStatus.raw
    rank: int | None = None
    kill_reason: str = ""
    duplicate_of: str | None = None
    brief_ids: list[str] = Field(default_factory=list)
    intersection_id: str | None = None
    context: str = ""

    @field_validator("text")
    @classmethod
    def text_is_questionish(cls, v: str) -> str:
        v = " ".join(v.split())
        if len(v) < 20:
            raise ValueError("question too short")
        return v


class TasteExample(BaseModel):
    stars: int = Field(ge=1, le=5)
    question: str
    why: str = ""
    keep: bool = True


class TasteProfile(BaseModel):
    generated_at: datetime | None = None
    preferred_lenses: list[str] = Field(default_factory=list)
    preferred_verticals: list[str] = Field(default_factory=list)
    anti_patterns: list[str] = Field(default_factory=list)
    keep_exemplars: list[TasteExample] = Field(default_factory=list)
    kill_exemplars: list[TasteExample] = Field(default_factory=list)
    notes: str = ""


class DigestDoc(BaseModel):
    date: str
    title: str
    markdown: str
    top_ids: list[str] = Field(default_factory=list)
    curated_count: int = 0
    killed_count: int = 0
    rejected_intersection_count: int = 0
    degraded: bool = False
    warnings: list[str] = Field(default_factory=list)
