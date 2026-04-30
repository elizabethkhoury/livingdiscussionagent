from __future__ import annotations

from datetime import datetime, timedelta

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
    RedditCommentCandidate,
    RedditPostCandidate,
    ThreadContext,
)
from src.storage import schema
from src.storage.repositories import DecisionRepository, ThreadRepository
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


class FakeReader:
    def __init__(self, posts):
        self.posts = posts
        self.rate_limited = False
        self.fetch_post_calls = []
        self.context_calls = []

    def fetch_posts(self, subreddit: str, limit: int = 25):
        self.fetch_post_calls.append((subreddit, limit))
        return self.posts

    def fetch_thread_context(self, post: RedditPostCandidate, comment_limit: int = 10):
        self.context_calls.append((post.platform_thread_id, comment_limit))
        return ThreadContext(
            post=post,
            comments=[
                RedditCommentCandidate(platform_comment_id="comment-low", author="a", body="This is a lower value comment about generic prompt storage."),
                RedditCommentCandidate(platform_comment_id="comment-best", author="b", body="I specifically need a reusable prompt library for a team workflow."),
            ],
        )


class FakeClassificationPipeline:
    def __init__(self, duplicate_similarity_lookup=None):
        self.duplicate_similarity_lookup = duplicate_similarity_lookup

    def classify(self, candidate: ThreadContext):
        if candidate.target_comment and candidate.target_comment.platform_comment_id == "comment-best":
            return ClassificationResult(
                intent="question",
                relevance_score=0.95,
                commercial_opportunity=CommercialOpportunity.HIGH,
                value_add_score=0.93,
                policy_risk_score=0.2,
                promo_fit_score=0.94,
                tone=Tone.BEGINNER,
                subreddit_promo_policy=SubredditPromoPolicy.ALLOW,
                duplicate_similarity_score=0.01,
                reason_codes=[],
            )
        return ClassificationResult(
            intent="question",
            relevance_score=0.85,
            commercial_opportunity=CommercialOpportunity.MEDIUM,
            value_add_score=0.8,
            policy_risk_score=0.1,
            promo_fit_score=0.6,
            tone=Tone.BEGINNER,
            subreddit_promo_policy=SubredditPromoPolicy.ALLOW,
            duplicate_similarity_score=0.01,
            reason_codes=[],
        )


class FakeDecisionEngine:
    def decide(self, candidate: ThreadContext, _classification: ClassificationResult):
        if candidate.target_comment and candidate.target_comment.platform_comment_id == "comment-best":
            return make_decision()
        return DecisionResult(
            action=DecisionAction.AUTOPOST_INFO,
            promotion_mode=PromotionMode.NONE,
            requires_review=False,
            risk_level=RiskLevel.LOW,
            selected_strategy=ResponseStrategy.EDUCATIONAL,
            trace=PolicyDecisionTrace(reason_codes=["autopost_information_only"]),
        )


class FakeDraftWriter:
    def __init__(self):
        self.composed = []

    def compose(self, candidate: ThreadContext, decision: DecisionResult):
        self.composed.append((candidate, decision))
        return make_draft()


class FakeDraftEvaluator:
    def evaluate(self, _candidate: ThreadContext, _draft: DraftReply):
        return None


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


def test_run_once_dedupes_subreddits_and_persists_best_candidate(monkeypatch, sqlite_session_local):
    monkeypatch.setattr("src.workers.ingest_worker.ClassificationPipeline", FakeClassificationPipeline)
    worker = IngestWorker()
    worker.settings.enabled_subreddits = ["Lovable", "lovable"]
    worker.settings.reddit_posts_per_subreddit = 2
    worker.settings.reddit_comment_limit = 5
    worker.settings.reddit_reprocess_after_hours = 24
    worker.reader = FakeReader([make_thread().post])
    worker.decision_engine = FakeDecisionEngine()
    worker.draft_writer = FakeDraftWriter()
    worker.draft_evaluator = FakeDraftEvaluator()

    result = worker.run_once()

    assert worker.reader.fetch_post_calls == [("Lovable", 2)]
    assert worker.reader.context_calls == [("thread-1", 5)]
    assert len(worker.draft_writer.composed) == 1
    selected_candidate, selected_decision = worker.draft_writer.composed[0]
    assert selected_candidate.target_comment is not None
    assert selected_candidate.target_comment.platform_comment_id == "comment-best"
    assert selected_decision.action == DecisionAction.QUEUE_REVIEW_PRODUCT
    assert len(result) == 1
    assert result[0]["action"] == DecisionAction.QUEUE_REVIEW_PRODUCT.value
    assert result[0]["draft_id"] is not None
    assert result[0]["review_id"] is not None

    with db.session_scope() as session:
        assert session.query(schema.ClassificationRecord).count() == 1
        assert session.query(schema.DecisionRecord).count() == 1
        assert session.query(schema.DraftRecord).count() == 1
        assert session.query(schema.ReviewRecord).count() == 1


