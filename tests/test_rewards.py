from reddit_agent.rewards import RewardInputs, compute_reward, depth_multiplier


def test_depth_multiplier_bounds():
    assert depth_multiplier(0.1) == 0.6
    assert depth_multiplier(3.0) == 1.5


def test_reward_prefers_conversions_over_upvotes():
    high_conversion = compute_reward(
        RewardInputs(paid_conversions=1, upvotes=4, token_usage=50, depth_score=1.1)
    )
    high_upvote = compute_reward(RewardInputs(upvotes=25, token_usage=50, depth_score=1.1))
    assert high_conversion > high_upvote


def test_reward_penalizes_negative_feedback():
    reward = compute_reward(
        RewardInputs(negative_replies=2, zero_engagement=True, moderator_flag=True, token_usage=100)
    )
    assert reward < 0
