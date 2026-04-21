from __future__ import annotations

from urllib import error

import pytest

from src.domain.models import RedditPostCandidate
from src.ingest.reddit_reader import RedditJSONReader


def test_fetch_posts_returns_empty_list_on_http_error(monkeypatch: pytest.MonkeyPatch):
    reader = RedditJSONReader()

    def fake_fetch_json(_url: str):
        raise error.HTTPError("https://www.reddit.com/r/missing/new.json?limit=25", 404, "Not Found", hdrs=None, fp=None)

    monkeypatch.setattr(reader, "_fetch_json", fake_fetch_json)

    assert reader.fetch_posts("missing") == []


def test_fetch_thread_context_returns_empty_comments_on_timeout(monkeypatch: pytest.MonkeyPatch):
    reader = RedditJSONReader()

    def fake_fetch_json(_url: str):
        raise TimeoutError("timed out")

    monkeypatch.setattr(reader, "_fetch_json", fake_fetch_json)

    candidate = RedditPostCandidate(
        platform_thread_id="thread-1",
        subreddit="PromptEngineering",
        title="How do I save prompts?",
        body="",
        url="https://www.reddit.com/r/PromptEngineering/comments/thread-1/example/",
    )

    context = reader.fetch_thread_context(candidate)

    assert context.post == candidate
    assert context.comments == []
