from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import desc, func, select

from reddit_agent.models import AgentPolicy, AgentScore, Draft, DraftStatus, HealthState
from reddit_agent.rules import LifecycleRules


def determine_health_state(
    *,
    score: float,
    approved_actions: int,
    paused_days: int,
    negative_reflections: int,
    rules: LifecycleRules,
):
    if negative_reflections >= 3 or score < rules.retire_below:
        return HealthState.retired
    if paused_days >= 7:
        return HealthState.dormant
    if score < rules.stressed_below:
        return HealthState.stressed
    if approved_actions >= 25:
        return HealthState.mature
    return HealthState.seed


class HealthService:
    async def refresh_policy_state(self, *, session, policy: AgentPolicy, rules: LifecycleRules):
        scores = (
            (
                await session.execute(
                    select(AgentScore)
                    .where(AgentScore.agent_policy_id == policy.id)
                    .order_by(desc(AgentScore.created_at))
                    .limit(3)
                )
            )
            .scalars()
            .all()
        )
        negative_reflections = sum(1 for score in scores if score.points < 0)
        approved_actions = await session.scalar(
            select(func.count())
            .select_from(Draft)
            .where(Draft.status == DraftStatus.approved.value)
        )
        latest_score = (
            await session.execute(
                select(AgentScore)
                .where(AgentScore.agent_policy_id == policy.id)
                .order_by(desc(AgentScore.created_at))
                .limit(1)
            )
        ).scalar_one_or_none()
        paused_days = 0
        if latest_score is not None:
            paused_days = max(0, (datetime.now(UTC) - latest_score.created_at).days)
        policy.state = determine_health_state(
            score=policy.score,
            approved_actions=approved_actions or 0,
            paused_days=paused_days,
            negative_reflections=negative_reflections,
            rules=rules,
        ).value
        if policy.state == HealthState.retired.value and policy.retired_at is None:
            policy.retired_at = datetime.now(UTC)
        if policy.state in {HealthState.seed.value, HealthState.stressed.value}:
            policy.strict_mode_until = datetime.now(UTC) + timedelta(days=rules.strict_mode_days)
        await session.commit()
        return policy
