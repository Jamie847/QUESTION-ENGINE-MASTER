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
    curated_by: Mapped[str] = mapped_column(String(128), default="")
    scout_seen: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    git_commit: Mapped[str] = mapped_column(String(64), default="")

    briefs: Mapped[list[BriefRow]] = relationship(back_populates="run")
    intersections: Mapped[list[IntersectionRow]] = relationship(back_populates="run")
    questions: Mapped[list[QuestionRow]] = relationship(back_populates="run")
    digest: Mapped[DigestRow | None] = relationship(back_populates="run")
    agent_calls: Mapped[list["AgentCallRow"]] = relationship(back_populates="run")


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
    written_by: Mapped[str] = mapped_column(String(128), default="")

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
    written_by: Mapped[str] = mapped_column(String(128), default="")

    run: Mapped[RunRow] = relationship(back_populates="intersections")


class QuestionRow(Base):
    __tablename__ = "questions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"), index=True)
    text: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text, default="")
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
    promoted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    provenance: Mapped[str] = mapped_column(String(32), default="linked")
    written_by: Mapped[str] = mapped_column(String(128), default="")
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
    why: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    question: Mapped[QuestionRow] = relationship(back_populates="ratings")


class DigestRow(Base):
    __tablename__ = "digests"
    __table_args__ = (UniqueConstraint("run_id", name="uq_digest_run"),)

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


class AgentCallRow(Base):
    """One row per LLM call. Spec §7 / §10 Phase 1. CP 2026-09-08."""

    __tablename__ = "agent_calls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"), index=True)
    agent: Mapped[str] = mapped_column(String(64), index=True, default="")
    model: Mapped[str] = mapped_column(String(128), default="")
    ok: Mapped[bool] = mapped_column(Boolean, default=False)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str] = mapped_column(Text, default="")
    stop_reason: Mapped[str] = mapped_column(String(64), default="")
    parsed_count: Mapped[int | None] = mapped_column(Integer)
    dropped_count: Mapped[int | None] = mapped_column(Integer)
    input_text: Mapped[str] = mapped_column(Text, default="")
    output_text: Mapped[str] = mapped_column(Text, default="")
    retry_of: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    run: Mapped[RunRow] = relationship(back_populates="agent_calls")


