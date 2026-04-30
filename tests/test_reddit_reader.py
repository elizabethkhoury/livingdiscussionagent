from __future__ import annotations

from email.message import Message
from urllib import error

import pytest

from src.domain.models import RedditPostCandidate
from src.ingest.reddit_reader import RedditJSONReader


def test_fetch_posts_returns_empty_list_on_http_error(monkeypatch: pytest.MonkeyPatch):
    reader = RedditJSONReader()

    def fake_fetch_json(_url: str):
        raise error.HTTPError("https://www.reddit.com/r/missing/new.json?limit=25", 404, "Not Found", hdrs=Message(), fp=None)

    monkeypatch.setattr(reader, "_fetch_json", fake_fetch_json)

    assert reader.fetch_posts("missing") == []


def test_fetch_posts_logs_status_code_and_url_on_http_error(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture):
    reader = RedditJSONReader()

    def fake_fetch_json(_url: str):
        raise error.HTTPError("https://www.reddit.com/r/missing/new.json?limit=25", 404, "Not Found", hdrs=Message(), fp=None)

    monkeypatch.setattr(reader, "_fetch_json", fake_fetch_json)

    with caplog.at_level("WARNING"):
        assert reader.fetch_posts("missing") == []

    assert "status_code=404" in caplog.text
    assert "url=https://www.reddit.com/r/missing/new.json?limit=25" in caplog.text
    assert "error=HTTP Error 404: Not Found" in caplog.text


def test_fetch_posts_marks_reader_rate_limited_on_429(monkeypatch: pytest.MonkeyPatch):
    reader = RedditJSONReader()

    def fake_fetch_json(_url: str):
        raise error.HTTPError("https://www.reddit.com/r/all/new.json?limit=25", 429, "Too Many Requests", hdrs=Message(), fp=None)

    monkeypatch.setattr(reader, "_fetch_json", fake_fetch_json)

    assert reader.fetch_posts("all") == []
    assert reader.rate_limited is True


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


def test_fetch_thread_context_uses_slug_free_url(monkeypatch: pytest.MonkeyPatch):
    reader = RedditJSONReader()
    captured_urls = []

    def fake_fetch_json(url: str):
        captured_urls.append(url)
        return [{"data": {"children": []}}, {"data": {"children": []}}]

    monkeypatch.setattr(reader, "_fetch_json", fake_fetch_json)

    candidate = RedditPostCandidate(
        platform_thread_id="thread-1",
        subreddit="PromptEngineering",
        title="How do I save prompts?",
        body="",
        url="https://www.reddit.com/r/PromptEngineering/comments/thread-1/café/",
    )

    reader.fetch_thread_context(candidate)

    assert captured_urls == ["https://www.reddit.com/r/PromptEngineering/comments/thread-1.json?limit=10"]
    assert "é" not in captured_urls[0]


def test_http_safe_url_percent_encodes_unicode_path():
    reader = RedditJSONReader()

    url = reader._http_safe_url("https://www.reddit.com/r/PromptEngineering/comments/thread-1/café.json?limit=10")

    assert "caf%C3%A9.json" in url
    assert "é" not in url
