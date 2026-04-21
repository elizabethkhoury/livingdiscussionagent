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
from src.storage import schema
from src.workers.ingest_worker import IngestWorker


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
            title="Where can I save and reuse prompts?",
            body="I want a better workflow for prompt reuse.",
            url="https://example.com/thread-1",
            author="poster",
        )
    )


def make_classification():
    return ClassificationResult(
        intent="question",
        relevance_score=0.92,
        commercial_opportunity=CommercialOpportunity.HIGH,
        value_add_score=0.88,
        policy_risk_score=0.2,
        promo_fit_score=0.91,
        tone=Tone.BEGINNER,
        subreddit_promo_policy=SubredditPromoPolicy.ALLOW,
        duplicate_similarity_score=0.05,
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
        body="A shared prompt library with notes can help, and PromptHunt could fit if you want a dedicated tool.",
        strategy=ResponseStrategy.EDUCATIONAL,
        promotion_mode=PromotionMode.PLAIN_MENTION,
        contains_link=False,
        disclosure_text=None,
        thread_id="thread-1",
        autopost_eligible=False,
    )


def test_persist_queues_review_in_same_transaction(sqlite_session_local):
    worker = IngestWorker()

    result = worker._persist(make_thread(), make_classification(), make_decision(), make_draft())

    assert result["draft_id"] is not None
    assert result["review_id"] is not None

    with db.session_scope() as session:
        draft_record = session.get(schema.DraftRecord, result["draft_id"])
        review_record = session.get(schema.ReviewRecord, result["review_id"])

        assert draft_record is not None
        assert draft_record.status == DraftStatus.QUEUED.value
        assert review_record is not None
        assert review_record.draft_id == draft_record.id
