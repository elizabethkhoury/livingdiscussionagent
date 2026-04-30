from __future__ import annotations

import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import src.storage.db as db
from src.domain.enums import CommercialOpportunity, DecisionAction, DraftStatus, PromotionMode, ResponseStrategy, RiskLevel, SubredditPromoPolicy, Tone
from src.domain.models import ClassificationResult, DecisionResult, DraftReply, PolicyDecisionTrace, RedditCommentCandidate, RedditPostCandidate, ThreadContext
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


def make_thread(target_comment: RedditCommentCandidate | None = None, thread_id: str = "thread-1"):
    comments = [target_comment] if target_comment else []
    return ThreadContext(
        post=RedditPostCandidate(
            platform_thread_id=thread_id,
            subreddit="PromptEngineering",
            title="How do I organize prompts?",
            body="I keep losing the good ones.",
            url=f"https://example.com/{thread_id}",
            author="poster",
        ),
        comments=comments,
        target_comment=target_comment,
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


def create_draft(target_comment: RedditCommentCandidate | None = None, thread_id: str = "thread-1", status: str = DraftStatus.CREATED.value):
    with db.session_scope() as session:
        threads = ThreadRepository(session)
        decisions = DecisionRepository(session)
        thread_record = threads.upsert_thread(make_thread(target_comment, thread_id))
        target_comment_id = None
        if target_comment:
            target_comment_record = next(comment for comment in thread_record.comments if comment.platform_comment_id == target_comment.platform_comment_id)
            target_comment_id = target_comment_record.id
        classification_record = decisions.create_classification(thread_record.id, target_comment_id, make_classification())
        decision_record = decisions.create_decision(classification_record.id, make_decision())
        draft_record = decisions.create_draft(decision_record.id, make_draft(thread_id), status=status)
        return draft_record.id


def test_reply_target_key_for_top_level_draft(sqlite_session_local):
    draft_id = create_draft()

    with db.session_scope() as session:
        decisions = DecisionRepository(session)
        draft = decisions.get_draft(draft_id)

        assert decisions.reply_target_key_for_draft(draft) == "reddit:thread:thread-1"


def test_reply_target_key_for_comment_draft(sqlite_session_local):
    target_comment = RedditCommentCandidate(platform_comment_id="comment-1", author="a", body="Can this work for teams?")
    draft_id = create_draft(target_comment=target_comment)

    with db.session_scope() as session:
        decisions = DecisionRepository(session)
        draft = decisions.get_draft(draft_id)

        assert decisions.reply_target_key_for_draft(draft) == "reddit:comment:comment-1"


def test_create_pending_attempt_blocks_active_duplicate(sqlite_session_local):
    first_draft_id = create_draft(thread_id="thread-1")
    second_draft_id = create_draft(thread_id="thread-1")

    with db.session_scope() as session:
        decisions = DecisionRepository(session)
        first_attempt = decisions.create_pending_attempt(first_draft_id, "playwright")
        second_attempt = decisions.create_pending_attempt(second_draft_id, "playwright")
        second_draft = decisions.get_draft(second_draft_id)

        assert first_attempt is not None
        assert second_attempt is None
        assert second_draft.status == DraftStatus.DUPLICATE.value


def test_failed_attempts_do_not_block_retry(sqlite_session_local):
    draft_id = create_draft()

    with db.session_scope() as session:
        decisions = DecisionRepository(session)
        failed_attempt = decisions.create_pending_attempt(draft_id, "playwright")
        assert failed_attempt is not None
        decisions.finish_attempt(failed_attempt.id, "failed", error_message="publish_failed")
        retry_attempt = decisions.create_pending_attempt(draft_id, "playwright")

        assert retry_attempt is not None
        assert retry_attempt.id != failed_attempt.id
