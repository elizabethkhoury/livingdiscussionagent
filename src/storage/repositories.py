from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import desc, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.domain.enums import AttemptStatus, DraftStatus
from src.domain.models import AccountHealthSnapshot, ClassificationResult, DecisionResult, DraftReply, EngagementSnapshot
from src.storage import schema


class ThreadRepository:
    def __init__(self, session: Session):
        self.session = session

    def upsert_thread(self, thread_context):
        record = self.session.scalar(select(schema.ThreadRecord).where(schema.ThreadRecord.platform_thread_id == thread_context.post.platform_thread_id))
        if record is None:
            record = schema.ThreadRecord(
                platform_thread_id=thread_context.post.platform_thread_id,
                platform="reddit",
                subreddit=thread_context.post.subreddit,
                title=thread_context.post.title,
                body=thread_context.post.body,
                url=thread_context.post.url,
                author=thread_context.post.author,
                created_at_platform=thread_context.post.created_at_platform,
            )
            self.session.add(record)
            self.session.flush()
        for comment in thread_context.comments:
            existing_comment = self.session.scalar(select(schema.ThreadCommentRecord).where(schema.ThreadCommentRecord.platform_comment_id == comment.platform_comment_id))
            if existing_comment is None:
                self.session.add(
                    schema.ThreadCommentRecord(
                        platform_comment_id=comment.platform_comment_id,
                        thread_id=record.id,
                        author=comment.author,
                        body=comment.body,
                        created_at_platform=comment.created_at_platform,
                    )
                )
        self.session.flush()
        return record

    def get_thread_by_platform_id(self, platform_thread_id: str):
        return self.session.scalar(select(schema.ThreadRecord).where(schema.ThreadRecord.platform_thread_id == platform_thread_id))

    def posted_thread_ids(self, lookback_days: int = 14):
        cutoff = datetime.utcnow() - timedelta(days=lookback_days)
        stmt = (
            select(schema.ThreadRecord.platform_thread_id)
            .join(schema.ClassificationRecord, schema.ClassificationRecord.thread_id == schema.ThreadRecord.id)
            .join(schema.DecisionRecord, schema.DecisionRecord.classification_id == schema.ClassificationRecord.id)
            .join(schema.DraftRecord, schema.DraftRecord.decision_id == schema.DecisionRecord.id)
            .join(schema.PostAttemptRecord, schema.PostAttemptRecord.draft_id == schema.DraftRecord.id)
            .where(schema.PostAttemptRecord.posted_at.is_not(None))
            .where(schema.PostAttemptRecord.posted_at >= cutoff)
        )
        return set(self.session.scalars(stmt).all())

    def recent_post_bodies(self, lookback_days: int = 14):
        cutoff = datetime.utcnow() - timedelta(days=lookback_days)
        stmt = (
            select(schema.DraftRecord.body)
            .join(schema.PostAttemptRecord, schema.PostAttemptRecord.draft_id == schema.DraftRecord.id)
            .where(schema.PostAttemptRecord.posted_at.is_not(None))
            .where(schema.PostAttemptRecord.posted_at >= cutoff)
        )
        return list(self.session.scalars(stmt).all())

    def recently_classified_platform_thread_ids(self, hours: int = 24):
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        stmt = (
            select(schema.ThreadRecord.platform_thread_id)
            .join(schema.ClassificationRecord, schema.ClassificationRecord.thread_id == schema.ThreadRecord.id)
            .where(schema.ClassificationRecord.created_at >= cutoff)
        )
        return set(self.session.scalars(stmt).all())

    def count_posts_for_subreddit_since(self, subreddit: str, since: datetime):
        stmt = (
            select(func.count(schema.PostAttemptRecord.id))
            .join(schema.DraftRecord, schema.DraftRecord.id == schema.PostAttemptRecord.draft_id)
            .join(schema.DecisionRecord, schema.DecisionRecord.id == schema.DraftRecord.decision_id)
            .join(schema.ClassificationRecord, schema.ClassificationRecord.id == schema.DecisionRecord.classification_id)
            .join(schema.ThreadRecord, schema.ThreadRecord.id == schema.ClassificationRecord.thread_id)
            .where(schema.ThreadRecord.subreddit == subreddit)
            .where(schema.PostAttemptRecord.posted_at >= since)
        )
        return self.session.scalar(stmt) or 0

    def count_posts_since(self, since: datetime):
        stmt = select(func.count(schema.PostAttemptRecord.id)).where(schema.PostAttemptRecord.posted_at >= since)
        return self.session.scalar(stmt) or 0