def test_run_once_skips_recently_classified_threads(monkeypatch, sqlite_session_local):
    monkeypatch.setattr("src.workers.ingest_worker.ClassificationPipeline", FakeClassificationPipeline)
    worker = IngestWorker()
    worker.settings.enabled_subreddits = ["PromptEngineering"]
    worker.settings.reddit_reprocess_after_hours = 24
    worker.reader = FakeReader([make_thread().post])
    worker.decision_engine = FakeDecisionEngine()
    worker.draft_writer = FakeDraftWriter()
    worker.draft_evaluator = FakeDraftEvaluator()

    assert len(worker.run_once()) == 1
    assert worker.run_once() == []
    assert worker.reader.fetch_post_calls == [("PromptEngineering", 2), ("PromptEngineering", 2)]
    assert worker.reader.context_calls == [("thread-1", 5)]


def test_run_once_skips_threads_with_recent_posted_attempt(monkeypatch, sqlite_session_local):
    with db.session_scope() as session:
        threads = ThreadRepository(session)
        decisions = DecisionRepository(session)
        thread_record = threads.upsert_thread(make_thread())
        classification_record = decisions.create_classification(thread_record.id, None, make_classification())
        classification_record.created_at = datetime.utcnow() - timedelta(days=3)
        decision_record = decisions.create_decision(classification_record.id, make_decision())
        draft_record = decisions.create_draft(decision_record.id, make_draft(), status=DraftStatus.POSTED.value)
        decisions.record_attempt(draft_record.id, "playwright", "posted", posted_comment_id="posted-comment")

    monkeypatch.setattr("src.workers.ingest_worker.ClassificationPipeline", FakeClassificationPipeline)
    worker = IngestWorker()
    worker.settings.enabled_subreddits = ["PromptEngineering"]
    worker.settings.reddit_reprocess_after_hours = 1
    worker.reader = FakeReader([make_thread().post])
    worker.decision_engine = FakeDecisionEngine()
    worker.draft_writer = FakeDraftWriter()
    worker.draft_evaluator = FakeDraftEvaluator()

    assert worker.run_once() == []
    assert worker.reader.context_calls == []


def test_best_candidate_prefers_product_review_over_autopost():
    worker = IngestWorker()
    post_candidate = make_thread()
    comment = RedditCommentCandidate(platform_comment_id="comment-1", author="a", body="I need a prompt library with team sharing and examples.")
    review_candidate = ThreadContext(post=post_candidate.post, comments=[comment], target_comment=comment)
    autopost_classification = ClassificationResult(
        intent="question",
        relevance_score=0.99,
        commercial_opportunity=CommercialOpportunity.MEDIUM,
        value_add_score=0.99,
        policy_risk_score=0.01,
        promo_fit_score=0.99,
        tone=Tone.BEGINNER,
        subreddit_promo_policy=SubredditPromoPolicy.ALLOW,
        duplicate_similarity_score=0.01,
        reason_codes=[],
    )
    review_classification = ClassificationResult(
        intent="question",
        relevance_score=0.8,
        commercial_opportunity=CommercialOpportunity.HIGH,
        value_add_score=0.8,
        policy_risk_score=0.2,
        promo_fit_score=0.8,
        tone=Tone.BEGINNER,
        subreddit_promo_policy=SubredditPromoPolicy.ALLOW,
        duplicate_similarity_score=0.01,
        reason_codes=[],
    )
    autopost_decision = DecisionResult(
        action=DecisionAction.AUTOPOST_INFO,
        promotion_mode=PromotionMode.NONE,
        requires_review=False,
        risk_level=RiskLevel.LOW,
        selected_strategy=ResponseStrategy.EDUCATIONAL,
        trace=PolicyDecisionTrace(reason_codes=["autopost_information_only"]),
    )
    review_decision = make_decision()

    selected = worker._best_candidate(
        [
            (post_candidate, autopost_classification, autopost_decision),
            (review_candidate, review_classification, review_decision),
        ]
    )

    assert selected == (review_candidate, review_classification, review_decision)
