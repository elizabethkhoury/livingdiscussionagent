from __future__ import annotations

from datetime import datetime, timedelta

from src.app.config import get_default_thresholds
from src.app.settings import get_settings
from src.execute.poster import PostingService
from src.runtime.active_hours import hours_until_active, is_within_active_hours
from src.runtime.halt_guard import operation_blocked_result
from src.storage import schema
from src.storage.db import session_scope
from src.storage.repositories import DecisionRepository
from sqlalchemy import func, select


class ReviewWorker:
    def __init__(self):
        self.poster = PostingService()
        self.thresholds = get_default_thresholds()
        self.settings = get_settings()

    def _count_recent_promo_posts(self, session) -> int:
        """How many PromptHunt-mentioning posts went up in the last 24h?"""
        cutoff = datetime.utcnow() - timedelta(days=1)
        stmt = (
            select(func.count(schema.PostAttemptRecord.id))
            .join(schema.DraftRecord, schema.DraftRecord.id == schema.PostAttemptRecord.draft_id)
            .join(schema.DecisionRecord, schema.DecisionRecord.id == schema.DraftRecord.decision_id)
            .where(schema.PostAttemptRecord.posted_at.is_not(None))
            .where(schema.PostAttemptRecord.posted_at >= cutoff)
            .where(schema.DecisionRecord.promotion_mode != "none")
        )
        return session.scalar(stmt) or 0

    async def run_once(self):
        blocked = operation_blocked_result("review-once")
        if blocked is not None:
            return blocked
        if not is_within_active_hours():
            wait_h = hours_until_active()
            return [{"skipped": "outside_active_hours", "hours_until_active": round(wait_h, 1)}]
        with session_scope() as session:
            repo = DecisionRepository(session)
            pending_drafts = (
                repo.list_drafts_by_status("created")
                + repo.list_drafts_by_status("queued")
                + repo.list_drafts_by_status("approved")
            )
            recent_promo_posts = self._count_recent_promo_posts(session)
            promo_budget = max(0, self.settings.max_promo_posts_per_day - recent_promo_posts)
            eligible = []
            for draft in pending_drafts:
                if draft.status == "approved":
                    eligible.append((draft.id, draft.decision.classification.thread.subreddit, draft.decision.promotion_mode))
                    continue
                evaluation = draft.evaluation_json or {}
                if not draft.autopost_eligible:
                    continue
                # Quality gate (same for promo and non-promo drafts).
                if evaluation.get("overall_score", 0) < 0.70:
                    continue
                if evaluation.get("authenticity_score", 0) < 0.80:
                    continue
                if evaluation.get("specificity_score", 0) < 0.65:
                    continue
                if evaluation.get("policy_compliance_score", 0) < 0.85:
                    continue
                # Promo posts have a higher specificity bar AND a tighter promo-pressure ceiling —
                # we only ship PromptHunt mentions when the thread is a clean fit and the reply
                # doesn't read as a pitch.
                is_promo = draft.decision.promotion_mode != "none"
                if is_promo:
                    if promo_budget <= 0:
                        continue  # over the daily promo cap
                    if evaluation.get("specificity_score", 0) < 0.75:
                        continue
                    if evaluation.get("promo_pressure_score", 1) > 0.15:
                        continue
                    promo_budget -= 1
                else:
                    if evaluation.get("promo_pressure_score", 1) > 0.25:
                        continue
                eligible.append((draft.id, draft.decision.classification.thread.subreddit, draft.decision.promotion_mode))
        posted = []
        skipped_count = 0
        for draft_id, subreddit, promotion_mode in eligible:
            try:
                attempt = await self.poster.publish_draft(draft_id, subreddit)
            except RuntimeError as exc:
                # Circuit breaker hit (hourly cap, daily cap, or per-subreddit cap).
                # Skip this draft and try the next one — could be in a different
                # subreddit where the per-sub cap isn't yet hit. If hourly cap is
                # the cause, *all* subsequent drafts will also raise and we'll
                # just iterate through them quickly (no Reddit calls).
                posted.append({"draft_id": draft_id, "skipped": str(exc)})
                skipped_count += 1
                # Safety: if we've skipped 20+ in a row, the hourly/daily cap is
                # almost certainly the cause — stop wasting time.
                if skipped_count >= 20:
                    break
                continue
            if attempt is not None:
                posted.append(attempt)
                skipped_count = 0  # reset run-counter on success
        return posted
