from __future__ import annotations

import json
import logging
import time
from datetime import UTC, datetime
from urllib import error, request
from urllib.parse import quote, urlsplit, urlunsplit

from src.domain.models import RedditCommentCandidate, RedditPostCandidate, ThreadContext


class RedditJSONReader:
    def __init__(self, request_delay_seconds: float = 0.0):
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
        }
        self.logger = logging.getLogger(__name__)
        self.request_delay_seconds = request_delay_seconds
        self.rate_limited = False
        self._last_request_at: float | None = None

    def _fetch_json(self, url: str):
        req = request.Request(self._http_safe_url(url), headers=self.headers)
        self._pace_requests()
        with request.urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))

    def _pace_requests(self):
        if self.request_delay_seconds <= 0:
            return
        now = time.monotonic()
        if self._last_request_at is not None:
            remaining = self.request_delay_seconds - (now - self._last_request_at)
            if remaining > 0:
                time.sleep(remaining)
                now = time.monotonic()
        self._last_request_at = now

    def _http_safe_url(self, url: str):
        parts = urlsplit(url)
        netloc = parts.netloc.encode("idna").decode("ascii")
        path = quote(parts.path, safe="/%")
        query = quote(parts.query, safe="=&%:+,/")
        return urlunsplit((parts.scheme, netloc, path, query, parts.fragment))

    def fetch_posts(self, subreddit: str, limit: int = 25, sort: str = "hot", time_filter: str = "day"):
        """Fetch posts from a subreddit, filtering out moderation/locked/removed/stickied.

        sort: 'hot' (default — Reddit's algorithm of upvotes×recency), 'top', 'new', 'rising'.
        time_filter: only used when sort='top'. 'hour', 'day', 'week', 'month', 'year', 'all'.
        """
        sort = sort if sort in {"hot", "top", "new", "rising"} else "hot"
        if sort == "top":
            url = f"https://www.reddit.com/r/{subreddit}/top.json?limit={limit}&t={time_filter}"
        else:
            url = f"https://www.reddit.com/r/{subreddit}/{sort}.json?limit={limit}"
        try:
            data = self._fetch_json(url)
        except (TimeoutError, error.URLError) as exc:
            status_code = exc.code if isinstance(exc, error.HTTPError) else None
            if status_code == 429:
                self.rate_limited = True
            self.logger.warning(
                "Skipping subreddit fetch subreddit=%s sort=%s status_code=%s url=%s error=%s",
                subreddit,
                sort,
                status_code,
                url,
                exc,
            )
            return []
        candidates = []
        for child in data["data"]["children"]:
            post = child["data"]
            if post.get("stickied") or post.get("locked") or post.get("archived"):
                continue
            if post.get("removed_by_category") or post.get("removed_by"):
                continue
            if post.get("over_18"):
                continue
            if not post.get("is_self", False) and not post.get("selftext"):
                # Skip pure link/image/video posts unless they have meaningful body text.
                # We can only generate good replies for self-text discussions.
                if post.get("post_hint") in {"image", "hosted:video", "rich:video", "link"}:
                    continue
            created = datetime.fromtimestamp(post["created_utc"], tz=UTC).replace(tzinfo=None)
            age_hours = (datetime.utcnow() - created).total_seconds() / 3600
            candidates.append(
                RedditPostCandidate(
                    platform_thread_id=post["id"],
                    subreddit=subreddit,
                    title=post["title"],
                    body=post.get("selftext", ""),
                    url=f"https://www.reddit.com{post['permalink']}",
                    author=post.get("author", ""),
                    num_comments=post.get("num_comments", 0),
                    score=int(post.get("score", 0) or 0),
                    upvote_ratio=float(post.get("upvote_ratio", 0.0) or 0.0),
                    age_hours=age_hours,
                    created_at_platform=created,
                )
            )
        return candidates

    def fetch_quality_candidates(self, subreddit: str, target_count: int = 4) -> list[RedditPostCandidate]:
        """Fetch the highest-engagement posts from a subreddit.

        Pulls from 'hot' (current engagement) AND 'top day' (best in 24h), dedupes,
        filters by quality thresholds, ranks by composite quality score, returns top N.
        """
        seen: dict[str, RedditPostCandidate] = {}
        for sort, time_filter in (("hot", "day"), ("top", "day")):
            for post in self.fetch_posts(subreddit, limit=25, sort=sort, time_filter=time_filter):
                seen.setdefault(post.platform_thread_id, post)
            if self.rate_limited:
                break

        def passes_quality(post: RedditPostCandidate) -> bool:
            if post.age_hours < 0.5:
                return False  # Too new — barely any engagement signal yet.
            if post.age_hours > 36:
                return False  # Stale — engagement window mostly closed.
            if post.score < 5:
                return False  # Not gaining traction.
            if post.num_comments < 3:
                return False  # No discussion to join.
            if post.upvote_ratio and post.upvote_ratio < 0.7:
                return False  # Controversial / poorly received.
            return True

        filtered = [p for p in seen.values() if passes_quality(p)]
        filtered.sort(key=quality_score, reverse=True)
        return filtered[:target_count]

    def fetch_thread_context(self, post: RedditPostCandidate, comment_limit: int = 10):
        subreddit = quote(post.subreddit, safe="")
        thread_id = quote(post.platform_thread_id, safe="")
        url = f"https://www.reddit.com/r/{subreddit}/comments/{thread_id}.json?limit={comment_limit}"
        try:
            payload = self._fetch_json(url)
        except (TimeoutError, error.URLError) as exc:
            status_code = exc.code if isinstance(exc, error.HTTPError) else None
            if status_code == 429:
                self.rate_limited = True
            self.logger.warning(
                "Skipping thread context fetch after request failure thread_id=%s status_code=%s url=%s error=%s",
                post.platform_thread_id,
                status_code,
                url,
                exc,
                extra={"thread_id": post.platform_thread_id, "status_code": status_code, "url": url, "error": str(exc)},
            )
            return ThreadContext(post=post, comments=[])
        comments = []
        for child in payload[1]["data"]["children"]:
            if child["kind"] != "t1":
                continue
            data = child["data"]
            body = data.get("body", "")
            if not body or len(body) < 20:
                continue
            created_utc = data.get("created_utc")
            created = None
            if created_utc:
                created = datetime.fromtimestamp(created_utc, tz=UTC).replace(tzinfo=None)
            comments.append(
                RedditCommentCandidate(
                    platform_comment_id=data["id"],
                    author=data.get("author", ""),
                    body=body,
                    created_at_platform=created,
                )
            )
        return ThreadContext(post=post, comments=comments)

    def fetch_comment_replies(self, subreddit: str, thread_id: str, comment_id: str) -> list[dict]:
        """Fetch direct replies to a specific comment.

        Returns a list of dicts: {id, author, body, created_at, parent_id}.
        """
        sub = quote(subreddit, safe="")
        tid = quote(thread_id, safe="")
        cid = quote(comment_id, safe="")
        url = f"https://www.reddit.com/r/{sub}/comments/{tid}/comment/{cid}.json"
        try:
            payload = self._fetch_json(url)
        except (TimeoutError, error.URLError) as exc:
            status_code = exc.code if isinstance(exc, error.HTTPError) else None
            if status_code == 429:
                self.rate_limited = True
            self.logger.warning(
                "fetch_comment_replies failed thread_id=%s comment_id=%s status=%s err=%s",
                thread_id,
                comment_id,
                status_code,
                exc,
            )
            return []
        replies: list[dict] = []
        try:
            top_children = payload[1]["data"]["children"]
        except (KeyError, IndexError, TypeError):
            return []
        # Find our target comment
        for child in top_children:
            if child.get("kind") != "t1":
                continue
            data = child.get("data", {})
            if data.get("id") != comment_id:
                continue
            reply_listing = data.get("replies")
            if not isinstance(reply_listing, dict):
                continue
            for r in reply_listing.get("data", {}).get("children", []):
                if r.get("kind") != "t1":
                    continue
                rd = r.get("data", {})
                created_utc = rd.get("created_utc")
                created = None
                if created_utc:
                    created = datetime.fromtimestamp(created_utc, tz=UTC).replace(tzinfo=None)
                replies.append(
                    {
                        "id": rd.get("id"),
                        "author": rd.get("author") or "",
                        "body": rd.get("body") or "",
                        "created_at": created,
                        "parent_id": rd.get("parent_id") or "",
                    }
                )
        return replies


def quality_score(post: RedditPostCandidate) -> float:
    """Composite ranking score. Higher = better candidate to engage with.

    Upvotes are the strongest signal; comments are second; freshness third.
    Penalize posts > 24h since engagement is decaying.
    """
    age_penalty = max(0.0, post.age_hours - 24) * 0.5
    return (
        post.score * 1.0
        + post.num_comments * 2.0
        + max(0.0, 1.0 - post.age_hours / 24.0) * 10.0  # bonus for posts < 24h old
        - age_penalty
    )
