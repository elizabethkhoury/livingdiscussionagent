from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from reddit_agent.db import Base


def now_utc():
    return datetime.now(UTC)


class CandidateDecision(StrEnum):
    abstain = 'abstain'
    watch_only = 'watch_only'
    queue_draft = 'queue_draft'


class DraftStatus(StrEnum):
    pending_approval = 'pending_approval'
    approved = 'approved'
    rejected = 'rejected'
    posted = 'posted'


class ApprovalDecision(StrEnum):
    approve = 'approve'
    reject = 'reject'


class ActionType(StrEnum):
    queued = 'queued'
    manual_handoff = 'manual_handoff'
    manual_post_confirmed = 'manual_post_confirmed'
    observation = 'observation'
    reflection = 'reflection'


class HealthState(StrEnum):
    seed = 'seed'
    mature = 'mature'
    stressed = 'stressed'
    dormant = 'dormant'
    retired = 'retired'


class MemoryType(StrEnum):
    working = 'working'
    episodic = 'episodic'
    semantic = 'semantic'
    identity = 'identity'
    health = 'health'


class RedditCandidate(Base):
    __tablename__ = 'reddit_candidates'

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    reddit_post_id: Mapped[str] = mapped_column(String(32), index=True)
    reddit_comment_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    subreddit: Mapped[str] = mapped_column(String(100), index=True)
    title: Mapped[str] = mapped_column(String(512))
    body: Mapped[str] = mapped_column(Text)
    permalink: Mapped[str] = mapped_column(String(1024))
    author: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source_kind: Mapped[str] = mapped_column(String(32), default='post')
    freshness_hours: Mapped[float] = mapped_column(Float, default=0.0)
    num_comments: Mapped[int] = mapped_column(Integer, default=0)
    route_product: Mapped[str | None] = mapped_column(String(64), nullable=True)
    decision: Mapped[str] = mapped_column(String(32), default=CandidateDecision.watch_only.value)
    abstain_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    evaluator_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    risk_score: Mapped[float] = mapped_column(Float, default=1.0)
    expected_value: Mapped[float] = mapped_column(Float, default=0.0)
    decision_trace: Mapped[dict] = mapped_column(JSON, default=dict)
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=now_utc,
        onupdate=now_utc,
    )

    features: Mapped[list[CandidateFeature]] = relationship(
        back_populates='candidate', cascade='all, delete-orphan'
    )
    drafts: Mapped[list[Draft]] = relationship(
        back_populates='candidate', cascade='all, delete-orphan'
    )
    actions: Mapped[list[Action]] = relationship(
        back_populates='candidate', cascade='all, delete-orphan'
    )


class CandidateFeature(Base):
    __tablename__ = 'candidate_features'

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    candidate_id: Mapped[str] = mapped_column(ForeignKey('reddit_candidates.id'), index=True)
    relevance_score: Mapped[float] = mapped_column(Float, default=0.0)
    replyability_score: Mapped[float] = mapped_column(Float, default=0.0)
    promo_fit_score: Mapped[float] = mapped_column(Float, default=0.0)
    risk_score: Mapped[float] = mapped_column(Float, default=1.0)
    uncertainty_score: Mapped[float] = mapped_column(Float, default=0.0)
    freshness_score: Mapped[float] = mapped_column(Float, default=0.0)
    competition_score: Mapped[float] = mapped_column(Float, default=0.0)
    token_cost_estimate: Mapped[float] = mapped_column(Float, default=0.0)
    feature_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    candidate: Mapped[RedditCandidate] = relationship(back_populates='features')


class Draft(Base):
    __tablename__ = 'drafts'

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    candidate_id: Mapped[str] = mapped_column(ForeignKey('reddit_candidates.id'), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    body: Mapped[str] = mapped_column(Text)
    critic_notes: Mapped[dict] = mapped_column(JSON, default=dict)
    token_usage: Mapped[int] = mapped_column(Integer, default=0)
    similarity_score: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(32), default=DraftStatus.pending_approval.value)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    candidate: Mapped[RedditCandidate] = relationship(back_populates='drafts')
    approvals: Mapped[list[Approval]] = relationship(
        back_populates='draft', cascade='all, delete-orphan'
    )
    actions: Mapped[list[Action]] = relationship(back_populates='draft')


