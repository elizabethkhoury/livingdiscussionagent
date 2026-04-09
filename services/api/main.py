from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from reddit_agent.bootstrap import get_runtime
from reddit_agent.db import get_session, init_db
from reddit_agent.models import Action, RedditCandidate
from reddit_agent.repository import Repository
from reddit_agent.rules import load_subreddit_rules
from reddit_agent.schemas import (
    AgentHealthRead,
    AnalyticsRead,
    ApprovalRequest,
    ApprovalResponse,
    CandidateFeatureSummary,
    CandidateRead,
    DraftRead,
    GenerateDraftResponse,
    IngestResponse,
    ObservationRequest,
    ObservationResponse,
    ReplayRead,
)
from reddit_agent.services.approvals import ApprovalService
from reddit_agent.services.discovery import DiscoveryService
from reddit_agent.services.drafting import DraftingService
from reddit_agent.services.health import HealthService
from reddit_agent.services.observations import ObservationService
from reddit_agent.services.replays import build_replay


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await init_db()
    runtime = get_runtime()
    async for session in get_session():
        repository = Repository(session)
        await repository.ensure_default_agent()
        await repository.upsert_subreddit_profiles(
            load_subreddit_rules(runtime['settings'].config_dir)
        )
        break
    yield


app = FastAPI(title='PromptHunt Reddit Agent API', version='0.1.0', lifespan=lifespan)
settings = get_runtime()['settings']
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.dashboard_api_origin, 'http://localhost:3000'],
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)


SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def repository_dep(session: SessionDep):
    return Repository(session)


RepositoryDep = Annotated[Repository, Depends(repository_dep)]


def serialize_candidate(candidate: RedditCandidate):
    features = [
        CandidateFeatureSummary(
            relevance_score=feature.relevance_score,
            replyability_score=feature.replyability_score,
            promo_fit_score=feature.promo_fit_score,
            risk_score=feature.risk_score,
            uncertainty_score=feature.uncertainty_score,
            freshness_score=feature.freshness_score,
            competition_score=feature.competition_score,
            token_cost_estimate=feature.token_cost_estimate,
            feature_payload=feature.feature_payload,
        )
        for feature in candidate.features
    ]
    return CandidateRead(
        id=candidate.id,
        subreddit=candidate.subreddit,
        title=candidate.title,
        body=candidate.body,
        permalink=candidate.permalink,
        source_kind=candidate.source_kind,
        route_product=candidate.route_product,
        decision=candidate.decision,
        abstain_reason=candidate.abstain_reason,
        evaluator_summary=candidate.evaluator_summary,
        model_confidence=candidate.model_confidence,
        risk_score=candidate.risk_score,
        expected_value=candidate.expected_value,
        discovered_at=candidate.discovered_at,
        features=features,
    )


@app.post('/ingest/reddit/sync', response_model=IngestResponse)
async def ingest_reddit(repository: RepositoryDep):
    runtime = get_runtime()
    discovery = DiscoveryService(
        reddit_browser_discovery=runtime['reddit_browser_discovery'],
        llm_provider=runtime['llm_provider'],
        lifecycle_rules=runtime['lifecycle_rules'],
    )
    created = []
    for subreddit_rule in runtime['subreddit_rules'].values():
        created.extend(
            await discovery.sync_subreddit(
                repository=repository,
                subreddit_rule=subreddit_rule,
                product_rules=runtime['product_rules'],
            )
        )
    return IngestResponse(
        created=len(created),
        queued=sum(1 for item in created if item.decision == 'queue_draft'),
        watched=sum(1 for item in created if item.decision == 'watch_only'),
        abstained=sum(1 for item in created if item.decision == 'abstain'),
        candidate_ids=[item.id for item in created],
    )


@app.get('/candidates', response_model=list[CandidateRead])
async def list_candidates(repository: RepositoryDep):
    stmt = (
        select(RedditCandidate)
        .options(selectinload(RedditCandidate.features))
        .order_by(RedditCandidate.discovered_at.desc())
        .limit(100)
    )
    candidates = list((await repository.session.execute(stmt)).scalars().unique().all())
    return [serialize_candidate(candidate) for candidate in candidates]


