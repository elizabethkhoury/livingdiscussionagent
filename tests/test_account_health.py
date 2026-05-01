from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import main
import src.storage.db as db
from src.app.settings import get_settings
from src.domain.models import AccountHealthSnapshot
from src.execute.poster import PostingService
from src.monitor.account_health import AccountHealthService
from src.runtime.halt_guard import operation_blocked_result
from src.storage import schema
from src.storage.repositories import AccountHealthRepository
from src.workers.ingest_worker import IngestWorker
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
    monkeypatch.setattr(main, "engine", engine)
    yield test_session_local
    db.Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture(autouse=True)
def clear_settings_cache(monkeypatch: pytest.MonkeyPatch):
    get_settings.cache_clear()
    monkeypatch.setenv("REDDIT_USERNAME", "agent")
    yield
    get_settings.cache_clear()


def make_snapshot(snapshot_date: date, total: int = 20, tracked_score: int = 0):
    return AccountHealthSnapshot(
        username="agent",
        snapshot_date=snapshot_date,
        link_karma=total // 2,
        comment_karma=total - (total // 2),
        total_karma=total,
        tracked_post_score_total=tracked_score,
        source_payload_json={"name": "agent"},
    )


class FakeFetcher:
    def __init__(self, snapshot: AccountHealthSnapshot | None = None, exc: Exception | None = None):
        self.snapshot = snapshot
        self.exc = exc

    def fetch(self, username: str, snapshot_date: date):
        if self.exc:
            raise self.exc
        snapshot = self.snapshot or make_snapshot(snapshot_date)
        return snapshot.model_copy(update={"username": username, "snapshot_date": snapshot_date})


class FakeEngagementFetcher:
    def __init__(self):
        self.calls = []

    def refresh(self, post_attempt_id: int):
        self.calls.append(post_attempt_id)


def create_halt(reason_code: str = "total_karma_below_minimum"):
    with db.session_scope() as session:
        repo = AccountHealthRepository(session)
        return repo.create_halt(reason_code, "account health breached", None, {"min_total_karma": 1}, {"total_karma": 0}).id


def test_upsert_daily_snapshot_and_latest_queries(sqlite_session_local):
    with db.session_scope() as session:
        repo = AccountHealthRepository(session)
        repo.upsert_daily_snapshot(make_snapshot(date(2026, 4, 29), total=10))
        updated = repo.upsert_daily_snapshot(make_snapshot(date(2026, 4, 29), total=20))
        repo.upsert_daily_snapshot(make_snapshot(date(2026, 4, 30), total=30))

        assert updated.total_karma == 20
        assert session.query(schema.AccountHealthSnapshotRecord).count() == 2
        assert repo.latest_snapshot("agent").total_karma == 30
        assert repo.latest_snapshot_before("agent", date(2026, 4, 30)).total_karma == 20


def test_create_and_resolve_active_halt(sqlite_session_local):
    with db.session_scope() as session:
        repo = AccountHealthRepository(session)
        halt = repo.create_halt("total_karma_below_minimum", "too low", None, {}, {})

        assert repo.latest_active_halt().id == halt.id
        repo.resolve_active_halt(resolved_by="test", note="ok")
        assert repo.latest_active_halt() is None


def test_active_halt_query_ignores_resolved_halts(sqlite_session_local):
    with db.session_scope() as session:
        repo = AccountHealthRepository(session)
        first = repo.create_halt("old", "old halt", None, {}, {})
        repo.resolve_active_halt(resolved_by="test")
        second = repo.create_halt("new", "new halt", None, {}, {})

        assert first.resolved_at is not None
        assert repo.latest_active_halt().id == second.id


def test_first_healthy_snapshot_records_without_halt(sqlite_session_local):
    service = AccountHealthService(
        fetcher=FakeFetcher(make_snapshot(date(2026, 4, 30), total=20)),
        engagement_fetcher=FakeEngagementFetcher(),
        today_provider=lambda: date(2026, 4, 30),
    )

    result = service.run_once()

    assert result["status"] == "healthy"
    with db.session_scope() as session:
        assert session.query(schema.AccountHealthSnapshotRecord).count() == 1
        assert AccountHealthRepository(session).latest_active_halt() is None


def test_absolute_karma_below_minimum_creates_halt(monkeypatch, sqlite_session_local):
    monkeypatch.setenv("ACCOUNT_HEALTH_MIN_TOTAL_KARMA", "10")
    get_settings.cache_clear()
    service = AccountHealthService(
        fetcher=FakeFetcher(make_snapshot(date(2026, 4, 30), total=0)),
        engagement_fetcher=FakeEngagementFetcher(),
        today_provider=lambda: date(2026, 4, 30),
    )

    result = service.run_once()

    assert result["status"] == "halted"
    assert result["evaluation"]["reason_codes"] == ["total_karma_below_minimum"]


def test_daily_karma_drop_creates_halt(sqlite_session_local):
    with db.session_scope() as session:
        AccountHealthRepository(session).upsert_daily_snapshot(make_snapshot(date(2026, 4, 29), total=100))
    service = AccountHealthService(
        fetcher=FakeFetcher(make_snapshot(date(2026, 4, 30), total=70)),
        engagement_fetcher=FakeEngagementFetcher(),
        today_provider=lambda: date(2026, 4, 30),
    )

    result = service.run_once()

    assert result["status"] == "halted"
    assert "daily_total_karma_drop_exceeded" in result["evaluation"]["reason_codes"]


def test_daily_tracked_score_delta_creates_halt(sqlite_session_local):
    with db.session_scope() as session:
        AccountHealthRepository(session).upsert_daily_snapshot(make_snapshot(date(2026, 4, 29), total=100, tracked_score=10))
    service = AccountHealthService(
        fetcher=FakeFetcher(make_snapshot(date(2026, 4, 30), total=100)),
        engagement_fetcher=FakeEngagementFetcher(),
        today_provider=lambda: date(2026, 4, 30),
    )

    result = service.run_once()

    assert result["status"] == "halted"
    assert "daily_tracked_post_score_delta_below_minimum" in result["evaluation"]["reason_codes"]


def test_existing_halt_is_not_duplicated(monkeypatch, sqlite_session_local):
    monkeypatch.setenv("ACCOUNT_HEALTH_MIN_TOTAL_KARMA", "10")
    get_settings.cache_clear()
    create_halt()
    service = AccountHealthService(
        fetcher=FakeFetcher(make_snapshot(date(2026, 4, 30), total=0)),
        engagement_fetcher=FakeEngagementFetcher(),
        today_provider=lambda: date(2026, 4, 30),
    )

    result = service.run_once()

    assert result["status"] == "already_halted"
    with db.session_scope() as session:
        assert session.query(schema.AgentHaltRecord).count() == 1


def test_fetch_failure_logs_event_without_halt(sqlite_session_local):
    service = AccountHealthService(fetcher=FakeFetcher(exc=ValueError("bad response")), engagement_fetcher=FakeEngagementFetcher(), today_provider=lambda: date(2026, 4, 30))

    result = service.run_once()

    assert result["status"] == "failed"
    with db.session_scope() as session:
        assert AccountHealthRepository(session).latest_active_halt() is None
        event_record = session.query(schema.SystemEventRecord).filter_by(event_type="account_health_fetch_failed").one()
        assert event_record.payload_json["error"] == "bad response"


def test_missing_username_logs_event_without_halt(monkeypatch, sqlite_session_local):
    monkeypatch.setenv("REDDIT_USERNAME", "")
    get_settings.cache_clear()
    service = AccountHealthService(fetcher=FakeFetcher(), engagement_fetcher=FakeEngagementFetcher(), today_provider=lambda: date(2026, 4, 30))

    result = service.run_once()

    assert result["status"] == "skipped"
    with db.session_scope() as session:
        assert AccountHealthRepository(session).latest_active_halt() is None
        session.query(schema.SystemEventRecord).filter_by(event_type="account_health_missing_username").one()


def test_operation_blocked_result_logs_halt_event(sqlite_session_local):
    halt_id = create_halt()

    result = operation_blocked_result("ingest-once")

    assert result["status"] == "halted"
    assert result["halt_id"] == halt_id
    with db.session_scope() as session:
        event_record = session.query(schema.SystemEventRecord).filter_by(event_type="operation_blocked_by_halt").one()
        assert event_record.payload_json["command"] == "ingest-once"


def test_ingest_worker_noops_when_halted(sqlite_session_local):
    create_halt()
    worker = IngestWorker()

    result = worker.run_once()

    assert result["status"] == "halted"


def test_review_worker_noops_when_halted(sqlite_session_local):
    create_halt()
    worker = ReviewWorker()

    result = asyncio.run(worker.run_once())

    assert result["status"] == "halted"


def test_posting_service_can_post_blocks_when_halted(sqlite_session_local):
    create_halt("daily_total_karma_drop_exceeded")

    allowed, state = PostingService().can_post("PromptEngineering")

    assert allowed is False
    assert state.failure_events == ["agent_halted:daily_total_karma_drop_exceeded"]


def test_account_health_command_runs_while_halted(monkeypatch, sqlite_session_local):
    create_halt()

    class FakeService:
        def run_once(self):
            return {"status": "already_halted"}

    monkeypatch.setattr(main, "AccountHealthService", FakeService)

    result = asyncio.run(main.run_async_command("account-health-once"))

    assert result == {"status": "already_halted"}


def test_resume_agent_command_resolves_halt(sqlite_session_local):
    create_halt()

    result = asyncio.run(main.run_async_command("resume-agent"))

    assert result["status"] == "resumed"
    with db.session_scope() as session:
        assert AccountHealthRepository(session).latest_active_halt() is None


def test_recent_posted_attempts_and_latest_snapshot_for_attempt(sqlite_session_local):
    with db.session_scope() as session:
        thread = schema.ThreadRecord(platform_thread_id="thread-1", subreddit="PromptEngineering", title="Question", body="", url="https://example.com", author="poster")
        session.add(thread)
        session.flush()
        classification = schema.ClassificationRecord(
            thread_id=thread.id,
            target_comment_id=None,
            intent="question",
            relevance_score=1.0,
            commercial_opportunity="low",
            value_add_score=1.0,
            policy_risk_score=0.0,
            promo_fit_score=0.0,
            tone="beginner",
            subreddit_promo_policy="allow",
            duplicate_similarity_score=0.0,
            reason_codes_json=[],
        )
        session.add(classification)
        session.flush()
        decision = schema.DecisionRecord(
            classification_id=classification.id,
            action="autopost_info",
            promotion_mode="none",
            requires_review=False,
            trace_json={},
        )
        session.add(decision)
        session.flush()
        draft = schema.DraftRecord(
            decision_id=decision.id,
            body="Helpful reply",
            strategy="educational",
            contains_link=False,
            autopost_eligible=True,
            evaluation_json={},
            status="posted",
        )
        session.add(draft)
        session.flush()
        attempt = schema.PostAttemptRecord(
            draft_id=draft.id,
            reply_target_key="reddit:thread:t1",
            transport="test",
            status="posted",
            posted_comment_id="comment",
            posted_at=datetime.utcnow() - timedelta(days=1),
        )
        session.add(attempt)
        session.flush()
        session.add(schema.EngagementSnapshotRecord(post_attempt_id=attempt.id, score=3, reply_count=0))
        session.add(schema.EngagementSnapshotRecord(post_attempt_id=attempt.id, score=5, reply_count=0))
        session.flush()
        repo = AccountHealthRepository(session)

        assert [item.id for item in repo.recent_posted_attempts_for_health(30)] == [attempt.id]
        assert repo.latest_snapshot_for_attempt(attempt.id).score == 5
