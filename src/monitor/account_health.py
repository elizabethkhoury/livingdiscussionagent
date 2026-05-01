from __future__ import annotations

import json
from datetime import date
from urllib import error, request
from urllib.parse import quote

from src.app.settings import get_settings
from src.domain.models import AccountHealthEvaluation, AccountHealthSnapshot, AccountHealthThresholds
from src.monitor.engagement_fetcher import RedditEngagementFetcher
from src.storage.db import session_scope
from src.storage.repositories import AccountHealthRepository


class RedditAccountHealthFetcher:
    def __init__(self):
        self.headers = {"User-Agent": "PromptHuntResearchBot/0.1"}

    def fetch(self, username: str, snapshot_date: date):
        user = quote(username, safe="")
        req = request.Request(f"https://www.reddit.com/user/{user}/about.json", headers=self.headers)
        with request.urlopen(req, timeout=30) as response:
            raw = json.loads(response.read().decode("utf-8"))
        data = raw.get("data", {})
        link_karma = int(data.get("link_karma", 0))
        comment_karma = int(data.get("comment_karma", 0))
        return AccountHealthSnapshot(
            username=username,
            snapshot_date=snapshot_date,
            link_karma=link_karma,
            comment_karma=comment_karma,
            total_karma=link_karma + comment_karma,
            source_payload_json=data,
        )


