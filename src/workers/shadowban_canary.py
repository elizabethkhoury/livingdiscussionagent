"""Shadowban / mod-removal detection.

Every cycle:
  1. Fetch the bot account's public profile JSON with no auth. If the response
     has no recent comments (or 404s), Reddit has shadowbanned the account —
     our future comments won't appear to anyone. Halt the loop.

  2. For each of our last 7 days of posted comments, fetch the comment via
     the public JSON endpoint with no cookies. If the body comes back as
     '[removed]' or the comment is missing, a mod removed it. If we hit >50%
     mod-removal rate across recent comments, the subreddits aren't accepting
     us — halt before we burn more reputation.

Detection is silent on Reddit's side (no rate-limit penalty for these reads).
We use the same JSON endpoints any logged-out reader hits.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta
from urllib import error, request

from sqlalchemy import desc

from src.app.settings import get_settings
from src.runtime.halt_guard import get_active_halt
from src.storage import schema
from src.storage.db import session_scope
from src.storage.repositories import AccountHealthRepository, LearningRepository

logger = logging.getLogger(__name__)

# Public-viewer User-Agent. Deliberately NOT the same as the posting transport's UA.
# We're simulating a logged-out reader fetching a comment.
PUBLIC_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 Safari/605.1.15"

LOOKBACK_DAYS = 7
REMOVED_RATIO_HALT_THRESHOLD = 0.5  # >50% recent comments removed -> halt
MIN_COMMENTS_FOR_REMOVAL_HALT = 4   # don't halt on a 1-of-2 sample


class ShadowbanCanary:
    def __init__(self):
        self.settings = get_settings()

    def run_once(self) -> dict:
        if get_active_halt() is not None:
            return {"status": "already_halted"}

        username = self.settings.reddit_username
        if not username:
            return {"status": "no_username_configured"}

        profile_visible = self._check_profile_visible(username)
        comment_results = self._check_recent_comments(username)

        removed = sum(1 for r in comment_results if r["state"] in {"removed", "missing"})
        total = len(comment_results)
        removed_ratio = (removed / total) if total else 0.0

        observed = {
            "profile_visible": profile_visible,
            "comments_checked": total,
            "comments_removed": removed,
            "removed_ratio": round(removed_ratio, 3),
            "samples": comment_results[:5],
        }
        thresholds = {
            "removed_ratio_halt_threshold": REMOVED_RATIO_HALT_THRESHOLD,
            "min_comments_for_removal_halt": MIN_COMMENTS_FOR_REMOVAL_HALT,
        }

        # Log every run so we have history.
        with session_scope() as session:
            LearningRepository(session).log_event("shadowban_canary", observed)

        # Halt condition 1: profile gone (full shadowban)
        if not profile_visible:
            self._fire_halt("shadowban_profile_invisible",
                            f"Public profile for /u/{username} is not visible from a logged-out viewpoint",
                            thresholds, observed)
            return {"status": "halt_fired", "reason": "profile_invisible", **observed}

        # Halt condition 2: too many recent comments mod-removed
        if total >= MIN_COMMENTS_FOR_REMOVAL_HALT and removed_ratio >= REMOVED_RATIO_HALT_THRESHOLD:
            self._fire_halt("shadowban_high_removal_ratio",
                            f"{removed} of {total} recent comments removed ({removed_ratio:.0%})",
                            thresholds, observed)
            return {"status": "halt_fired", "reason": "high_removal_ratio", **observed}

        return {"status": "ok", **observed}

    # --- Detection internals -------------------------------------------------

    def _check_profile_visible(self, username: str) -> bool:
        """Returns True if /u/<username>.json is reachable AND shows recent activity."""
        url = f"https://www.reddit.com/user/{username}.json?limit=5"
        try:
            data = self._fetch_json(url)
        except error.HTTPError as exc:
            # 404 = profile invisible (classic shadowban signal). 403 = suspended.
            if exc.code in (403, 404):
                logger.warning("profile_invisible username=%s http=%s", username, exc.code)
                return False
            logger.warning("profile_fetch_unexpected_error username=%s http=%s", username, exc.code)
            return True  # Don't halt on transient 5xx
        except Exception as exc:
            logger.warning("profile_fetch_network_error username=%s err=%s", username, exc)
            return True  # Don't halt on transient network errors

        # Profile fetched. Now check it actually has recent content.
        try:
            children = data.get("data", {}).get("children", [])
        except AttributeError:
            return False
        return len(children) > 0

    def _check_recent_comments(self, username: str) -> list[dict]:
        """For each posted comment in lookback window, check public visibility."""
        cutoff = datetime.utcnow() - timedelta(days=LOOKBACK_DAYS)
        results: list[dict] = []
        with session_scope() as session:
            attempts = session.query(schema.PostAttemptRecord).filter(
                schema.PostAttemptRecord.status == "posted",
                schema.PostAttemptRecord.posted_at.is_not(None),
                schema.PostAttemptRecord.posted_at >= cutoff,
                schema.PostAttemptRecord.posted_comment_id.like("t1_%"),
            ).order_by(desc(schema.PostAttemptRecord.id)).limit(20).all()

            for a in attempts:
                draft = session.get(schema.DraftRecord, a.draft_id)
                if not draft:
                    continue
                decision = session.get(schema.DecisionRecord, draft.decision_id)
                classification = session.get(schema.ClassificationRecord, decision.classification_id)
                thread = session.get(schema.ThreadRecord, classification.thread_id)
                cid = a.posted_comment_id.replace("t1_", "")
                results.append({
                    "attempt_id": a.id,
                    "subreddit": thread.subreddit,
                    "thread_id": thread.platform_thread_id,
                    "comment_id": cid,
                    "state": "pending",
                })

        # Fetch each from logged-out viewpoint. Space requests to avoid rate-limiting.
        for r in results:
            r["state"] = self._fetch_comment_state(r["subreddit"], r["thread_id"], r["comment_id"])
            time.sleep(2.0)
        return results

    def _fetch_comment_state(self, subreddit: str, thread_id: str, comment_id: str) -> str:
        """Returns: 'visible', 'removed', 'missing', 'unknown'."""
        url = f"https://www.reddit.com/r/{subreddit}/comments/{thread_id}/comment/{comment_id}.json"
        try:
            data = self._fetch_json(url)
        except error.HTTPError as exc:
            if exc.code == 404:
                return "missing"
            return "unknown"  # 5xx / 429 — don't count against us
        except Exception:
            return "unknown"
        try:
            children = data[1]["data"]["children"]
            if not children:
                return "missing"
            body = (children[0].get("data", {}).get("body") or "").strip()
        except (KeyError, IndexError, AttributeError, TypeError):
            return "unknown"
        if body in {"[removed]", "[deleted]", "[ Removed by Reddit ]", "[ Removed by Reddit in response to a copyright notice. ]"}:
            return "removed"
        if not body:
            return "missing"
        return "visible"

    def _fetch_json(self, url: str):
        req = request.Request(url, headers={"User-Agent": PUBLIC_UA})
        with request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _fire_halt(self, reason_code: str, reason: str, thresholds: dict, observed: dict):
        with session_scope() as session:
            AccountHealthRepository(session).create_halt(
                reason_code=reason_code,
                reason=reason,
                snapshot_id=None,
                thresholds=thresholds,
                observed=observed,
            )
        logger.error("HALT FIRED reason=%s detail=%s", reason_code, reason)
