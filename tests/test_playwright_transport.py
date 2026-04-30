from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import src.storage.db as db
from src.domain.enums import CommercialOpportunity, DecisionAction, PromotionMode, ResponseStrategy, RiskLevel, SubredditPromoPolicy, Tone
from src.domain.models import ClassificationResult, DecisionResult, DraftReply, PolicyDecisionTrace, RedditCommentCandidate, RedditPostCandidate, ThreadContext
from src.execute.playwright_transport import PlaywrightPostingTransport
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


def make_thread(target_comment: RedditCommentCandidate | None = None):
    comments = [target_comment] if target_comment else []
    return ThreadContext(
        post=RedditPostCandidate(
            platform_thread_id="thread-1",
            subreddit="PromptEngineering",
            title="How do I organize prompts?",
            body="I keep losing the good ones.",
            url="https://www.reddit.com/r/PromptEngineering/comments/thread-1/example/",
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


def make_draft():
    return DraftReply(
        body="A practical prompt library with notes can help.",
        strategy=ResponseStrategy.EDUCATIONAL,
        promotion_mode=PromotionMode.NONE,
        contains_link=False,
        disclosure_text=None,
        thread_id="thread-1",
        autopost_eligible=True,
    )


def create_draft(target_comment: RedditCommentCandidate | None = None):
    with db.session_scope() as session:
        threads = ThreadRepository(session)
        decisions = DecisionRepository(session)
        thread_record = threads.upsert_thread(make_thread(target_comment))
        target_comment_id = None
        if target_comment:
            target_comment_record = next(comment for comment in thread_record.comments if comment.platform_comment_id == target_comment.platform_comment_id)
            target_comment_id = target_comment_record.id
        classification_record = decisions.create_classification(thread_record.id, target_comment_id, make_classification())
        decision_record = decisions.create_decision(classification_record.id, make_decision())
        draft_record = decisions.create_draft(decision_record.id, make_draft())
        attempt_record = decisions.create_pending_attempt(draft_record.id, "playwright")
        return draft_record.id, attempt_record.id


class FakeAsyncPlaywright:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, _exc_type, _exc, _traceback):
        return False


class FakeContext:
    async def close(self):
        return None


class CapturingTransport(PlaywrightPostingTransport):
    def __init__(self):
        super().__init__()
        self.post_comment_call = None

    async def _make_context(self, _playwright):
        return FakeContext(), object()

    async def _login(self, _page):
        return None

    async def _post_comment(self, page, post_url: str, reply_text: str, target_comment_id: str | None = None):
        self.post_comment_call = {
            "page": page,
            "post_url": post_url,
            "reply_text": reply_text,
            "target_comment_id": target_comment_id,
        }
        return True


def test_publish_passes_target_comment_id(monkeypatch: pytest.MonkeyPatch, sqlite_session_local):
    target_comment = RedditCommentCandidate(platform_comment_id="comment-1", author="a", body="Can this work for teams?")
    draft_id, attempt_id = create_draft(target_comment=target_comment)
    monkeypatch.setattr("src.execute.playwright_transport.async_playwright", lambda: FakeAsyncPlaywright())
    transport = CapturingTransport()

    result = asyncio.run(transport.publish(draft_id, attempt_id))

    assert result.status == "posted"
    assert transport.post_comment_call["target_comment_id"] == "comment-1"

    with db.session_scope() as session:
        attempt = session.get(schema.PostAttemptRecord, attempt_id)

        assert attempt.status == "posted"


class FakePage:
    def __init__(self):
        self.urls = []

    async def goto(self, url: str, wait_until: str):
        self.urls.append((url, wait_until))

    async def wait_for_timeout(self, _timeout: int):
        return None


class SafeFailCommentTransport(PlaywrightPostingTransport):
    def __init__(self):
        super().__init__()
        self.reply_composer_targets = []

    async def _check_rate_limit(self, _page):
        return False

    async def _open_reply_composer(self, _page, target_comment_id: str):
        self.reply_composer_targets.append(target_comment_id)
        return None


def test_comment_reply_fails_when_target_composer_is_missing():
    page = FakePage()
    transport = SafeFailCommentTransport()

    result = asyncio.run(transport._post_comment(page, "https://www.reddit.com/r/x/comments/thread-1/example/", "reply", target_comment_id="comment-1"))

    assert result is False
    assert transport.reply_composer_targets == ["comment-1"]
    assert page.urls == [("https://www.reddit.com/r/x/comments/thread-1/example/comment-1/", "domcontentloaded")]


class TopLevelTransport(PlaywrightPostingTransport):
    def __init__(self):
        super().__init__()
        self.opened_post_composer = False
        self.opened_reply_composer = False

    async def _check_rate_limit(self, _page):
        return False

    async def _open_post_composer(self, _page):
        self.opened_post_composer = True
        return {"x": 1, "y": 1}

    async def _open_reply_composer(self, _page, _target_comment_id: str):
        self.opened_reply_composer = True
        return {"x": 1, "y": 1}

    async def _type_and_submit(self, _page, _editor_coords, _text: str):
        return True


def test_top_level_reply_uses_post_composer():
    page = FakePage()
    transport = TopLevelTransport()

    result = asyncio.run(transport._post_comment(page, "https://www.reddit.com/r/x/comments/thread-1/example/", "reply"))

    assert result is True
    assert transport.opened_post_composer is True
    assert transport.opened_reply_composer is False
