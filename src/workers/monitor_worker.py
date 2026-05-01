from __future__ import annotations

from src.learn.feature_builder import build_learning_features
from src.monitor.account_health import AccountHealthService
from src.monitor.engagement_fetcher import RedditEngagementFetcher
from src.monitor.moderation_signals import classify_negative_signal
from src.runtime.halt_guard import operation_blocked_result
from src.storage.db import session_scope
from src.storage.repositories import DecisionRepository, LearningRepository


class MonitorWorker:
    def __init__(self):
        self.fetcher = RedditEngagementFetcher()
        self.account_health = AccountHealthService()

    def run_once(self):
        blocked = operation_blocked_result("monitor-once")
        if blocked is not None:
            return blocked
        account_health_result = self.account_health.run_once()
        if account_health_result.get("status") in {"halted", "already_halted"}:
            return {"account_health": account_health_result, "snapshots": []}
        snapshots = []
        with session_scope() as session:
            repo = DecisionRepository(session)
            attempts = repo.get_attempts()
        for attempt in attempts:
            snapshot = self.fetcher.refresh(attempt.id)
            snapshots.append(snapshot)
            signal = classify_negative_signal(snapshot)
            with session_scope() as session:
                decisions = DecisionRepository(session)
                learning = LearningRepository(session)
                draft = decisions.get_draft(attempt.draft_id)
                if draft is None:
                    continue
                classification = draft.decision.classification
                reward = self._reward(snapshot)
                learning.add_learning_example(
                    thread_id=classification.thread_id,
                    draft_id=draft.id,
                    features=build_learning_features(classification, draft),
                    outcome_label=signal,
                    reward_score=reward,
                )
        return snapshots

    def _reward(self, snapshot):
        normalized_upvotes = min(max(snapshot.score, 0), 10) / 10
        normalized_reply_depth = min(snapshot.reply_count, 5) / 5
        survived_48h = 1.0 if not snapshot.is_removed and not snapshot.is_deleted else 0.0
        positive_followup_signal = 1.0 if snapshot.reply_count > 0 and snapshot.score > 0 else 0.0
        removal_flag = 1.0 if snapshot.is_removed else 0.0
        deletion_flag = 1.0 if snapshot.is_deleted else 0.0
        negative = 1.0 if snapshot.score < 0 else 0.0
        return round(
            (0.35 * normalized_upvotes)
            + (0.25 * normalized_reply_depth)
            + (0.20 * survived_48h)
            + (0.20 * positive_followup_signal)
            - (0.60 * removal_flag)
            - (0.50 * deletion_flag)
            - (0.40 * negative),
            3,
        )
