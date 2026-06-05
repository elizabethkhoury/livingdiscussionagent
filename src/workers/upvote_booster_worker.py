"""Upvote Booster Worker

Watches our posted comments for real human upvotes, then has a second Reddit
account come in a few minutes later and upvote:
  - Our own comment
  - The original post it's in
  - The comment we replied to (if applicable)

This makes activity look natural — real engagement followed by more engagement
a few minutes later, rather than an instant vote spike right when we post.

How it works:
  1. Fetch the current public score of each of our recent comments via Reddit's
     logged-out JSON API (same approach as the shadowban canary).
  2. If a comment's score >= BOOSTER_MIN_SCORE (default 2, meaning at least one
     real human upvoted beyond our own auto-upvote) AND it was posted at least
     BOOSTER_DELAY_MINUTES ago, it's a boost candidate.
  3. Skip anything we've already boosted (tracked in data/boosted_comments.json).
  4. For each candidate: open a Playwright session as the booster account and
     upvote the comment, post, and target comment.

Requires REDDIT_BOOSTER_USERNAME + REDDIT_BOOSTER_PASSWORD in .env.
If those aren't set, this worker silently returns a skip result every cycle.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib import error as urllib_error
from urllib import request as urllib_request

from sqlalchemy import select

from src.app.settings import get_settings
from src.execute.booster_transport import BoosterTransport
from src.runtime.halt_guard import operation_blocked_result
from src.storage import schema
from src.storage.db import session_scope
from src.storage.repositories import LearningRepository

logger = logging.getLogger(__name__)

LOOKBACK_DAYS = 7
BOOSTED_LOG_PATH = Path("data/boosted_comments.json")

# Public-viewer UA — logged-out score checks
_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 Safari/605.1.15"


class UpvoteBoosterWorker:
    def __init__(self):
        self.settings = get_settings()
        self.transport = BoosterTransport()
        BOOSTED_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

    async def run_once(self) -> dict:
        blocked = operation_blocked_result("upvote-booster-once")
        if blocked is not None:
            return blocked

        if not self.transport.is_configured():
            return {"status": "skipped", "reason": "booster account not configured"}

        candidates = self._find_boost_candidates()
        if not candidates:
            return {"status": "ok", "boosted": 0, "reason": "no eligible comments"}

        boosted = []
        skipped = []

        for c in candidates:
            try:
                result = await self._boost(c)
                boosted.append(result)
                self._mark_boosted(c["comment_id"])
                # Small pause between boosts so it doesn't look like a flood
                time.sleep(3)
            except Exception as exc:
                logger.warning("boost failed comment=%s err=%s", c["comment_id"], exc)
                skipped.append({"comment_id": c["comment_id"], "error": str(exc)})

        # Log the run
        with session_scope() as session:
            LearningRepository(session).log_event("upvote_booster", {
                "boosted_count": len(boosted),
                "skipped_count": len(skipped),
                "details": boosted,
            })

        return {"status": "ok", "boosted": len(boosted), "skipped": len(skipped), "details": boosted}

    # ------------------------------------------------------------------
    # Finding candidates
    # ------------------------------------------------------------------

    def _find_boost_candidates(self) -> list[dict]:
        """Return comments that have real human engagement and haven't been boosted yet."""
        cutoff = datetime.utcnow() - timedelta(days=LOOKBACK_DAYS)
        # Only consider comments old enough that the delay has passed
        delay_cutoff = datetime.utcnow() - timedelta(minutes=self.settings.booster_delay_minutes)
        already_boosted = self._load_boosted_ids()

        candidates = []
        with session_scope() as session:
            stmt = select(schema.PostAttemptRecord).where(
                schema.PostAttemptRecord.status == "posted",
                schema.PostAttemptRecord.posted_at.is_not(None),
                schema.PostAttemptRecord.posted_at >= cutoff,
                schema.PostAttemptRecord.posted_at <= delay_cutoff,
                schema.PostAttemptRecord.posted_comment_id.like("t1_%"),
            )
            attempts = list(session.scalars(stmt).all())

            for attempt in attempts:
                comment_id = attempt.posted_comment_id.replace("t1_", "")
                if comment_id in already_boosted:
                    continue

                draft = session.get(schema.DraftRecord, attempt.draft_id)
                if draft is None:
                    continue
                decision = session.get(schema.DecisionRecord, draft.decision_id)
                classification = session.get(schema.ClassificationRecord, decision.classification_id)
                thread = session.get(schema.ThreadRecord, classification.thread_id)

                # Get the target comment we replied to (if any)
                target_comment_fullname = None
                if classification.target_comment_id:
                    target_comment = session.get(schema.ThreadCommentRecord, classification.target_comment_id)
                    if target_comment and target_comment.platform_comment_id:
                        cid = target_comment.platform_comment_id
                        target_comment_fullname = cid if cid.startswith("t1_") else f"t1_{cid}"

                candidates.append({
                    "comment_id": comment_id,
                    "comment_fullname": f"t1_{comment_id}",
                    "thread_id": thread.platform_thread_id,
                    "thread_fullname": f"t3_{thread.platform_thread_id}",
                    "subreddit": thread.subreddit,
                    "thread_url": thread.url,
                    "target_comment_fullname": target_comment_fullname,
                })

        # Check live scores — only boost ones with real engagement
        eligible = []
        for c in candidates:
            score = self._fetch_comment_score(c["subreddit"], c["thread_id"], c["comment_id"])
            if score is None:
                continue  # couldn't fetch — skip
            if score >= self.settings.booster_min_score:
                c["current_score"] = score
                eligible.append(c)
                logger.info(
                    "boost_candidate comment=%s score=%d subreddit=%s",
                    c["comment_id"], score, c["subreddit"],
                )
            # Polite delay between public score checks
            time.sleep(2)

        return eligible

    def _fetch_comment_score(self, subreddit: str, thread_id: str, comment_id: str) -> int | None:
        """Fetch the current public score of a comment. Returns None on error."""
        url = f"https://www.reddit.com/r/{subreddit}/comments/{thread_id}/comment/{comment_id}.json"
        req = urllib_request.Request(url, headers={"User-Agent": _UA})
        try:
            with urllib_request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            children = data[1]["data"]["children"]
            if not children:
                return None
            return int(children[0]["data"].get("score", 0))
        except (urllib_error.HTTPError, urllib_error.URLError, KeyError, IndexError, ValueError) as exc:
            logger.debug("fetch_comment_score error %s: %s", comment_id, exc)
            return None

    # ------------------------------------------------------------------
    # Boosting
    # ------------------------------------------------------------------

    async def _boost(self, candidate: dict) -> dict:
        """Use the booster account to upvote the comment, post, and target comment."""
        thread_url = candidate["thread_url"]
        fullnames_to_upvote = [
            candidate["comment_fullname"],      # our comment
            candidate["thread_fullname"],        # the original post
        ]
        if candidate.get("target_comment_fullname"):
            fullnames_to_upvote.append(candidate["target_comment_fullname"])  # person we replied to

        # De-duplicate (in case thread fullname == something else somehow)
        fullnames_to_upvote = list(dict.fromkeys(fullnames_to_upvote))

        logger.info(
            "boosting comment=%s upvoting=%s",
            candidate["comment_id"], fullnames_to_upvote,
        )
        results = await self.transport.upvote_items(thread_url, fullnames_to_upvote)
        return {
            "comment_id": candidate["comment_id"],
            "score_before_boost": candidate.get("current_score"),
            "upvotes": results,
        }

    # ------------------------------------------------------------------
    # Tracking boosted comments
    # ------------------------------------------------------------------

    def _load_boosted_ids(self) -> set[str]:
        if not BOOSTED_LOG_PATH.exists():
            return set()
        try:
            data = json.loads(BOOSTED_LOG_PATH.read_text(encoding="utf-8"))
            return set(data.get("comment_ids", []))
        except Exception:
            return set()

    def _mark_boosted(self, comment_id: str) -> None:
        existing = self._load_boosted_ids()
        existing.add(comment_id)
        # Keep the log from growing forever — only keep last 500 IDs
        ids = list(existing)[-500:]
        BOOSTED_LOG_PATH.write_text(
            json.dumps({"comment_ids": ids}, indent=2),
            encoding="utf-8",
        )
