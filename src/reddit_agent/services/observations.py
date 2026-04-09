from __future__ import annotations

from reddit_agent.repository import Repository
from reddit_agent.rewards import RewardInputs, compute_reward


class ObservationService:
    async def record(self, *, repository: Repository, payload: dict):
        action = await repository.get_action(payload['action_id'])
        if action is None:
            raise ValueError('Action not found.')
        reward = compute_reward(
            RewardInputs(
                paid_conversions=payload['paid_conversions'],
                qualified_signups=payload['qualified_signups'],
                positive_replies=payload['positive_replies'],
                upvotes=payload['upvotes'],
                negative_replies=payload['negative_replies'],
                moderator_flag=payload['moderator_flag'],
                zero_engagement=payload['zero_engagement'],
                operator_flagged_spammy=payload.get('operator_flagged_spammy', False),
                token_usage=payload.get('token_usage', 0),
                depth_score=payload.get('depth_score', 1.0),
            )
        )
        observation = await repository.add_observation(action.id, payload, reward)
        policy = await repository.first_agent()
        await repository.update_agent_score(
            policy, reward, f'Observation at {payload["horizon_hours"]}h'
        )
        await repository.session.commit()
        return observation, policy
