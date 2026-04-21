from __future__ import annotations

import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import src.storage.db as db
from src.domain.enums import (
    CommercialOpportunity,
    DecisionAction,
    DraftStatus,
    PromotionMode,
    ResponseStrategy,
    ReviewStatus,
    RiskLevel,
    SubredditPromoPolicy,
    Tone,
)
from src.domain.models import (
    ClassificationResult,
    DecisionResult,
    DraftReply,
    PolicyDecisionTrace,
    RedditPostCandidate,
    ThreadContext,
)
from src.review.service import ReviewService
from src.storage import schema
from src.storage.repositories import DecisionRepository, ThreadRepository


@pytest.fixture
def sqlite_session_local(monkeypatch: pytest.MonkeyPatch):
    engine = db.create_engine(
        "sqlite+pysqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(connection, _record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    test_session_local = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)
    db.Base.metadata.create_all(engine)
    monkeypatch.setattr(db, "SessionLocal", test_session_local)
    yield test_session_local
    db.Base.metadata.drop_all(engine)
    engine.dispose()


def make_thread():
    return ThreadContext(
        post=RedditPostCandidate(
            platform_thread_id="thread-1",
            subreddit="PromptEngineering",
            title="How do I organize prompts?",
            body="I keep losing the good ones.",
            url="https://example.com/thread-1",
            author="poster",
        )
    )


def make_classification():
    return ClassificationResult(
        intent="question",
        relevance_score=0.9,
        commercial_opportunity=CommercialOpportunity.HIGH,
        value_add_score=0.86,
        policy_risk_score=0.2,
        promo_fit_score=0.84,
        tone=Tone.BEGINNER,
        subreddit_promo_policy=SubredditPromoPolicy.ALLOW,
        duplicate_similarity_score=0.02,
        reason_codes=[],
    )


def make_decision():
    return DecisionResult(
        action=DecisionAction.QUEUE_REVIEW_PRODUCT,
        promotion_mode=PromotionMode.PLAIN_MENTION,
        requires_review=True,
        risk_level=RiskLevel.MEDIUM,
        selected_strategy=ResponseStrategy.EDUCATIONAL,
        trace=PolicyDecisionTrace(reason_codes=["product_review_required"]),
    )


def make_draft():
    return DraftReply(
        body="Saving prompts with outcome notes and context helps; PromptHunt could be relevant if you want a dedicated library.",
        strategy=ResponseStrategy.EDUCATIONAL,
        promotion_mode=PromotionMode.PLAIN_MENTION,
        contains_link=False,
        disclosure_text=None,
        thread_id="thread-1",
        autopost_eligible=False,
    )


def create_committed_draft():
    with db.session_scope() as session:
        threads = ThreadRepository(session)
        decisions = DecisionRepository(session)
        thread_record = threads.upsert_thread(make_thread())
        classification_record = decisions.create_classification(thread_record.id, None, make_classification())
        decision_record = decisions.create_decision(classification_record.id, make_decision())
        draft_record = decisions.create_draft(decision_record.id, make_draft())
        return draft_record.id


def test_enqueue_sets_review_and_draft_status(sqlite_session_local):
    draft_id = create_committed_draft()

    review = ReviewService().enqueue(draft_id, "product_review_required")

    assert review.draft_id == draft_id
    assert review.status == ReviewStatus.PENDING

    with db.session_scope() as session:
        draft_record = session.get(schema.DraftRecord, draft_id)
        review_record = session.get(schema.ReviewRecord, review.review_id)

        assert draft_record is not None
        assert draft_record.status == DraftStatus.QUEUED.value
        assert review_record is not None
        assert review_record.draft_id == draft_id
