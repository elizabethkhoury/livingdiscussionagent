from src.decide.engine import RuleBasedDecisionEngine
from src.domain.enums import CommercialOpportunity, SubredditPromoPolicy, Tone
from src.domain.models import ClassificationResult, RedditPostCandidate, ThreadContext


def make_thread(text: str):
    return ThreadContext(
        post=RedditPostCandidate(
            platform_thread_id="thread-1",
            subreddit="PromptEngineering",
            title=text,
            body="",
            url="https://example.com",
        )
    )


def make_classification(**overrides):
    base = ClassificationResult(
        intent="question",
        relevance_score=0.9,
        commercial_opportunity=CommercialOpportunity.LOW,
        value_add_score=0.9,
        policy_risk_score=0.2,
        promo_fit_score=0.2,
        tone=Tone.BEGINNER,
        subreddit_promo_policy=SubredditPromoPolicy.ALLOW,
        duplicate_similarity_score=0.1,
        reason_codes=[],
    )
    return base.model_copy(update=overrides)


def test_low_relevance_skips():
    decision = RuleBasedDecisionEngine().decide(
        make_thread("How do I save prompts?"),
        make_classification(relevance_score=0.5),
    )
    assert decision.action.value == "skip"


def test_high_value_no_promo_autoposts_info():
    decision = RuleBasedDecisionEngine().decide(
        make_thread("How do I keep my prompt workflow organized?"),
        make_classification(),
    )
    assert decision.action.value == "autopost_info"
    assert decision.promotion_mode.value == "none"


def test_high_promo_fit_routes_to_review():
    decision = RuleBasedDecisionEngine().decide(
        make_thread("Where can I find and save reusable prompts?"),
        make_classification(
            commercial_opportunity=CommercialOpportunity.HIGH,
            promo_fit_score=0.9,
        ),
    )
    assert decision.requires_review is True
    assert decision.action.value == "queue_review_product"


def test_deny_policy_blocks_promo_but_not_info():
    decision = RuleBasedDecisionEngine().decide(
        make_thread("How do I save prompts without losing context?"),
        make_classification(subreddit_promo_policy=SubredditPromoPolicy.DENY),
    )
    assert decision.promotion_mode.value == "none"
