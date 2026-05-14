from __future__ import annotations

from src.app.config import get_default_thresholds
from src.execute.poster import PostingService
from src.runtime.halt_guard import operation_blocked_result
from src.storage.db import session_scope
from src.storage.repositories import DecisionRepository


class ReviewWorker:
    def __init__(self):
        self.poster = PostingService()
        self.thresholds = get_default_thresholds()

    async def run_once(self):
        blocked = operation_blocked_result("review-once")
        if blocked is not None:
            return blocked
        with session_scope() as session:
            repo = DecisionRepository(session)
            pending_drafts = (
                repo.list_drafts_by_status("created")
                + repo.list_drafts_by_status("queued")
                + repo.list_drafts_by_status("approved")
            )
            eligible = []
            for draft in pending_drafts:
                if draft.status == "approved":
                    eligible.append((draft.id, draft.decision.classification.thread.subreddit))
                    continue
                evaluation = draft.evaluation_json or {}
                if not draft.autopost_eligible:
                    continue
                if evaluation.get("overall_score", 0) < 0.70:
                    continue
                if evaluation.get("authenticity_score", 0) < 0.80:
                    continue
                if evaluation.get("specificity_score", 0) < 0.65:
                    continue
                if evaluation.get("promo_pressure_score", 1) > 0.25:
                    continue
                if evaluation.get("policy_compliance_score", 0) < 0.85:
                    continue
                eligible.append((draft.id, draft.decision.classification.thread.subreddit))
        posted = []
        skipped_count = 0
        for draft_id, subreddit in eligible:
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
