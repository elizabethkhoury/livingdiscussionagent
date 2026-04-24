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
        self.headers = {"User-Agent": "PromptHuntResearchBot/0.1"}
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

    def fetch_posts(self, subreddit: str, limit: int = 25):
        url = f"https://www.reddit.com/r/{subreddit}/new.json?limit={limit}"
        try:
            data = self._fetch_json(url)
        except (TimeoutError, error.URLError) as exc:
            status_code = exc.code if isinstance(exc, error.HTTPError) else None
            if status_code == 429:
                self.rate_limited = True
            self.logger.warning(
                "Skipping subreddit fetch after request failure subreddit=%s status_code=%s url=%s error=%s",
                subreddit,
                status_code,
                url,
                exc,
                extra={"subreddit": subreddit, "status_code": status_code, "url": url, "error": str(exc)},
            )
            return []
        candidates = []
        for child in data["data"]["children"]:
            post = child["data"]
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
                    age_hours=age_hours,
                    created_at_platform=created,
                )
            )
        return candidates

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
