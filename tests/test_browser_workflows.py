from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from reddit_agent import models as _models  # noqa: F401
from reddit_agent.db import Base
from reddit_agent.models import ActionType, ApprovalDecision, DraftStatus
from reddit_agent.repository import Repository
from reddit_agent.rules import load_lifecycle_rules, load_product_rules, load_subreddit_rules
from reddit_agent.services.approvals import ApprovalService
from reddit_agent.services.discovery import DiscoveryService
from reddit_agent.services.posting import PostingService


@pytest.fixture
async def repository():
    engine = create_async_engine('sqlite+aiosqlite:///:memory:')
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with session_factory() as session:
        repository = Repository(session)
        await repository.ensure_default_agent()
        yield repository
    await engine.dispose()


async def create_candidate_and_draft(repository: Repository):
    candidate = await repository.create_candidate(
        {
            'reddit_post_id': 'post-1',
            'subreddit': 'PromptEngineering',
            'title': 'Need a better prompt workflow',
            'body': 'I keep losing useful prompts and need a better system.',
            'permalink': 'https://www.reddit.com/r/PromptEngineering/comments/post-1/test/',
            'author': 'example-user',
            'freshness_hours': 1.0,
            'num_comments': 12,
            'source_kind': 'post',
            'route_product': 'prompthunt',
            'decision': 'queue_draft',
            'abstain_reason': None,
            'evaluator_summary': 'High fit.',
            'model_confidence': 0.92,
            'risk_score': 0.1,
            'expected_value': 0.87,
        },
        {'seed': True},
    )
    draft = await repository.create_draft(
        candidate.id,
        'PromptHunt might help organize the prompts you keep reusing.',
        {'critic': 'clean'},
        88,
        0.04,
    )
    await repository.session.commit()
    return candidate, draft


class FakeDispatcher:
    def __init__(self):
        self.action_ids: list[str] = []

    async def dispatch(self, action_id: str):
        self.action_ids.append(action_id)
        return 'local'


class FakePoster:
    def __init__(self, status: str):
        self.status = status

    async def post_reply(self, *, permalink: str, body: str):
        diagnostics = {
            'current_url': permalink,
            'session_id': 'session-1',
            'live_view_url': 'https://kernel.example/live/session-1',
        }
        if self.status == 'posted':
            return {
                'status': 'posted',
                'comment_url': f'{permalink}comment/test',
                'diagnostics': diagnostics,
            }
        return {
            'status': self.status,
            'diagnostics': diagnostics,
        }


class FakeBrowserDiscovery:
    def __init__(self, payloads):
        self.payloads = payloads

    async def fetch_new_posts(self, subreddit: str):
        return self.payloads


class FakeEvaluation:
    relevance_score = 0.9
    replyability_score = 0.8
    promo_fit_score = 0.9
    risk_score = 0.1
    uncertainty_score = 0.1
    depth_score = 1.0
    confidence = 0.95
    summary = 'Strong fit.'


class FakeLLMProvider:
    async def evaluate_candidate(self, *, title: str, body: str, route_product: str | None):
        return FakeEvaluation()


@pytest.mark.asyncio
async def test_approval_creates_post_request_and_dispatches(repository: Repository):
    candidate, draft = await create_candidate_and_draft(repository)
    dispatcher = FakeDispatcher()

    updated_draft, handoff_url, post_action = await ApprovalService(dispatcher).decide(
        repository=repository,
        draft_id=draft.id,
        decision=ApprovalDecision.approve,
        operator_feedback=None,
        edited_body=None,
    )

    assert updated_draft.status == DraftStatus.approved.value
    assert handoff_url == candidate.permalink
    assert post_action is not None
    assert post_action.action_type == ActionType.post_requested.value
    assert dispatcher.action_ids == [post_action.id]


