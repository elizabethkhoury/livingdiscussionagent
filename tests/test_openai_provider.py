import json
import sys
from types import ModuleType, SimpleNamespace

import pytest

from reddit_agent.bootstrap import build_llm_provider
from reddit_agent.browser.agent import RedditBrowserAgent
from reddit_agent.providers.mock_llm import MockLLMProvider
from reddit_agent.providers.openai_llm import OpenAILLMProvider
from reddit_agent.settings import Settings


class FakeAsyncOpenAI:
    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))
        FakeAsyncOpenAI.instances.append(self)

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        schema_name = kwargs['response_format']['json_schema']['name']
        payload_by_schema = {
            'candidate_evaluation': {
                'relevance_score': 0.91,
                'replyability_score': 0.84,
                'promo_fit_score': 0.79,
                'risk_score': 0.12,
                'uncertainty_score': 0.19,
                'confidence': 0.88,
                'summary': 'Strong fit for a direct, non-spammy response.',
                'depth_score': 1.1,
            },
            'reddit_draft': {
                'body': 'PromptHunt seems like a good fit here if you mainly want one place to '
                'save and reuse the prompts that actually work.'
            },
            'draft_critic_notes': {
                'awkwardness': 'low',
                'repetition_risk': 0.08,
                'safety': 'pass',
                'subreddit_fit': 'Fits a practical prompt-workflow discussion.',
                'route_product': 'prompthunt.me',
            },
        }
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=json.dumps(payload_by_schema[schema_name]),
                        refusal=None,
                    )
                )
            ],
            usage=SimpleNamespace(total_tokens=321),
        )


@pytest.mark.asyncio
async def test_openai_provider_uses_structured_outputs(monkeypatch):
    FakeAsyncOpenAI.instances.clear()
    monkeypatch.setattr('reddit_agent.providers.openai_llm.AsyncOpenAI', FakeAsyncOpenAI)

    provider = OpenAILLMProvider(
        Settings(
            _env_file=None,
            openai_api_key='test-key',
            generation_model='gpt-5.4',
            evaluator_model='gpt-5.4-mini',
        )
    )

    evaluation = await provider.evaluate_candidate(
        title='Need a prompt library',
        body='I keep losing the prompts that work best for me.',
        route_product='prompthunt.me',
    )
    draft = await provider.generate_draft(
        title='Need a prompt library',
        body='I keep losing the prompts that work best for me.',
        subreddit='PromptEngineering',
        route_product='prompthunt.me',
    )
    critic = await provider.critic_pass(
        draft=draft.body,
        route_product='prompthunt.me',
        subreddit='PromptEngineering',
    )

    client = FakeAsyncOpenAI.instances[0]
    assert client.kwargs == {'api_key': 'test-key'}
    assert [call['response_format']['json_schema']['name'] for call in client.calls] == [
        'candidate_evaluation',
        'reddit_draft',
        'draft_critic_notes',
    ]
    assert all(call['reasoning_effort'] == 'medium' for call in client.calls)
    assert all(call['verbosity'] == 'medium' for call in client.calls)
    assert evaluation.summary.startswith('Strong fit')
    assert draft.token_usage == 321
    assert critic.token_usage == 321
    assert critic.notes['route_product'] == 'prompthunt.me'


def test_build_llm_provider_switches_on_mode(monkeypatch):
    sentinel = object()

    monkeypatch.setattr('reddit_agent.bootstrap.OpenAILLMProvider', lambda settings: sentinel)

    assert isinstance(
        build_llm_provider(Settings(_env_file=None, llm_mode='mock')), MockLLMProvider
    )
    assert (
        build_llm_provider(Settings(_env_file=None, llm_mode='openai', openai_api_key='test-key'))
        is sentinel
    )


def test_browser_agent_defaults_to_openai_credentials(monkeypatch):
    calls = []
    fake_browser_use = ModuleType('browser_use')

    class FakeChatOpenAI:
        def __init__(self, **kwargs):
            calls.append(kwargs)

    fake_browser_use.ChatOpenAI = FakeChatOpenAI
    monkeypatch.setitem(sys.modules, 'browser_use', fake_browser_use)

    agent = RedditBrowserAgent(
        Settings(
            _env_file=None,
            openai_api_key='openai-key',
            openai_base_url='https://api.openai.example/v1',
            browser_agent_model='gpt-5.4-mini',
        )
    )
    agent._build_llm()

    assert calls == [
        {
            'model': 'gpt-5.4-mini',
            'api_key': 'openai-key',
            'base_url': 'https://api.openai.example/v1',
        }
    ]
