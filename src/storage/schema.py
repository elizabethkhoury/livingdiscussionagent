from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.storage.db import Base


class ThreadRecord(Base):
    __tablename__ = "threads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    platform_thread_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    platform: Mapped[str] = mapped_column(String(32), default="reddit")
    subreddit: Mapped[str] = mapped_column(String(128), index=True)
    title: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text, default="")
    url: Mapped[str] = mapped_column(Text)
    author: Mapped[str] = mapped_column(String(128), default="")
    created_at_platform: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=datetime.utcnow)

    comments: Mapped[list[ThreadCommentRecord]] = relationship(back_populates="thread")
    classifications: Mapped[list[ClassificationRecord]] = relationship(back_populates="thread")


class ThreadCommentRecord(Base):
    __tablename__ = "thread_comments"
    __table_args__ = (UniqueConstraint("platform_comment_id", name="uq_thread_comment_platform"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    platform_comment_id: Mapped[str] = mapped_column(String(64), index=True)
    thread_id: Mapped[int] = mapped_column(ForeignKey("threads.id"), index=True)
    author: Mapped[str] = mapped_column(String(128))
    body: Mapped[str] = mapped_column(Text)
    created_at_platform: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))

    thread: Mapped[ThreadRecord] = relationship(back_populates="comments")


class ClassificationRecord(Base):
    __tablename__ = "classifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    thread_id: Mapped[int] = mapped_column(ForeignKey("threads.id"), index=True)
    target_comment_id: Mapped[int | None] = mapped_column(ForeignKey("thread_comments.id"), nullable=True)
    intent: Mapped[str] = mapped_column(String(64))
    relevance_score: Mapped[float] = mapped_column(Float)
    commercial_opportunity: Mapped[str] = mapped_column(String(16))
    value_add_score: Mapped[float] = mapped_column(Float)
    policy_risk_score: Mapped[float] = mapped_column(Float)
    promo_fit_score: Mapped[float] = mapped_column(Float)
    tone: Mapped[str] = mapped_column(String(32))
    subreddit_promo_policy: Mapped[str] = mapped_column(String(16))
    duplicate_similarity_score: Mapped[float] = mapped_column(Float, default=0.0)
    reason_codes_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=datetime.utcnow)

    thread: Mapped[ThreadRecord] = relationship(back_populates="classifications")
    decision: Mapped[DecisionRecord] = relationship(back_populates="classification", uselist=False)


class DecisionRecord(Base):
    __tablename__ = "decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    classification_id: Mapped[int] = mapped_column(ForeignKey("classifications.id"), unique=True, index=True)
    action: Mapped[str] = mapped_column(String(64))
    promotion_mode: Mapped[str] = mapped_column(String(32))
    requires_review: Mapped[bool] = mapped_column(Boolean)
    trace_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=datetime.utcnow)

    classification: Mapped[ClassificationRecord] = relationship(back_populates="decision")
    draft: Mapped[DraftRecord] = relationship(back_populates="decision", uselist=False)


class DraftRecord(Base):
    __tablename__ = "drafts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    decision_id: Mapped[int] = mapped_column(ForeignKey("decisions.id"), unique=True, index=True)
    body: Mapped[str] = mapped_column(Text)
    strategy: Mapped[str] = mapped_column(String(32))
    contains_link: Mapped[bool] = mapped_column(Boolean, default=False)
    disclosure_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    autopost_eligible: Mapped[bool] = mapped_column(Boolean, default=False)
    evaluation_json: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(32), default="created")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=datetime.utcnow)

    decision: Mapped[DecisionRecord] = relationship(back_populates="draft")
    review: Mapped[ReviewRecord] = relationship(back_populates="draft", uselist=False)
    attempts: Mapped[list[PostAttemptRecord]] = relationship(back_populates="draft")


class ReviewRecord(Base):
    __tablename__ = "reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    draft_id: Mapped[int] = mapped_column(ForeignKey("drafts.id"), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    review_reason: Mapped[str] = mapped_column(Text)
    reviewer_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)

    draft: Mapped[DraftRecord] = relationship(back_populates="review")


class PostAttemptRecord(Base):
    __tablename__ = "post_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    draft_id: Mapped[int] = mapped_column(ForeignKey("drafts.id"), index=True)
    transport: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="pending")
    posted_comment_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=datetime.utcnow)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)

    draft: Mapped[DraftRecord] = relationship(back_populates="attempts")
    snapshots: Mapped[list[EngagementSnapshotRecord]] = relationship(back_populates="attempt")


class EngagementSnapshotRecord(Base):
    __tablename__ = "engagement_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    post_attempt_id: Mapped[int] = mapped_column(ForeignKey("post_attempts.id"), index=True)
    score: Mapped[int] = mapped_column(Integer, default=0)
    reply_count: Mapped[int] = mapped_column(Integer, default=0)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    is_removed: Mapped[bool] = mapped_column(Boolean, default=False)
    is_locked: Mapped[bool] = mapped_column(Boolean, default=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=datetime.utcnow)

    attempt: Mapped[PostAttemptRecord] = relationship(back_populates="snapshots")


class LearningExampleRecord(Base):
    __tablename__ = "learning_examples"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    thread_id: Mapped[int] = mapped_column(ForeignKey("threads.id"), index=True)
    draft_id: Mapped[int] = mapped_column(ForeignKey("drafts.id"), index=True)
    features_json: Mapped[dict] = mapped_column(JSON, default=dict)
    outcome_label: Mapped[str] = mapped_column(String(64))
    reward_score: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=datetime.utcnow)


class StrategyWeightRecord(Base):
    __tablename__ = "strategy_weights"
    __table_args__ = (UniqueConstraint("strategy", "version", name="uq_strategy_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    strategy: Mapped[str] = mapped_column(String(64), index=True)
    weight: Mapped[float] = mapped_column(Float)
    version: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=datetime.utcnow)


class SystemEventRecord(Base):
    __tablename__ = "system_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_type: Mapped[str] = mapped_column(String(128), index=True)
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=datetime.utcnow)
