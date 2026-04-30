from __future__ import annotations

import json
from typing import TypedDict
from urllib import request

from src.domain.models import EngagementSnapshot
from src.storage.db import session_scope
from src.storage.repositories import DecisionRepository


class _EngagementPayload(TypedDict):
    score: int
    reply_count: int
    is_deleted: bool
    is_removed: bool
    is_locked: bool


class RedditEngagementFetcher:
    def refresh(self, post_attempt_id: int):
        with session_scope() as session:
            attempts = DecisionRepository(session)
            attempt = next((item for item in attempts.get_attempts() if item.id == post_attempt_id), None)
            if attempt is None or attempt.posted_comment_id is None:
                return EngagementSnapshot(
                    post_attempt_id=post_attempt_id,
                    score=0,
                    reply_count=0,
                    is_deleted=False,
                    is_removed=False,
                    is_locked=False,
                )
            payload: _EngagementPayload = {"score": 1, "reply_count": 0, "is_deleted": False, "is_removed": False, "is_locked": False}
            try:
                req = request.Request(
                    f"https://www.reddit.com/comments/{attempt.posted_comment_id}.json",
                    headers={"User-Agent": "PromptHuntResearchBot/0.1"},
                )
                with request.urlopen(req, timeout=30) as response:
                    raw = json.loads(response.read().decode("utf-8"))
                if raw and raw[0]["data"]["children"]:
                    item = raw[0]["data"]["children"][0]["data"]
                    payload = {
                        "score": item.get("score", 0),
                        "reply_count": item.get("num_comments", 0),
                        "is_deleted": item.get("removed_by_category") == "deleted",
                        "is_removed": item.get("removed_by_category") is not None,
                        "is_locked": item.get("locked", False),
                    }
            except Exception:
                pass
            snapshot = EngagementSnapshot(post_attempt_id=post_attempt_id, **payload)
            attempts.record_snapshot(snapshot)
            return snapshot
