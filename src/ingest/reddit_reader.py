from __future__ import annotations

import json
from datetime import UTC, datetime
from urllib import request

from src.domain.models import RedditCommentCandidate, RedditPostCandidate, ThreadContext


class RedditJSONReader:
    def __init__(self):
        self.headers = {"User-Agent": "PromptHuntResearchBot/0.1"}

    def _fetch_json(self, url: str):
        req = request.Request(url, headers=self.headers)
        with request.urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))

    def fetch_posts(self, subreddit: str, limit: int = 25):
        url = f"https://www.reddit.com/r/{subreddit}/new.json?limit={limit}"
        data = self._fetch_json(url)
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
        payload = self._fetch_json(f"{post.url.rstrip('/')}.json?limit={comment_limit}")
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

