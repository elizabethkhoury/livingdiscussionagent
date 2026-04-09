from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from reddit_agent.models import ApprovalDecision, CandidateDecision, DraftStatus, HealthState


class CandidateFeatureSummary(BaseModel):
    relevance_score: float
    replyability_score: float
    promo_fit_score: float
    risk_score: float
    uncertainty_score: float
    freshness_score: float
    competition_score: float
    token_cost_estimate: float
    feature_payload: dict[str, Any] = Field(default_factory=dict)


class CandidateRead(BaseModel):
    id: str
    subreddit: str
    title: str
    body: str
    permalink: str
    source_kind: str
    route_product: str | None
    decision: CandidateDecision
    abstain_reason: str | None
    evaluator_summary: str | None
    model_confidence: float
    risk_score: float
    expected_value: float
    discovered_at: datetime
    features: list[CandidateFeatureSummary] = Field(default_factory=list)


class IngestResponse(BaseModel):
    created: int
    queued: int
    watched: int
    abstained: int
    candidate_ids: list[str]


class DraftRead(BaseModel):
    id: str
    candidate_id: str
    version: int
    body: str
    critic_notes: dict[str, Any]
    token_usage: int
    similarity_score: float
    status: DraftStatus
    created_at: datetime


class GenerateDraftResponse(BaseModel):
    candidate: CandidateRead
    draft: DraftRead


class ApprovalRequest(BaseModel):
    decision: ApprovalDecision
    operator_feedback: str | None = None
    edited_body: str | None = None


class ApprovalResponse(BaseModel):
    draft_id: str
    status: DraftStatus
    handoff_url: str | None
    final_body: str


class ObservationRequest(BaseModel):
    action_id: str
    horizon_hours: int
    upvotes: int = 0
    positive_replies: int = 0
    negative_replies: int = 0
    moderator_flag: bool = False
    link_clicks: int = 0
    qualified_signups: int = 0
    paid_conversions: int = 0
    zero_engagement: bool = False
    payload: dict[str, Any] = Field(default_factory=dict)


class ObservationResponse(BaseModel):
    observation_id: str
    reward_delta: float
    agent_score: float


class AgentHealthRead(BaseModel):
    id: str
    name: str
    state: HealthState
    score: float
    version: int
    strict_mode_until: datetime | None
    thresholds: dict[str, Any]
    recent_failures: list[str] = Field(default_factory=list)


class ReplayRead(BaseModel):
    candidate_id: str
    title: str
    subreddit: str
    decision: CandidateDecision
    route_product: str | None
    trace: dict[str, Any]
    drafts: list[DraftRead] = Field(default_factory=list)


class AnalyticsRead(BaseModel):
    queued_drafts: int
    approvals: int
    manual_posts: int
    total_reward: float
    conversions: int
    by_product: dict[str, int]
    by_subreddit: dict[str, int]
