from dataclasses import dataclass


@dataclass(slots=True)
class RewardInputs:
    paid_conversions: int = 0
    qualified_signups: int = 0
    positive_replies: int = 0
    upvotes: int = 0
    negative_replies: int = 0
    moderator_flag: bool = False
    zero_engagement: bool = False
    operator_flagged_spammy: bool = False
    token_usage: int = 0
    depth_score: float = 1.0


def depth_multiplier(depth_score: float):
    return min(1.5, max(0.6, depth_score))


def compute_reward(inputs: RewardInputs):
    reward = 0.0
    reward += inputs.paid_conversions * 20
    reward += inputs.qualified_signups * 8
    reward += inputs.positive_replies * 3
    if inputs.upvotes > 2:
        reward += min(inputs.upvotes - 2, 5)
    reward -= inputs.negative_replies * 4
    if inputs.moderator_flag:
        reward -= 8
    if inputs.zero_engagement:
        reward -= 3
    if inputs.operator_flagged_spammy:
        reward -= 5
    reward *= depth_multiplier(inputs.depth_score)
    reward -= inputs.token_usage * 0.002
    return round(reward, 3)