@pytest.mark.asyncio
async def test_approval_reject_does_not_dispatch(repository: Repository):
    _, draft = await create_candidate_and_draft(repository)
    dispatcher = FakeDispatcher()

    updated_draft, handoff_url, post_action = await ApprovalService(dispatcher).decide(
        repository=repository,
        draft_id=draft.id,
        decision=ApprovalDecision.reject,
        operator_feedback='Not a fit.',
        edited_body=None,
    )

    assert updated_draft.status == DraftStatus.rejected.value
    assert handoff_url is None
    assert post_action is None
    assert dispatcher.action_ids == []


@pytest.mark.asyncio
async def test_posting_service_marks_draft_posted(repository: Repository):
    candidate, draft = await create_candidate_and_draft(repository)
    requested = await repository.create_action(
        candidate.id,
        ActionType.post_requested.value,
        draft_id=draft.id,
        payload={'permalink': candidate.permalink, 'body': draft.body},
    )
    await repository.session.commit()

    action = await PostingService(FakePoster('posted')).post_approved_draft(
        repository=repository,
        action_id=requested.id,
    )

    refreshed_draft = await repository.get_draft(draft.id)
    assert refreshed_draft.status == DraftStatus.posted.value
    assert action.action_type == ActionType.posted.value
    assert action.payload['external_comment_url'].endswith('comment/test')


@pytest.mark.asyncio
async def test_posting_service_records_failure_without_posting(repository: Repository):
    candidate, draft = await create_candidate_and_draft(repository)
    draft.status = DraftStatus.approved.value
    requested = await repository.create_action(
        candidate.id,
        ActionType.post_requested.value,
        draft_id=draft.id,
        payload={'permalink': candidate.permalink, 'body': draft.body},
    )
    await repository.session.commit()

    action = await PostingService(FakePoster('auth_required')).post_approved_draft(
        repository=repository,
        action_id=requested.id,
    )

    refreshed_draft = await repository.get_draft(draft.id)
    assert refreshed_draft.status == DraftStatus.approved.value
    assert action.action_type == ActionType.post_failed.value
    assert action.payload['auth_required'] is True


@pytest.mark.asyncio
async def test_analytics_counts_executed_posts(repository: Repository):
    candidate, draft = await create_candidate_and_draft(repository)
    await repository.create_action(candidate.id, ActionType.posted.value, draft_id=draft.id)
    await repository.session.commit()

    snapshot = await repository.analytics_snapshot()
    assert snapshot['executed_posts'] == 1
    assert snapshot['manual_posts'] == 1


@pytest.mark.asyncio
async def test_discovery_skips_duplicate_candidates(repository: Repository):
    payload = {
        'reddit_post_id': 'post-duplicate',
        'subreddit': 'PromptEngineering',
        'title': 'Prompt library for repeated workflows',
        'body': 'How are you all storing prompts for Cursor and Claude?',
        'permalink': 'https://www.reddit.com/r/PromptEngineering/comments/post-duplicate/test/',
        'author': 'example-user',
        'source_kind': 'post',
        'freshness_hours': 0.1,
        'num_comments': 3,
        'browser_metadata': {'extraction_mode': 'browser_agent'},
    }
    service = DiscoveryService(
        reddit_browser_discovery=FakeBrowserDiscovery([payload]),
        llm_provider=FakeLLMProvider(),
        lifecycle_rules=load_lifecycle_rules(Path('config/rules')),
    )

    subreddit_rule = load_subreddit_rules(Path('config/rules'))['promptengineering']
    product_rules = load_product_rules(Path('config/rules'))

    first = await service.sync_subreddit(
        repository=repository,
        subreddit_rule=subreddit_rule,
        product_rules=product_rules,
    )
    second = await service.sync_subreddit(
        repository=repository,
        subreddit_rule=subreddit_rule,
        product_rules=product_rules,
    )

    assert len(first) == 1
    assert len(second) == 0
    candidates = await repository.list_candidates()
    assert len(candidates) == 1
