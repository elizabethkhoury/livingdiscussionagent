from __future__ import annotations

from collections import Counter

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from reddit_agent.models import (
    Action,
    AgentPolicy,
    AgentScore,
    Approval,
    CandidateFeature,
    Draft,
    DraftStatus,
    Observation,
    RedditCandidate,
    SubredditProfile,
)


class Repository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def ensure_default_agent(self):
        query = select(AgentPolicy).order_by(AgentPolicy.created_at.asc()).limit(1)
        policy = (await self.session.execute(query)).scalar_one_or_none()
        if policy is None:
            policy = AgentPolicy(
                name='default',
                score=50.0,
                identity={
                    'voice': 'useful, calm, direct',
                    'product_routing': 'mention exactly one product',
                },
                thresholds={},
            )
            self.session.add(policy)
            await self.session.commit()
            await self.session.refresh(policy)
        return policy

    async def upsert_subreddit_profiles(self, rules):
        existing = {
            item.subreddit.lower(): item
            for item in (await self.session.execute(select(SubredditProfile))).scalars().all()
        }
        for name, rule in rules.items():
            profile = existing.get(name)
            if profile is None:
                profile = SubredditProfile(
                    subreddit=rule.name,
                    allow_promotion=rule.allow_promotion,
                    allow_links=rule.allow_links,
                    notes=rule.notes,
                    tags=rule.tags,
                )
                self.session.add(profile)
                continue
            profile.allow_promotion = rule.allow_promotion
            profile.allow_links = rule.allow_links
            profile.notes = rule.notes
            profile.tags = rule.tags
        await self.session.commit()

    async def create_candidate(self, payload: dict, decision_trace: dict):
        candidate = RedditCandidate(**payload, decision_trace=decision_trace)
        self.session.add(candidate)
        await self.session.flush()
        return candidate

    async def find_candidate_by_source(self, *, reddit_post_id: str | None, permalink: str):
        clauses = [RedditCandidate.permalink == permalink]
        if reddit_post_id:
            clauses.append(RedditCandidate.reddit_post_id == reddit_post_id)
        stmt = select(RedditCandidate).where(or_(*clauses)).limit(1)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def add_features(self, candidate_id: str, payload: dict):
        feature = CandidateFeature(candidate_id=candidate_id, **payload)
        self.session.add(feature)
        await self.session.flush()
        return feature

    async def create_draft(
        self,
        candidate_id: str,
        body: str,
        critic_notes: dict,
        token_usage: int,
        similarity_score: float,
    ):
        draft = Draft(
            candidate_id=candidate_id,
            body=body,
            critic_notes=critic_notes,
            token_usage=token_usage,
            similarity_score=similarity_score,
        )
        self.session.add(draft)
        await self.session.flush()
        return draft

    async def create_action(
        self,
        candidate_id: str,
        action_type: str,
        draft_id: str | None = None,
        notes: str | None = None,
        payload: dict | None = None,
    ):
        action = Action(
            candidate_id=candidate_id,
            draft_id=draft_id,
            action_type=action_type,
            notes=notes,
            payload=payload or {},
        )
        self.session.add(action)
        await self.session.flush()
        return action

    async def add_approval(
        self, draft_id: str, decision: str, operator_feedback: str | None, edited_body: str | None
    ):
        approval = Approval(
            draft_id=draft_id,
            decision=decision,
            operator_feedback=operator_feedback,
            edited_body=edited_body,
        )
        self.session.add(approval)
        await self.session.flush()
        return approval

    async def add_observation(self, action_id: str, payload: dict, reward_delta: float):
        observation = Observation(action_id=action_id, reward_delta=reward_delta, **payload)
        self.session.add(observation)
        await self.session.flush()
        return observation

    async def update_agent_score(self, policy: AgentPolicy, delta: float, reason: str):
        policy.score += delta
        self.session.add(AgentScore(agent_policy_id=policy.id, points=delta, reason=reason))
        await self.session.flush()
        return policy

    async def list_candidates(self) -> list[RedditCandidate]:
        stmt: Select[tuple[RedditCandidate]] = (
            select(RedditCandidate).order_by(RedditCandidate.discovered_at.desc()).limit(100)
        )
        return list((await self.session.execute(stmt)).scalars().unique().all())

    async def get_candidate(self, candidate_id: str):
        return await self.session.get(RedditCandidate, candidate_id)

    async def get_draft(self, draft_id: str):
        return await self.session.get(Draft, draft_id)

    async def get_action(self, action_id: str):
        return await self.session.get(Action, action_id)

    async def list_actions_for_candidate(self, candidate_id: str):
        stmt = (
            select(Action)
            .where(Action.candidate_id == candidate_id)
            .order_by(Action.created_at.asc())
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def latest_manual_post_action(self, draft_id: str):
        stmt = (
            select(Action)
            .where(Action.draft_id == draft_id, Action.action_type == 'manual_handoff')
            .order_by(Action.created_at.desc())
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_agent(self, agent_id: str):
        return await self.session.get(AgentPolicy, agent_id)

    async def first_agent(self):
        stmt = select(AgentPolicy).order_by(AgentPolicy.created_at.asc()).limit(1)
        return (await self.session.execute(stmt)).scalar_one()

    async def approved_action_count(self):
        return await self.session.scalar(
            select(func.count())
            .select_from(Draft)
            .where(Draft.status == DraftStatus.approved.value)
        )

    async def latest_score_event(self, agent_policy_id: str):
        stmt = (
            select(AgentScore)
            .where(AgentScore.agent_policy_id == agent_policy_id)
            .order_by(AgentScore.created_at.desc())
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def analytics_snapshot(self):
        queued = await self.session.scalar(select(func.count()).select_from(Draft))
        approvals = await self.session.scalar(
            select(func.count())
            .select_from(Draft)
            .where(Draft.status == DraftStatus.approved.value)
        )
        executed_posts = await self.session.scalar(
            select(func.count()).select_from(Action).where(Action.action_type == 'posted')
        )
        reward_total = await self.session.scalar(
            select(func.coalesce(func.sum(Observation.reward_delta), 0.0))
        )
        conversion_total = await self.session.scalar(
            select(func.coalesce(func.sum(Observation.paid_conversions), 0))
        )
        candidate_rows = (
            await self.session.execute(
                select(RedditCandidate.subreddit, RedditCandidate.route_product)
            )
        ).all()
        by_product = Counter(product or 'unrouted' for _, product in candidate_rows)
        by_subreddit = Counter(subreddit for subreddit, _ in candidate_rows)
        return {
            'queued_drafts': queued or 0,
            'approvals': approvals or 0,
            'manual_posts': executed_posts or 0,
            'executed_posts': executed_posts or 0,
            'total_reward': reward_total or 0.0,
            'conversions': conversion_total or 0,
            'by_product': dict(by_product),
            'by_subreddit': dict(by_subreddit),
        }