class DecisionRepository:
    def __init__(self, session: Session):
        self.session = session

    def create_classification(self, thread_id: int, target_comment_id: int | None, result: ClassificationResult):
        record = schema.ClassificationRecord(
            thread_id=thread_id,
            target_comment_id=target_comment_id,
            intent=result.intent,
            relevance_score=result.relevance_score,
            commercial_opportunity=result.commercial_opportunity.value,
            value_add_score=result.value_add_score,
            policy_risk_score=result.policy_risk_score,
            promo_fit_score=result.promo_fit_score,
            tone=result.tone.value,
            subreddit_promo_policy=result.subreddit_promo_policy.value,
            duplicate_similarity_score=result.duplicate_similarity_score,
            reason_codes_json=result.reason_codes,
        )
        self.session.add(record)
        self.session.flush()
        return record

    def create_decision(self, classification_id: int, decision: DecisionResult):
        record = schema.DecisionRecord(
            classification_id=classification_id,
            action=decision.action.value,
            promotion_mode=decision.promotion_mode.value,
            requires_review=decision.requires_review,
            trace_json=decision.trace.model_dump(),
        )
        self.session.add(record)
        self.session.flush()
        return record

    def create_draft(self, decision_id: int, draft: DraftReply, status: str = DraftStatus.CREATED.value):
        record = schema.DraftRecord(
            decision_id=decision_id,
            body=draft.body,
            strategy=draft.strategy.value,
            contains_link=draft.contains_link,
            disclosure_text=draft.disclosure_text,
            autopost_eligible=draft.autopost_eligible,
            evaluation_json=draft.evaluation.model_dump() if draft.evaluation else {},
            status=status,
        )
        self.session.add(record)
        self.session.flush()
        return record

    def set_draft_status(self, draft_id: int, status: str):
        record = self.session.get(schema.DraftRecord, draft_id)
        if record:
            record.status = status
            self.session.flush()
        return record

    def queue_review(self, draft_id: int, reason: str):
        draft = self.session.get(schema.DraftRecord, draft_id)
        if draft is None:
            raise ValueError(f"Unknown draft {draft_id}")
        record = schema.ReviewRecord(
            draft_id=draft_id,
            status="pending",
            review_reason=reason,
        )
        self.session.add(record)
        draft.status = DraftStatus.QUEUED.value
        self.session.flush()
        return record

    def reply_target_key_for_draft(self, draft):
        classification = draft.decision.classification
        if classification.target_comment is not None:
            return f"reddit:comment:{classification.target_comment.platform_comment_id}"
        return f"reddit:thread:{classification.thread.platform_thread_id}"

    def has_active_attempt_for_target(self, reply_target_key: str):
        stmt = select(func.count(schema.PostAttemptRecord.id)).where(
            schema.PostAttemptRecord.reply_target_key == reply_target_key,
            schema.PostAttemptRecord.status.in_([AttemptStatus.PENDING.value, AttemptStatus.POSTED.value]),
        )
        return bool(self.session.scalar(stmt))

    def create_pending_attempt(self, draft_id: int, transport: str):
        draft = self.session.get(schema.DraftRecord, draft_id)
        if draft is None:
            raise ValueError(f"Unknown draft {draft_id}")
        if draft.status in {DraftStatus.POSTED.value, DraftStatus.PUBLISHING.value, DraftStatus.REJECTED.value, DraftStatus.DUPLICATE.value}:
            return None
        reply_target_key = self.reply_target_key_for_draft(draft)
        if self.has_active_attempt_for_target(reply_target_key):
            self.mark_duplicate_draft(draft_id, f"active_attempt_for_{reply_target_key}")
            return None
        record = schema.PostAttemptRecord(
            draft_id=draft_id,
            reply_target_key=reply_target_key,
            transport=transport,
            status=AttemptStatus.PENDING.value,
        )
        nested = self.session.begin_nested()
        try:
            self.session.add(record)
            draft.status = DraftStatus.PUBLISHING.value
            self.session.flush()
            nested.commit()
        except IntegrityError:
            nested.rollback()
            self.mark_duplicate_draft(draft_id, f"active_attempt_for_{reply_target_key}")
            return None
        return record

    def finish_attempt(self, attempt_id: int, status: str, posted_comment_id: str | None = None, error_message: str | None = None):
        record = self.session.get(schema.PostAttemptRecord, attempt_id)
        if record is None:
            raise ValueError(f"Unknown post attempt {attempt_id}")
        record.status = status
        record.posted_comment_id = posted_comment_id
        record.error_message = error_message
        record.posted_at = datetime.utcnow() if status == AttemptStatus.POSTED.value else None
        draft = self.session.get(schema.DraftRecord, record.draft_id)
        if draft:
            draft.status = DraftStatus.POSTED.value if status == AttemptStatus.POSTED.value else DraftStatus.FAILED.value
        self.session.flush()
        return record

    def mark_duplicate_draft(self, draft_id: int, reason: str):
        draft = self.session.get(schema.DraftRecord, draft_id)
        if draft is None:
            raise ValueError(f"Unknown draft {draft_id}")
        draft.status = DraftStatus.DUPLICATE.value
        self.session.add(schema.SystemEventRecord(event_type="duplicate_reply_target", payload_json={"draft_id": draft_id, "reason": reason}))
        self.session.flush()
        return draft

    def record_attempt(
        self,
        draft_id: int,
        transport: str,
        status: str,
        posted_comment_id: str | None = None,
        error_message: str | None = None,
        reply_target_key: str | None = None,
    ):
        draft = self.session.get(schema.DraftRecord, draft_id)
        if reply_target_key is None and draft is not None:
            reply_target_key = self.reply_target_key_for_draft(draft)
        record = schema.PostAttemptRecord(
            draft_id=draft_id,
            reply_target_key=reply_target_key,
            transport=transport,
            status=status,
            posted_comment_id=posted_comment_id,
            error_message=error_message,
            posted_at=datetime.utcnow() if status == "posted" else None,
        )
        self.session.add(record)
        self.session.flush()
        return record

    def record_snapshot(self, snapshot: EngagementSnapshot):
        record = schema.EngagementSnapshotRecord(
            post_attempt_id=snapshot.post_attempt_id,
            score=snapshot.score,
            reply_count=snapshot.reply_count,
            is_deleted=snapshot.is_deleted,
            is_removed=snapshot.is_removed,
            is_locked=snapshot.is_locked,
            captured_at=snapshot.captured_at,
        )
        self.session.add(record)
        self.session.flush()
        return record

    def list_pending_reviews(self):
        stmt = (
            select(schema.ReviewRecord)
            .join(schema.DraftRecord, schema.DraftRecord.id == schema.ReviewRecord.draft_id)
            .where(schema.ReviewRecord.status == "pending")
            .order_by(schema.ReviewRecord.id.asc())
        )
        return list(self.session.scalars(stmt).all())

    def get_review(self, review_id: int):
        return self.session.get(schema.ReviewRecord, review_id)

    def get_draft(self, draft_id: int):
        return self.session.get(schema.DraftRecord, draft_id)

    def get_attempts(self):
        stmt = select(schema.PostAttemptRecord).order_by(desc(schema.PostAttemptRecord.created_at))
        return list(self.session.scalars(stmt).all())

    def list_drafts_by_status(self, status: str):
        stmt = select(schema.DraftRecord).where(schema.DraftRecord.status == status).order_by(schema.DraftRecord.id.asc())
        return list(self.session.scalars(stmt).all())

    def get_thread_details(self, platform_thread_id: str):
        stmt = select(schema.ThreadRecord).where(schema.ThreadRecord.platform_thread_id == platform_thread_id)
        return self.session.scalar(stmt)

    def recent_negative_signals(self, hours: int = 24):
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        stmt = select(func.count(schema.EngagementSnapshotRecord.id)).where(
            schema.EngagementSnapshotRecord.captured_at >= cutoff,
            schema.EngagementSnapshotRecord.is_removed.is_(True),
        )
        return self.session.scalar(stmt) or 0

    def recent_rate_limit_events(self, hours: int = 12):
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        stmt = select(func.count(schema.SystemEventRecord.id)).where(
            schema.SystemEventRecord.created_at >= cutoff,
            schema.SystemEventRecord.event_type == "rate_limit",
        )
        return self.session.scalar(stmt) or 0


