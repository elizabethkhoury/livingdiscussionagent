from __future__ import annotations

from src.app.config import get_default_thresholds
from src.execute.poster import PostingService
from src.storage.db import session_scope
from src.storage.repositories import DecisionRepository


class ReviewWorker:
    def __init__(self):
        self.poster = PostingService()
        self.thresholds = get_default_thresholds()

    async def run_once(self):
        with session_scope() as session:
            repo = DecisionRepository(session)
            pending_drafts = repo.list_drafts_by_status("created") + repo.list_drafts_by_status("approved")
            eligible = []
            for draft in pending_drafts:
                if draft.status == "approved":
                    eligible.append((draft.id, draft.decision.classification.thread.subreddit))
                    continue
                evaluation = draft.evaluation_json or {}
                if draft.status == "created" and not draft.autopost_eligible:
                    continue
                if evaluation.get("overall_score", 0) < self.thresholds.autopost_overall_threshold:
                    continue
                if evaluation.get("authenticity_score", 0) < 0.85:
                    continue
                if evaluation.get("specificity_score", 0) < 0.75:
                    continue
                if evaluation.get("promo_pressure_score", 1) > 0.2:
                    continue
                if evaluation.get("policy_compliance_score", 0) < 0.90:
                    continue
                eligible.append((draft.id, draft.decision.classification.thread.subreddit))
        posted = []
        for draft_id, subreddit in eligible:
            attempt = await self.poster.publish_draft(draft_id, subreddit)
            if attempt is not None:
                posted.append(attempt)
        return posted
