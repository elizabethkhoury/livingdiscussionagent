from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import src.storage.db as db
from src.domain.enums import CommercialOpportunity, DecisionAction, DraftStatus, PromotionMode, ResponseStrategy, RiskLevel, SubredditPromoPolicy, Tone
from src.domain.models import ClassificationResult, DecisionResult, DraftReply, PolicyDecisionTrace, PostAttempt, RedditPostCandidate, ThreadContext
from src.storage import schema
from src.storage.repositories import DecisionRepository, ThreadRepository
from src.workers.review_worker import ReviewWorker


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


def make_thread(thread_id: str = "thread-1"):
    return ThreadContext(
        post=RedditPostCandidate(
            platform_thread_id=thread_id,
            subreddit="PromptEngineering",
            title="How do I organize prompts?",
            body="I keep losing the good ones.",
            url=f"https://example.com/{thread_id}",
            author="poster",
        )
    )


def make_classification():
    return ClassificationResult(
        intent="question",
        relevance_score=0.9,
        commercial_opportunity=CommercialOpportunity.LOW,
        value_add_score=0.9,
        policy_risk_score=0.1,
        promo_fit_score=0.2,
        tone=Tone.BEGINNER,
        subreddit_promo_policy=SubredditPromoPolicy.ALLOW,
        duplicate_similarity_score=0.01,
        reason_codes=[],
    )


def make_decision():
    return DecisionResult(
        action=DecisionAction.AUTOPOST_INFO,
        promotion_mode=PromotionMode.NONE,
        requires_review=False,
        risk_level=RiskLevel.LOW,
        selected_strategy=ResponseStrategy.EDUCATIONAL,
        trace=PolicyDecisionTrace(reason_codes=["autopost_information_only"]),
    )


def make_draft(thread_id: str = "thread-1"):
    return DraftReply(
        body="A practical prompt library with notes can help.",
        strategy=ResponseStrategy.EDUCATIONAL,
        promotion_mode=PromotionMode.NONE,
        contains_link=False,
        disclosure_text=None,
        thread_id=thread_id,
        autopost_eligible=True,
    )


def create_approved_draft(thread_id: str = "thread-1"):
    with db.session_scope() as session:
        threads = ThreadRepository(session)
        decisions = DecisionRepository(session)
        thread_record = threads.upsert_thread(make_thread(thread_id))
        classification_record = decisions.create_classification(thread_record.id, None, make_classification())
        decision_record = decisions.create_decision(classification_record.id, make_decision())
        draft_record = decisions.create_draft(decision_record.id, make_draft(thread_id), status=DraftStatus.APPROVED.value)
        return draft_record.id


class FakeTransport:
    def __init__(self):
        self.calls = []

    async def publish(self, draft_id: int, attempt_id: int):
        self.calls.append((draft_id, attempt_id))
        with db.session_scope() as session:
            record = DecisionRepository(session).finish_attempt(attempt_id, "posted", posted_comment_id=f"posted-{draft_id}")
            return PostAttempt(
                attempt_id=record.id,
                draft_id=record.draft_id,
                transport=record.transport,
                status=record.status,
                posted_comment_id=record.posted_comment_id,
                error_message=record.error_message,
            )


def make_worker_with_fake_transport():
    worker = ReviewWorker()
    fake_transport = FakeTransport()
    worker.poster.transport = fake_transport
    return worker, fake_transport


def test_approved_draft_is_published_once(sqlite_session_local):
    draft_id = create_approved_draft()
    worker, fake_transport = make_worker_with_fake_transport()

    first_run = asyncio.run(worker.run_once())
    second_run = asyncio.run(worker.run_once())

    assert [attempt.draft_id for attempt in first_run] == [draft_id]
    assert second_run == []
    assert len(fake_transport.calls) == 1

    with db.session_scope() as session:
        draft = session.get(schema.DraftRecord, draft_id)
        attempts = session.query(schema.PostAttemptRecord).all()

        assert draft.status == DraftStatus.POSTED.value
        assert len(attempts) == 1
        assert attempts[0].reply_target_key == "reddit:thread:thread-1"


def test_duplicate_targets_publish_one_draft(sqlite_session_local):
    first_draft_id = create_approved_draft(thread_id="thread-1")
    second_draft_id = create_approved_draft(thread_id="thread-1")
    worker, fake_transport = make_worker_with_fake_transport()

    posted = asyncio.run(worker.run_once())

    assert [attempt.draft_id for attempt in posted] == [first_draft_id]
    assert len(fake_transport.calls) == 1

    with db.session_scope() as session:
        first_draft = session.get(schema.DraftRecord, first_draft_id)
        second_draft = session.get(schema.DraftRecord, second_draft_id)
        attempts = session.query(schema.PostAttemptRecord).all()

        assert first_draft.status == DraftStatus.POSTED.value
        assert second_draft.status == DraftStatus.DUPLICATE.value
        assert len(attempts) == 1