class KillReasonRow(Base):
    """Labelled curator kills. A rendered page is not a corpus."""

    __tablename__ = "kill_reasons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    question_id: Mapped[str] = mapped_column(String(64), index=True)
    run_id: Mapped[int] = mapped_column(Integer, index=True)
    label: Mapped[str] = mapped_column(String(64), index=True, default="other")
    reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class DeployMarkerRow(Base):
    """One-shot deploy steps. A row means that step already ran."""

    __tablename__ = "deploy_markers"

    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    detail: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    ran_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class OperatorAssetsRow(Base):
    """Operator-written. The system never fills these fields."""

    __tablename__ = "operator_assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    businesses: Mapped[str] = mapped_column(Text, default="")
    reach: Mapped[str] = mapped_column(Text, default="")
    skills: Mapped[str] = mapped_column(Text, default="")
    capital_time: Mapped[str] = mapped_column(Text, default="")
    wont_do: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OpportunityRow(Base):
    __tablename__ = "opportunities"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[int] = mapped_column(Integer, index=True)
    question_id: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), default="completed", index=True)
    skip_reason: Mapped[str] = mapped_column(Text, default="")
    claims: Mapped[list[Any]] = mapped_column(JSONType, default=list)
    whats_actually_true: Mapped[str] = mapped_column(Text, default="")
    shapes: Mapped[list[Any]] = mapped_column(JSONType, default=list)
    picked_shape: Mapped[str] = mapped_column(String(64), default="")
    who_has_problem: Mapped[str] = mapped_column(Text, default="")
    who_pays: Mapped[str] = mapped_column(Text, default="")
    what_they_use_today: Mapped[str] = mapped_column(Text, default="")
    why_now: Mapped[str] = mapped_column(Text, default="")
    how_it_charges: Mapped[str] = mapped_column(Text, default="")
    rivals: Mapped[str] = mapped_column(Text, default="")
    commentators: Mapped[str] = mapped_column(Text, default="")
    first_prospects: Mapped[list[Any]] = mapped_column(JSONType, default=list)
    pages_read: Mapped[list[Any]] = mapped_column(JSONType, default=list)
    queries_run: Mapped[list[Any]] = mapped_column(JSONType, default=list)
    fit: Mapped[str] = mapped_column(Text, default="")
    weekend_test: Mapped[str] = mapped_column(Text, default="")
    why_it_might_fail: Mapped[str] = mapped_column(Text, default="")
    red_flags: Mapped[list[Any]] = mapped_column(JSONType, default=list)
    check_note: Mapped[str] = mapped_column(Text, default="")
    written_by: Mapped[str] = mapped_column(String(128), default="")
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    on_demand: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    searches: Mapped[list[Any]] = mapped_column(JSONType, default=list)
    latest_verdict: Mapped[str] = mapped_column(String(16), default="")
    latest_verdict_why: Mapped[str] = mapped_column(Text, default="")
    latest_verdict_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    related_from_memory: Mapped[list[Any]] = mapped_column(JSONType, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class OpportunityVerdictRow(Base):
    __tablename__ = "opportunity_verdicts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    opportunity_id: Mapped[str] = mapped_column(
        ForeignKey("opportunities.id", ondelete="CASCADE"), index=True
    )
    verdict: Mapped[str] = mapped_column(String(16), index=True)
    why: Mapped[str] = mapped_column(Text, default="")
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class MemoryItemRow(Base):
    """Derived card catalog. Raw text stays in its own tables (WO-014)."""

    __tablename__ = "memory_items"
    __table_args__ = (UniqueConstraint("kind", "ref_id", name="uq_memory_kind_ref"),)

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    ref_id: Mapped[str] = mapped_column(String(64), index=True)
    text: Mapped[str] = mapped_column(Text, default="")
    title: Mapped[str] = mapped_column(Text, default="")
    run_id: Mapped[int] = mapped_column(Integer, index=True, default=0)
    item_date: Mapped[str] = mapped_column(String(16), index=True, default="")
    verticals: Mapped[list[Any]] = mapped_column(JSONType, default=list)
    source_urls: Mapped[list[Any]] = mapped_column(JSONType, default=list)
    embedding: Mapped[list[Any]] = mapped_column(JSONType, default=list)
    embed_model: Mapped[str] = mapped_column(String(64), index=True, default="")
    embed_dims: Mapped[int] = mapped_column(Integer, default=0)
    verdict: Mapped[str] = mapped_column(String(16), default="")
    verdict_why: Mapped[str] = mapped_column(Text, default="")
    embedded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class MemorySearchDayRow(Base):
    """Public Archive search meter. One row per UTC day."""

    __tablename__ = "memory_search_days"

    day: Mapped[str] = mapped_column(String(16), primary_key=True)
    count: Mapped[int] = mapped_column(Integer, default=0)


class RunLockRow(Base):
    __tablename__ = "run_locks"

    name: Mapped[str] = mapped_column(String(32), primary_key=True)
    run_id: Mapped[int | None] = mapped_column(Integer)
    acquired_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class IssueRow(Base):
    """Correspondent draft. Always a draft. There is no published state.

    Spec §6's no-approval rule is for the private digest. Do not add a
    published_at column or a send path to 'finish' this table.
    """

    __tablename__ = "issues"
    __table_args__ = (UniqueConstraint("week_ending", name="uq_issue_week"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    week_ending: Mapped[str] = mapped_column(String(16), index=True)
    question_id: Mapped[str] = mapped_column(String(64), index=True)
    selection_rule: Mapped[str] = mapped_column(String(32))
    selection_note: Mapped[str] = mapped_column(Text, default="")
    title: Mapped[str] = mapped_column(Text)
    markdown: Mapped[str] = mapped_column(Text)
    word_count: Mapped[int] = mapped_column(Integer, default=0)
    voice_ready: Mapped[bool] = mapped_column(Boolean, default=False)
    publish_gate_open: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(16), default="draft")
    warnings: Mapped[list[Any]] = mapped_column(JSONType, default=list)
    source_urls: Mapped[list[Any]] = mapped_column(JSONType, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