@app.post('/drafts/{candidate_id}/generate', response_model=GenerateDraftResponse)
async def generate_draft(candidate_id: str, repository: RepositoryDep):
    stmt = (
        select(RedditCandidate)
        .where(RedditCandidate.id == candidate_id)
        .options(selectinload(RedditCandidate.features))
    )
    candidate = (await repository.session.execute(stmt)).scalar_one_or_none()
    if candidate is None:
        raise HTTPException(status_code=404, detail='Candidate not found.')
    draft = await DraftingService(get_runtime()['llm_provider']).generate(
        repository=repository, candidate=candidate
    )
    return GenerateDraftResponse(
        candidate=serialize_candidate(candidate),
        draft=DraftRead(
            id=draft.id,
            candidate_id=draft.candidate_id,
            version=draft.version,
            body=draft.body,
            critic_notes=draft.critic_notes,
            token_usage=draft.token_usage,
            similarity_score=draft.similarity_score,
            status=draft.status,
            created_at=draft.created_at,
        ),
    )


@app.post('/approvals/{draft_id}', response_model=ApprovalResponse)
async def submit_approval(draft_id: str, payload: ApprovalRequest, repository: RepositoryDep):
    try:
        draft, handoff_url, post_action = await ApprovalService(
            get_runtime()['posting_dispatcher']
        ).decide(
            repository=repository,
            draft_id=draft_id,
            decision=payload.decision,
            operator_feedback=payload.operator_feedback,
            edited_body=payload.edited_body,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ApprovalResponse(
        draft_id=draft.id,
        status=draft.status,
        handoff_url=handoff_url,
        final_body=draft.body,
        post_action_id=post_action.id if post_action else None,
        post_status='queued' if post_action else None,
        live_view_url=None,
    )


@app.post('/observations/reddit', response_model=ObservationResponse)
async def record_observation(payload: ObservationRequest, repository: RepositoryDep):
    try:
        observation, policy = await ObservationService().record(
            repository=repository, payload=payload.model_dump()
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ObservationResponse(
        observation_id=observation.id,
        reward_delta=observation.reward_delta,
        agent_score=policy.score,
    )


@app.get('/agents/{agent_id}/health', response_model=AgentHealthRead)
async def get_health(agent_id: str, repository: RepositoryDep):
    policy = await repository.get_agent(agent_id)
    if policy is None:
        raise HTTPException(status_code=404, detail='Agent not found.')
    policy = await HealthService().refresh_policy_state(
        session=repository.session,
        policy=policy,
        rules=get_runtime()['lifecycle_rules'],
    )
    return AgentHealthRead(
        id=policy.id,
        name=policy.name,
        state=policy.state,
        score=policy.score,
        version=policy.version,
        strict_mode_until=policy.strict_mode_until,
        thresholds=policy.thresholds,
        recent_failures=[],
    )


@app.get('/replays/{run_id}', response_model=ReplayRead)
async def get_replay(run_id: str, repository: RepositoryDep):
    stmt = (
        select(RedditCandidate)
        .where(RedditCandidate.id == run_id)
        .options(selectinload(RedditCandidate.drafts), selectinload(RedditCandidate.actions))
    )
    candidate = (await repository.session.execute(stmt)).scalar_one_or_none()
    if candidate is None:
        raise HTTPException(status_code=404, detail='Replay not found.')
    return build_replay(candidate)


@app.get('/analytics', response_model=AnalyticsRead)
async def get_analytics(repository: RepositoryDep):
    return AnalyticsRead(**(await repository.analytics_snapshot()))


@app.get('/agents/default')
async def get_default_agent(repository: RepositoryDep):
    policy = await repository.first_agent()
    return {'id': policy.id, 'score': policy.score, 'state': policy.state}


@app.get('/actions/manual-posts')
async def list_manual_posts(repository: RepositoryDep):
    stmt = (
        select(Action)
        .where(
            Action.action_type.in_(['manual_handoff', 'post_requested', 'posted', 'post_failed'])
        )
        .order_by(Action.created_at.desc())
        .limit(100)
    )
    rows = list((await repository.session.execute(stmt)).scalars().all())
    return [
        {
            'id': row.id,
            'candidate_id': row.candidate_id,
            'draft_id': row.draft_id,
            'notes': row.notes,
            'payload': row.payload,
            'created_at': row.created_at,
        }
        for row in rows
    ]