class LearningRepository:
    def __init__(self, session: Session):
        self.session = session

    def add_learning_example(self, thread_id: int, draft_id: int, features: dict, outcome_label: str, reward_score: float):
        record = schema.LearningExampleRecord(
            thread_id=thread_id,
            draft_id=draft_id,
            features_json=features,
            outcome_label=outcome_label,
            reward_score=reward_score,
        )
        self.session.add(record)
        self.session.flush()
        return record

    def recent_examples(self, days: int = 7):
        cutoff = datetime.utcnow() - timedelta(days=days)
        stmt = select(schema.LearningExampleRecord).where(schema.LearningExampleRecord.created_at >= cutoff)
        return list(self.session.scalars(stmt).all())

    def learning_examples_between(self, start: datetime, end: datetime):
        stmt = (
            select(schema.LearningExampleRecord)
            .where(schema.LearningExampleRecord.created_at >= start)
            .where(schema.LearningExampleRecord.created_at < end)
            .order_by(schema.LearningExampleRecord.created_at.asc())
        )
        return list(self.session.scalars(stmt).all())

    def post_attempts_between(self, start: datetime, end: datetime):
        stmt = (
            select(schema.PostAttemptRecord)
            .where(schema.PostAttemptRecord.created_at >= start)
            .where(schema.PostAttemptRecord.created_at < end)
            .order_by(schema.PostAttemptRecord.created_at.asc())
        )
        return list(self.session.scalars(stmt).all())

    def reviews_between(self, start: datetime, end: datetime):
        stmt = (
            select(schema.ReviewRecord)
            .where(schema.ReviewRecord.reviewed_at.is_not(None))
            .where(schema.ReviewRecord.reviewed_at >= start)
            .where(schema.ReviewRecord.reviewed_at < end)
            .order_by(schema.ReviewRecord.reviewed_at.asc())
        )
        return list(self.session.scalars(stmt).all())

    def engagement_snapshots_between(self, start: datetime, end: datetime):
        stmt = (
            select(schema.EngagementSnapshotRecord)
            .where(schema.EngagementSnapshotRecord.captured_at >= start)
            .where(schema.EngagementSnapshotRecord.captured_at < end)
            .order_by(schema.EngagementSnapshotRecord.captured_at.asc())
        )
        return list(self.session.scalars(stmt).all())

    def system_events_between(self, start: datetime, end: datetime, event_type: str | None = None):
        stmt = (
            select(schema.SystemEventRecord)
            .where(schema.SystemEventRecord.created_at >= start)
            .where(schema.SystemEventRecord.created_at < end)
            .order_by(schema.SystemEventRecord.created_at.asc())
        )
        if event_type is not None:
            stmt = stmt.where(schema.SystemEventRecord.event_type == event_type)
        return list(self.session.scalars(stmt).all())

    def store_strategy_weights(self, version: int, weights: dict[str, float]):
        records = []
        for strategy, weight in weights.items():
            record = schema.StrategyWeightRecord(strategy=strategy, weight=weight, version=version)
            self.session.add(record)
            records.append(record)
        self.session.flush()
        return records

    def latest_strategy_weights(self):
        version = self.session.scalar(select(func.max(schema.StrategyWeightRecord.version)))
        if version is None:
            return {}
        stmt = select(schema.StrategyWeightRecord).where(schema.StrategyWeightRecord.version == version)
        return {record.strategy: record.weight for record in self.session.scalars(stmt)}

    def latest_strategy_version(self):
        return self.session.scalar(select(func.max(schema.StrategyWeightRecord.version))) or 0

    def log_event(self, event_type: str, payload: dict):
        record = schema.SystemEventRecord(event_type=event_type, payload_json=payload)
        self.session.add(record)
        self.session.flush()
        return record

    def latest_threshold_event(self):
        stmt = select(schema.SystemEventRecord).where(schema.SystemEventRecord.event_type == "threshold_update").order_by(desc(schema.SystemEventRecord.id))
        return self.session.scalar(stmt)


