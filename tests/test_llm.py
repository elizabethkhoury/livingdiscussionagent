from __future__ import annotations

import json

import pytest

from src.app import llm
from src.app.llm import HeuristicLLMClient, LLMMessage, OpenAILLMClient, get_llm_client
from src.app.settings import get_settings


class DummyResponse:
    def __init__(self, payload: dict):
        self.payload = payload

    def read(self):
        return json.dumps(self.payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


@pytest.fixture(autouse=True)
def clear_settings_cache(monkeypatch: pytest.MonkeyPatch):
    get_settings.cache_clear()
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    yield
    get_settings.cache_clear()


def test_get_llm_client_uses_heuristic_without_api_key():
    client = get_llm_client()
    assert isinstance(client, HeuristicLLMClient)


def test_get_llm_client_uses_openai_with_api_key(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-test-mini")
    get_settings.cache_clear()

    client = get_llm_client()

    assert isinstance(client, OpenAILLMClient)
    assert client.api_key == "test-key"
    assert client.model == "gpt-test-mini"


def test_openai_llm_client_sends_expected_request(monkeypatch: pytest.MonkeyPatch):
    captured: dict[str, object] = {}

    def fake_urlopen(req, timeout):
        captured["url"] = req.full_url
        captured["timeout"] = timeout
        captured["headers"] = dict(req.header_items())
        captured["payload"] = json.loads(req.data.decode("utf-8"))
        return DummyResponse(
            {
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "Helpful reply"}],
                    }
                ]
            }
        )

    monkeypatch.setattr(llm.request, "urlopen", fake_urlopen)

    client = OpenAILLMClient("secret", "gpt-5-mini")
    result = client.complete(
        [
            LLMMessage(role="system", content="System prompt"),
            LLMMessage(role="user", content="User prompt"),
        ],
        temperature=0.4,
    )

    assert result == "Helpful reply"
    assert captured["url"] == "https://api.openai.com/v1/responses"
    assert captured["timeout"] == 30
    assert captured["headers"] == {
        "Authorization": "Bearer secret",
        "Content-type": "application/json",
    }
    assert captured["payload"] == {
        "model": "gpt-5-mini",
        "temperature": 0.4,
        "input": [
            {
                "role": "system",
                "content": [{"type": "input_text", "text": "System prompt"}],
            },
            {
                "role": "user",
                "content": [{"type": "input_text", "text": "User prompt"}],
            },
        ],
    }


def test_openai_llm_client_extracts_multiple_output_text_blocks(monkeypatch: pytest.MonkeyPatch):
    def fake_urlopen(_req, timeout):
        return DummyResponse(
            {
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [
                            {"type": "output_text", "text": "First line"},
                            {"type": "output_text", "text": "Second line"},
                        ],
                    }
                ]
            }
        )

    monkeypatch.setattr(llm.request, "urlopen", fake_urlopen)

    client = OpenAILLMClient("secret", "gpt-5-mini")

    assert client.complete([LLMMessage(role="user", content="Prompt")]) == "First line\nSecond line"