class Approval(Base):
    __tablename__ = 'approvals'

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    draft_id: Mapped[str] = mapped_column(ForeignKey('drafts.id'), index=True)
    decision: Mapped[str] = mapped_column(String(32))
    operator_feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    edited_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    draft: Mapped[Draft] = relationship(back_populates='approvals')


class Action(Base):
    __tablename__ = 'actions'

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    candidate_id: Mapped[str] = mapped_column(ForeignKey('reddit_candidates.id'), index=True)
    draft_id: Mapped[str | None] = mapped_column(ForeignKey('drafts.id'), nullable=True, index=True)
    action_type: Mapped[str] = mapped_column(String(64))
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    candidate: Mapped[RedditCandidate] = relationship(back_populates='actions')
    draft: Mapped[Draft | None] = relationship(back_populates='actions')
    observations: Mapped[list[Observation]] = relationship(
        back_populates='action', cascade='all, delete-orphan'
    )


class Observation(Base):
    __tablename__ = 'observations'

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    action_id: Mapped[str] = mapped_column(ForeignKey('actions.id'), index=True)
    horizon_hours: Mapped[int] = mapped_column(Integer)
    upvotes: Mapped[int] = mapped_column(Integer, default=0)
    positive_replies: Mapped[int] = mapped_column(Integer, default=0)
    negative_replies: Mapped[int] = mapped_column(Integer, default=0)
    moderator_flag: Mapped[bool] = mapped_column(default=False)
    link_clicks: Mapped[int] = mapped_column(Integer, default=0)
    qualified_signups: Mapped[int] = mapped_column(Integer, default=0)
    paid_conversions: Mapped[int] = mapped_column(Integer, default=0)
    zero_engagement: Mapped[bool] = mapped_column(default=False)
    reward_delta: Mapped[float] = mapped_column(Float, default=0.0)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    action: Mapped[Action] = relationship(back_populates='observations')


class AgentPolicy(Base):
    __tablename__ = 'agent_policies'

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    parent_policy_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    name: Mapped[str] = mapped_column(String(128), default='default')
    state: Mapped[str] = mapped_column(String(32), default=HealthState.seed.value)
    score: Mapped[float] = mapped_column(Float, default=50.0)
    strict_mode_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    identity: Mapped[dict] = mapped_column(JSON, default=dict)
    thresholds: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    score_events: Mapped[list[AgentScore]] = relationship(
        back_populates='policy', cascade='all, delete-orphan'
    )


class AgentScore(Base):
    __tablename__ = 'agent_scores'

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    agent_policy_id: Mapped[str] = mapped_column(ForeignKey('agent_policies.id'), index=True)
    points: Mapped[float] = mapped_column(Float)
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    policy: Mapped[AgentPolicy] = relationship(back_populates='score_events')


class MemoryEntry(Base):
    __tablename__ = 'memory_entries'

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    agent_policy_id: Mapped[str] = mapped_column(ForeignKey('agent_policies.id'), index=True)
    memory_type: Mapped[str] = mapped_column(String(32), index=True)
    subreddit: Mapped[str | None] = mapped_column(String(100), nullable=True)
    product: Mapped[str | None] = mapped_column(String(64), nullable=True)
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(JSON, default=list)
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    source_action_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class SubredditProfile(Base):
    __tablename__ = 'subreddit_profiles'

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    subreddit: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    allow_promotion: Mapped[bool] = mapped_column(default=False)
    allow_links: Mapped[bool] = mapped_column(default=False)
    notes: Mapped[str] = mapped_column(Text, default='')
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=now_utc,
        onupdate=now_utc,
    )


class ExperimentAssignment(Base):
    __tablename__ = 'experiment_assignments'

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    candidate_id: Mapped[str] = mapped_column(String(36), index=True)
    experiment_key: Mapped[str] = mapped_column(String(128))
    variant: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class ProductClickEvent(Base):
    __tablename__ = 'product_click_events'

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    candidate_id: Mapped[str] = mapped_column(String(36), index=True)
    product: Mapped[str] = mapped_column(String(64))
    clicks: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class ConversionEvent(Base):
    __tablename__ = 'conversion_events'

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    candidate_id: Mapped[str] = mapped_column(String(36), index=True)
    product: Mapped[str] = mapped_column(String(64))
    signup_type: Mapped[str] = mapped_column(String(64), default='qualified_signup')
    count: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
