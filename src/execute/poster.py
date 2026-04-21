from __future__ import annotations

from datetime import datetime, timedelta

from src.app.settings import get_settings
from src.domain.models import CircuitBreakerState
from src.execute.playwright_transport import PlaywrightPostingTransport
from src.storage.db import session_scope
from src.storage.repositories import DecisionRepository, ThreadRepository


class PostingService:
    def __init__(self):
        self.settings = get_settings()
        self.transport = PlaywrightPostingTransport()

    def can_post(self, subreddit: str):
        with session_scope() as session:
            decisions = DecisionRepository(session)
            threads = ThreadRepository(session)
            if decisions.recent_negative_signals(24) >= self.settings.moderator_removals_circuit_breaker:
                return False, CircuitBreakerState(moderator_removals=decisions.recent_negative_signals(24))
            if decisions.recent_rate_limit_events(12) >= self.settings.rate_limits_circuit_breaker:
                return False, CircuitBreakerState(rate_limits=decisions.recent_rate_limit_events(12))
            if threads.count_posts_since(datetime.utcnow() - timedelta(hours=1)) >= self.settings.max_autoposts_per_hour:
                return False, CircuitBreakerState(failure_events=["hourly_cap"])
            if threads.count_posts_since(datetime.utcnow() - timedelta(days=1)) >= self.settings.max_total_posts_per_day:
                return False, CircuitBreakerState(failure_events=["daily_cap"])
            if threads.count_posts_for_subreddit_since(subreddit, datetime.utcnow() - timedelta(days=1)) >= self.settings.subreddit_daily_cap:
                return False, CircuitBreakerState(failure_events=["subreddit_daily_cap"])
        return True, CircuitBreakerState()

    async def publish_draft(self, draft_id: int, subreddit: str):
        allowed, state = self.can_post(subreddit)
        if not allowed:
            raise RuntimeError(f"Circuit breaker active: {state}")
        return await self.transport.publish(draft_id)
