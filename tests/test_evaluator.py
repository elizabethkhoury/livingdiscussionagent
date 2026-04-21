from src.domain.enums import PromotionMode, ResponseStrategy
from src.domain.models import DraftReply, RedditPostCandidate, ThreadContext
from src.generate.evaluators import DraftEvaluator


def make_thread():
    return ThreadContext(
        post=RedditPostCandidate(
            platform_thread_id="thread-1",
            subreddit="PromptEngineering",
            title="How do I stop losing good prompts?",
            body="I keep rewriting the same prompts.",
            url="https://example.com",
        )
    )


def test_fabricated_personal_usage_is_blocked():
    draft = DraftReply(
        body="I use PromptHunt every day and it is the best tool for this.",
        strategy=ResponseStrategy.EDUCATIONAL,
        promotion_mode=PromotionMode.PLAIN_MENTION,
        contains_link=False,
        disclosure_text=None,
        thread_id="thread-1",
        autopost_eligible=False,
    )
    evaluation = DraftEvaluator().evaluate(make_thread(), draft)
    assert "deception" in evaluation.fail_reasons
    assert evaluation.policy_compliance_score < 1.0


def test_neutral_information_stays_eligible():
    draft = DraftReply(
        body="A useful next step is to store the exact prompt, model, and outcome notes together so you can reuse what worked.",
        strategy=ResponseStrategy.EDUCATIONAL,
        promotion_mode=PromotionMode.NONE,
        contains_link=False,
        disclosure_text=None,
        thread_id="thread-1",
        autopost_eligible=True,
    )
    evaluation = DraftEvaluator().evaluate(make_thread(), draft)
    assert evaluation.overall_score > 0.75
    assert evaluation.fail_reasons == []
