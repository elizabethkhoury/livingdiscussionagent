from __future__ import annotations

from typing import Protocol

from src.domain.models import (
    ClassificationResult,
    DecisionResult,
    DraftEvaluation,
    DraftReply,
    EngagementSnapshot,
    LearningUpdateReport,
    PostAttempt,
    ReviewItem,
    ThreadContext,
)


class CandidateSource(Protocol):
    def fetch_candidates(self) -> list[ThreadContext]: ...


class Classifier(Protocol):
    def classify(self, thread: ThreadContext) -> ClassificationResult: ...


class DecisionEngine(Protocol):
    def decide(self, thread: ThreadContext, classification: ClassificationResult) -> DecisionResult: ...


class DraftWriterProtocol(Protocol):
    def compose(self, thread: ThreadContext, decision: DecisionResult) -> DraftReply | None: ...


class DraftEvaluatorProtocol(Protocol):
    def evaluate(self, thread: ThreadContext, draft: DraftReply) -> DraftEvaluation: ...


class ReviewServiceProtocol(Protocol):
    def enqueue(self, draft_id: int, reason: str) -> ReviewItem: ...


class PostingTransport(Protocol):
    async def publish(self, draft_id: int) -> PostAttempt: ...


class OutcomeMonitor(Protocol):
    def refresh(self, post_attempt_id: int) -> EngagementSnapshot: ...


class LearningService(Protocol):
    def update(self) -> LearningUpdateReport: ...

