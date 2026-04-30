from __future__ import annotations

from datetime import date, datetime

import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import src.storage.db as db
from src.domain.models import DiaryEntry
from src.learn.diary_builder import DiaryBuilder, build_daily_entry, build_monthly_recap
from src.storage import schema
from src.storage.repositories import LearningRepository


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


def seed_activity(activity_time: datetime):
    with db.session_scope() as session:
        thread = schema.ThreadRecord(
            platform_thread_id="thread-1",
            platform="reddit",
            subreddit="PromptEngineering",
            title="How do I organize prompts?",
            body="I keep losing context.",
            url="https://example.com/thread-1",
            author="poster",
        )
        session.add(thread)
        session.flush()
        classification = schema.ClassificationRecord(
            thread_id=thread.id,
            target_comment_id=None,
            intent="question",
            relevance_score=0.9,
            commercial_opportunity="high",
            value_add_score=0.86,
            policy_risk_score=0.2,
            promo_fit_score=0.84,
            tone="beginner",
            subreddit_promo_policy="allow",
            duplicate_similarity_score=0.02,
            reason_codes_json=[],
            created_at=activity_time,
        )
        session.add(classification)
        session.flush()
        decision = schema.DecisionRecord(
            classification_id=classification.id,
            action="autopost_info",
            promotion_mode="none",
            requires_review=False,
            trace_json={},
            created_at=activity_time,
        )
        session.add(decision)
        session.flush()
        draft = schema.DraftRecord(
            decision_id=decision.id,
            body="A practical reply.",
            strategy="educational",
            contains_link=False,
            disclosure_text=None,
            autopost_eligible=True,
            evaluation_json={},
            status="approved",
            created_at=activity_time,
        )
        session.add(draft)
        session.flush()
        review = schema.ReviewRecord(
            draft_id=draft.id,
            status="approved",
            review_reason="test",
            reviewed_at=activity_time,
        )
        attempt = schema.PostAttemptRecord(
            draft_id=draft.id,
            transport="test",
            status="posted",
            posted_comment_id="comment-1",
            created_at=activity_time,
            posted_at=activity_time,
        )
        example = schema.LearningExampleRecord(
            thread_id=thread.id,
            draft_id=draft.id,
            features_json={"intent": "question"},
            outcome_label="positive",
            reward_score=0.7,
            created_at=activity_time,
        )
        event_record = schema.SystemEventRecord(
            event_type="threshold_update",
            payload_json={"relevance_threshold": 0.66},
            created_at=activity_time,
        )
        session.add_all([review, attempt, example, event_record])
        session.flush()
        snapshot = schema.EngagementSnapshotRecord(
            post_attempt_id=attempt.id,
            score=2,
            reply_count=1,
            is_deleted=False,
            is_removed=False,
            is_locked=False,
            captured_at=activity_time,
        )
        session.add(snapshot)


def test_build_daily_entry_from_database_activity(sqlite_session_local):
    seed_activity(datetime(2026, 4, 29, 12, 0, 0))

    with db.session_scope() as session:
        entry = build_daily_entry(LearningRepository(session), date(2026, 4, 30))

    assert entry.date == date(2026, 4, 30)
    assert entry.metrics["post_attempts"] == 1
    assert entry.metrics["attempts_posted"] == 1
    assert entry.metrics["reviews_approved"] == 1
    assert entry.metrics["engagement_snapshots"] == 1
    assert entry.metrics["average_reward"] == 0.7
    assert "Recent outcomes were strong" in entry.what_i_learned


def test_build_monthly_recap_summarizes_entries():
    recap = build_monthly_recap(
        "2026-04",
        [
            schema_entry(date(2026, 4, 29), 0.7, removals=0),
            schema_entry(date(2026, 4, 30), 0.2, removals=1),
        ],
    )

    assert recap.month == "2026-04"
    assert "2 daily entries" in recap.summary
    assert recap.lessons
    assert "review routing" in recap.strategy_adjustments[0]
    assert "1 removals" in recap.risk_notes[0]


def test_diary_builder_updates_daily_and_forced_monthly_recap(tmp_path, sqlite_session_local):
    seed_activity(datetime(2026, 4, 29, 12, 0, 0))
    path = tmp_path / "agent_diary.md"

    report = DiaryBuilder(path).update(entry_date=date(2026, 4, 30), force_monthly=True)

    assert report["daily_entry_date"] == "2026-04-30"
    assert report["monthly_recap_month"] == "2026-04"
    text = path.read_text(encoding="utf-8")
    assert "### 2026-04-30" in text
    assert "### 2026-04" in text


def schema_entry(day: date, average_reward: float, removals: int):
    return DiaryEntry(
        date=day,
        yesterday="Summary.",
        what_happened="Things happened.",
        what_i_learned="Lesson.",
        metrics={
            "post_attempts": 1,
            "attempts_posted": 1,
            "attempts_failed": 0,
            "reviews_approved": 1,
            "reviews_rejected": 0,
            "engagement_snapshots": 1,
            "removals": removals,
            "deletions": 0,
            "negative_rewards": 0,
            "threshold_updates": 0,
            "average_reward": average_reward,
        },
    )
