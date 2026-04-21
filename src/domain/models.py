from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from pydantic import BaseModel, Field

from src.domain.enums import (
    CommercialOpportunity,
    DecisionAction,
    PromotionMode,
    ResponseStrategy,
    ReviewStatus,
    RiskLevel,
    SubredditPromoPolicy,
    Tone,
)


class RedditPostCandidate(BaseModel):
    platform_thread_id: str
    subreddit: str
    title: str
    body: str = ""
    url: str
    author: str = ""
    age_hours: float = 0.0
    num_comments: int = 0
    created_at_platform: datetime | None = None


class RedditCommentCandidate(BaseModel):
    platform_comment_id: str
    author: str
    body: str
    created_at_platform: datetime | None = None


class ThreadContext(BaseModel):
    post: RedditPostCandidate
    comments: list[RedditCommentCandidate] = Field(default_factory=list)
    target_comment: RedditCommentCandidate | None = None

    @property
    def thread_id(self):
        return self.post.platform_thread_id

    @property
    def combined_text(self):
        parts = [self.post.title, self.post.body]
        if self.target_comment:
            parts.append(self.target_comment.body)
        return "\n".join(part for part in parts if part).strip()


class ClassificationResult(BaseModel):
    intent: str
    relevance_score: float
    commercial_opportunity: CommercialOpportunity
    value_add_score: float
    policy_risk_score: float
    promo_fit_score: float
    tone: Tone
    subreddit_promo_policy: SubredditPromoPolicy
    duplicate_similarity_score: float
    reason_codes: list[str] = Field(default_factory=list)


class PolicyDecisionTrace(BaseModel):
    blocked: bool = False
    reason_codes: list[str] = Field(default_factory=list)
    thresholds: dict[str, float] = Field(default_factory=dict)
    classifier_summary: dict[str, float | str] = Field(default_factory=dict)


class DecisionResult(BaseModel):
    action: DecisionAction
    promotion_mode: PromotionMode
    requires_review: bool
    risk_level: RiskLevel
    selected_strategy: ResponseStrategy
    trace: PolicyDecisionTrace


class DraftEvaluation(BaseModel):
    authenticity_score: float
    specificity_score: float
    helpfulness_score: float
    promo_pressure_score: float
    policy_compliance_score: float
    overall_score: float
    fail_reasons: list[str] = Field(default_factory=list)


class DraftReply(BaseModel):
    body: str
    strategy: ResponseStrategy
    promotion_mode: PromotionMode
    contains_link: bool
    disclosure_text: str | None = None
    decision_trace_id: str | None = None
    thread_id: str
    autopost_eligible: bool
    evaluation: DraftEvaluation | None = None


class ReviewItem(BaseModel):
    review_id: int
    draft_id: int
    status: ReviewStatus
    review_reason: str


class PostAttempt(BaseModel):
    attempt_id: int | None = None
    draft_id: int
    transport: str
    status: str
    posted_comment_id: str | None = None
    error_message: str | None = None


class EngagementSnapshot(BaseModel):
    post_attempt_id: int
    score: int
    reply_count: int
    is_deleted: bool
    is_removed: bool
    is_locked: bool
    captured_at: datetime = Field(default_factory=datetime.utcnow)


class LearningExample(BaseModel):
    thread_id: int
    draft_id: int
    features: dict[str, float | str]
    outcome_label: str
    reward_score: float


class StrategyWeights(BaseModel):
    version: int
    weights: dict[ResponseStrategy, float]


class LearningUpdateReport(BaseModel):
    updated: bool
    reason: str
    strategy_weights: dict[str, float] = Field(default_factory=dict)
    thresholds: dict[str, float] = Field(default_factory=dict)


class RuntimeThresholds(BaseModel):
    relevance_threshold: float
    value_add_threshold: float
    autopost_overall_threshold: float


@dataclass
class CircuitBreakerState:
    moderator_removals: int = 0
    rate_limits: int = 0
    blocked_until: datetime | None = None
    failure_events: list[str] = field(default_factory=list)