class AccountHealthRepository:
    def __init__(self, session: Session):
        self.session = session

    def upsert_daily_snapshot(self, snapshot: AccountHealthSnapshot):
        record = self.session.scalar(
            select(schema.AccountHealthSnapshotRecord).where(
                schema.AccountHealthSnapshotRecord.username == snapshot.username,
                schema.AccountHealthSnapshotRecord.snapshot_date == snapshot.snapshot_date,
            )
        )
        values = snapshot.model_dump()
        if record is None:
            record = schema.AccountHealthSnapshotRecord(**values)
            self.session.add(record)
        else:
            for key, value in values.items():
                setattr(record, key, value)
        self.session.flush()
        return record

    def latest_snapshot(self, username: str):
        stmt = (
            select(schema.AccountHealthSnapshotRecord)
            .where(schema.AccountHealthSnapshotRecord.username == username)
            .order_by(desc(schema.AccountHealthSnapshotRecord.snapshot_date), desc(schema.AccountHealthSnapshotRecord.captured_at), desc(schema.AccountHealthSnapshotRecord.id))
        )
        return self.session.scalar(stmt)

    def latest_snapshot_before(self, username: str, snapshot_date: date):
        stmt = (
            select(schema.AccountHealthSnapshotRecord)
            .where(schema.AccountHealthSnapshotRecord.username == username)
            .where(schema.AccountHealthSnapshotRecord.snapshot_date < snapshot_date)
            .order_by(desc(schema.AccountHealthSnapshotRecord.snapshot_date), desc(schema.AccountHealthSnapshotRecord.captured_at), desc(schema.AccountHealthSnapshotRecord.id))
        )
        return self.session.scalar(stmt)

    def latest_active_halt(self):
        stmt = select(schema.AgentHaltRecord).where(schema.AgentHaltRecord.resolved_at.is_(None)).order_by(desc(schema.AgentHaltRecord.id))
        return self.session.scalar(stmt)

    def create_halt(self, reason_code: str, reason: str, snapshot_id: int | None, thresholds: dict, observed: dict):
        record = schema.AgentHaltRecord(
            reason_code=reason_code,
            reason=reason,
            triggered_by_snapshot_id=snapshot_id,
            thresholds_json=thresholds,
            observed_json=observed,
        )
        self.session.add(record)
        self.session.flush()
        return record

    def resolve_active_halt(self, resolved_by: str = "manual", note: str | None = None):
        record = self.latest_active_halt()
        if record is None:
            return None
        record.resolved_at = datetime.utcnow()
        record.resolved_by = resolved_by
        record.resolution_note = note
        self.session.flush()
        return record

    def recent_posted_attempts_for_health(self, lookback_days: int):
        cutoff = datetime.utcnow() - timedelta(days=lookback_days)
        stmt = (
            select(schema.PostAttemptRecord)
            .where(schema.PostAttemptRecord.status == AttemptStatus.POSTED.value)
            .where(schema.PostAttemptRecord.posted_at.is_not(None))
            .where(schema.PostAttemptRecord.posted_at >= cutoff)
            .order_by(schema.PostAttemptRecord.posted_at.asc())
        )
        return list(self.session.scalars(stmt).all())

    def latest_snapshot_for_attempt(self, post_attempt_id: int):
        stmt = (
            select(schema.EngagementSnapshotRecord)
            .where(schema.EngagementSnapshotRecord.post_attempt_id == post_attempt_id)
            .order_by(desc(schema.EngagementSnapshotRecord.captured_at), desc(schema.EngagementSnapshotRecord.id))
        )
        return self.session.scalar(stmt)

    def log_event(self, event_type: str, payload: dict):
        record = schema.SystemEventRecord(event_type=event_type, payload_json=payload)
        self.session.add(record)
        self.session.flush()
        return record

    def recent_health_events(self, limit: int = 20):
        event_types = [
            "account_health_snapshot_recorded",
            "account_health_fetch_failed",
            "account_health_missing_username",
            "agent_halted",
            "operation_blocked_by_halt",
            "agent_resumed",
        ]
        stmt = (
            select(schema.SystemEventRecord)
            .where(schema.SystemEventRecord.event_type.in_(event_types))
            .order_by(desc(schema.SystemEventRecord.created_at), desc(schema.SystemEventRecord.id))
            .limit(limit)
        )
        return list(self.session.scalars(stmt).all())
