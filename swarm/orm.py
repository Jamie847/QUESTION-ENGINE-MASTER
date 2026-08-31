from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.sqlite import JSON as SQLITE_JSON
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import JSON


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSON, list[Any]: JSON}


JSONType = JSON().with_variant(SQLITE_JSON(), "sqlite")


class RunRow(Base):
    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32), default="running")
    current_stage: Mapped[str] = mapped_column(String(64), default="")
    error: Mapped[str | None] = mapped_column(Text)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    budget_usd: Mapped[float] = mapped_column(Float, default=2.0)
    degraded: Mapped[bool] = mapped_column(Boolean, default=False)
    warnings: Mapped[list[Any]] = mapped_column(JSONType, default=list)
    source_health: Mapped[list[Any]] = mapped_column(JSONType, default=list)
    stages: Mapped[list[Any]] = mapped_column(JSONType, default=list)

    briefs: Mapped[list[BriefRow]] = relationship(back_populates="run")
    intersections: Mapped[list[IntersectionRow]] = relationship(back_populates="run")
    questions: Mapped[list[QuestionRow]] = relationship(back_populates="run")
    digest: Mapped[DigestRow | None] = relationship(back_populates="run")


class SignalRow(Base):
    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"), index=True)
    source: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text, default="")
    snippet: Mapped[str] = mapped_column(Text, default="")
    score: Mapped[float] = mapped_column(Float, default=0.0)
    vertical_hints: Mapped[list[Any]] = mapped_column(JSONType, default=list)
    raw: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class BriefRow(Base):
    __tablename__ = "briefs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"), index=True)
    vertical: Mapped[str] = mapped_column(String(32), index=True)
    headline: Mapped[str] = mapped_column(Text)
    what_is_happening: Mapped[str] = mapped_column(Text, default="")
    why_now: Mapped[str] = mapped_column(Text, default="")
    who_is_affected: Mapped[str] = mapped_column(Text, default="")
    velocity: Mapped[str] = mapped_column(String(32), default="unknown")
    sources: Mapped[list[Any]] = mapped_column(JSONType, default=list)
    raw_signals: Mapped[list[Any]] = mapped_column(JSONType, default=list)
    score: Mapped[float] = mapped_column(Float, default=0.0)

    run: Mapped[RunRow] = relationship(back_populates="briefs")


class IntersectionRow(Base):
    __tablename__ = "intersections"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"), index=True)
    verticals: Mapped[list[Any]] = mapped_column(JSONType, default=list)
    thesis: Mapped[str] = mapped_column(Text)
    surprise: Mapped[float] = mapped_column(Float, default=0.0)
    plausibility: Mapped[float] = mapped_column(Float, default=0.0)
    coverage: Mapped[str] = mapped_column(String(32), default="unknown")
    coverage_notes: Mapped[str] = mapped_column(Text, default="")
    accepted: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    reject_reason: Mapped[str] = mapped_column(Text, default="")
    brief_ids: Mapped[list[Any]] = mapped_column(JSONType, default=list)

    run: Mapped[RunRow] = relationship(back_populates="intersections")


class QuestionRow(Base):
    __tablename__ = "questions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"), index=True)
    text: Mapped[str] = mapped_column(Text)
    lens: Mapped[str] = mapped_column(String(32), index=True)
    verticals: Mapped[list[Any]] = mapped_column(JSONType, default=list)
    coverage: Mapped[str] = mapped_column(String(32), default="unknown")
    decay_class: Mapped[str] = mapped_column(String(32), default="slow")
    status: Mapped[str] = mapped_column(String(32), default="raw", index=True)
    rank: Mapped[int | None] = mapped_column(Integer)
    kill_reason: Mapped[str] = mapped_column(Text, default="")
    duplicate_of: Mapped[str | None] = mapped_column(String(64))
    brief_ids: Mapped[list[Any]] = mapped_column(JSONType, default=list)
    intersection_id: Mapped[str | None] = mapped_column(String(64))
    context: Mapped[str] = mapped_column(Text, default="")
    promoted: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    run: Mapped[RunRow] = relationship(back_populates="questions")
    ratings: Mapped[list[RatingRow]] = relationship(back_populates="question")


class RatingRow(Base):
    __tablename__ = "ratings"
    __table_args__ = (UniqueConstraint("question_id", name="uq_rating_question"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    question_id: Mapped[str] = mapped_column(ForeignKey("questions.id"), index=True)
    stars: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    question: Mapped[QuestionRow] = relationship(back_populates="ratings")


class DigestRow(Base):
    __tablename__ = "digests"
    __table_args__ = (UniqueConstraint("date", name="uq_digest_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"), index=True)
    date: Mapped[str] = mapped_column(String(16), index=True)
    title: Mapped[str] = mapped_column(Text)
    markdown: Mapped[str] = mapped_column(Text)
    top_ids: Mapped[list[Any]] = mapped_column(JSONType, default=list)
    curated_count: Mapped[int] = mapped_column(Integer, default=0)
    killed_count: Mapped[int] = mapped_column(Integer, default=0)
    rejected_intersection_count: Mapped[int] = mapped_column(Integer, default=0)
    degraded: Mapped[bool] = mapped_column(Boolean, default=False)
    warnings: Mapped[list[Any]] = mapped_column(JSONType, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    run: Mapped[RunRow] = relationship(back_populates="digest")


class RunLockRow(Base):
    __tablename__ = "run_locks"

    name: Mapped[str] = mapped_column(String(32), primary_key=True)
    run_id: Mapped[int | None] = mapped_column(Integer)
    acquired_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