class AccountHealthService:
    def __init__(self, fetcher=None, engagement_fetcher=None, today_provider=None):
        self.settings = get_settings()
        self.fetcher = fetcher or RedditAccountHealthFetcher()
        self.engagement_fetcher = engagement_fetcher or RedditEngagementFetcher()
        self.today_provider = today_provider or date.today

    def run_once(self):
        if not self.settings.account_health_enabled:
            return {"status": "disabled", "reason": "account_health_disabled"}
        username = self.settings.reddit_username
        if not username:
            self._log_event("account_health_missing_username", {"reason": "reddit_username_not_configured"})
            return {"status": "skipped", "reason": "reddit_username_not_configured"}

        snapshot_date = self.today_provider()
        try:
            snapshot = self.fetcher.fetch(username, snapshot_date)
        except (TimeoutError, error.URLError, ValueError, KeyError, TypeError) as exc:
            self._log_event("account_health_fetch_failed", {"username": username, "error": str(exc), "error_type": type(exc).__name__})
            return {"status": "failed", "reason": "account_health_fetch_failed", "error": str(exc)}

        attempt_ids = self._refresh_recent_post_snapshots()
        with session_scope() as session:
            repo = AccountHealthRepository(session)
            prior = repo.latest_snapshot_before(username, snapshot_date)
            snapshot = self._with_deltas(snapshot, prior, self._tracked_post_score_total(repo, attempt_ids))
            record = repo.upsert_daily_snapshot(snapshot)
            evaluation = self._evaluate(snapshot, self._thresholds())
            repo.log_event(
                "account_health_snapshot_recorded",
                {
                    "username": username,
                    "snapshot_id": record.id,
                    "snapshot_date": snapshot.snapshot_date.isoformat(),
                    "thresholds": evaluation.thresholds,
                    "observed": evaluation.observed,
                    "reason_codes": evaluation.reason_codes,
                },
            )
            active_halt = repo.latest_active_halt()
            halt = None
            status = "healthy" if evaluation.healthy else "unhealthy"
            if not evaluation.healthy:
                if active_halt is None:
                    halt = repo.create_halt(
                        reason_code=evaluation.reason_codes[0],
                        reason=evaluation.reason,
                        snapshot_id=record.id,
                        thresholds=evaluation.thresholds,
                        observed=evaluation.observed,
                    )
                    repo.log_event(
                        "agent_halted",
                        {
                            "username": username,
                            "halt_id": halt.id,
                            "snapshot_id": record.id,
                            "reason": evaluation.reason,
                            "reason_codes": evaluation.reason_codes,
                            "thresholds": evaluation.thresholds,
                            "observed": evaluation.observed,
                        },
                    )
                    status = "halted"
                else:
                    halt = active_halt
                    status = "already_halted"
            return {
                "status": status,
                "snapshot_id": record.id,
                "halt_id": halt.id if halt else None,
                "evaluation": evaluation.model_dump(),
            }

    def _refresh_recent_post_snapshots(self):
        with session_scope() as session:
            attempts = AccountHealthRepository(session).recent_posted_attempts_for_health(self.settings.account_health_post_lookback_days)
            attempt_ids = [attempt.id for attempt in attempts]
        for attempt_id in attempt_ids:
            self.engagement_fetcher.refresh(attempt_id)
        return attempt_ids

    def _tracked_post_score_total(self, repo: AccountHealthRepository, attempt_ids: list[int]):
        total = 0
        for attempt_id in attempt_ids:
            snapshot = repo.latest_snapshot_for_attempt(attempt_id)
            if snapshot is not None:
                total += snapshot.score
        return total

    def _with_deltas(self, snapshot: AccountHealthSnapshot, prior, tracked_post_score_total: int):
        snapshot.tracked_post_score_total = tracked_post_score_total
        if prior is None:
            return snapshot
        snapshot.link_karma_delta = snapshot.link_karma - prior.link_karma
        snapshot.comment_karma_delta = snapshot.comment_karma - prior.comment_karma
        snapshot.total_karma_delta = snapshot.total_karma - prior.total_karma
        snapshot.tracked_post_score_delta = snapshot.tracked_post_score_total - prior.tracked_post_score_total
        return snapshot

    def _thresholds(self):
        return AccountHealthThresholds(
            min_total_karma=self.settings.account_health_min_total_karma,
            min_comment_karma=self.settings.account_health_min_comment_karma,
            min_link_karma=self.settings.account_health_min_link_karma,
            max_daily_total_karma_drop=self.settings.account_health_max_daily_total_karma_drop,
            min_daily_tracked_score_delta=self.settings.account_health_min_daily_tracked_score_delta,
        )

    def _evaluate(self, snapshot: AccountHealthSnapshot, thresholds: AccountHealthThresholds):
        reason_codes = []
        if snapshot.total_karma < thresholds.min_total_karma:
            reason_codes.append("total_karma_below_minimum")
        if snapshot.comment_karma < thresholds.min_comment_karma:
            reason_codes.append("comment_karma_below_minimum")
        if snapshot.link_karma < thresholds.min_link_karma:
            reason_codes.append("link_karma_below_minimum")
        if snapshot.total_karma_delta is not None and snapshot.total_karma_delta < -thresholds.max_daily_total_karma_drop:
            reason_codes.append("daily_total_karma_drop_exceeded")
        if snapshot.tracked_post_score_delta is not None and snapshot.tracked_post_score_delta < thresholds.min_daily_tracked_score_delta:
            reason_codes.append("daily_tracked_post_score_delta_below_minimum")
        observed = {
            "total_karma": snapshot.total_karma,
            "comment_karma": snapshot.comment_karma,
            "link_karma": snapshot.link_karma,
            "total_karma_delta": snapshot.total_karma_delta,
            "tracked_post_score_total": snapshot.tracked_post_score_total,
            "tracked_post_score_delta": snapshot.tracked_post_score_delta,
        }
        threshold_values = thresholds.model_dump()
        reason = "account health is within configured thresholds"
        if reason_codes:
            reason = f"account health breached configured thresholds: {', '.join(reason_codes)}"
        return AccountHealthEvaluation(
            healthy=not reason_codes,
            reason_codes=reason_codes,
            reason=reason,
            thresholds=threshold_values,
            observed=observed,
        )

    def _log_event(self, event_type: str, payload: dict):
        with session_scope() as session:
            AccountHealthRepository(session).log_event(event_type, payload)
