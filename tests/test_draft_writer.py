from __future__ import annotations

from src.domain.enums import DecisionAction, PromotionMode, ResponseStrategy, RiskLevel
from src.domain.models import DecisionResult, PolicyDecisionTrace, RedditCommentCandidate, RedditPostCandidate, ThreadContext
from src.generate.draft_writer import DraftWriter
from src.generate.evaluators import DraftEvaluator


class StubLLMClient:
    def __init__(self, response: str):
        self.response = response

    def complete(self, messages, temperature: float = 0.2):
        return self.response


class FailingLLMClient:
    def complete(self, messages, temperature: float = 0.2):
        raise RuntimeError("boom")


def make_thread():
    return ThreadContext(
        post=RedditPostCandidate(
            platform_thread_id="thread-1",
            subreddit="PromptEngineering",
            title="How do I stop losing good prompts?",
            body="I keep rewriting the same prompts and forgetting what worked.",
            url="https://example.com",
        ),
        target_comment=RedditCommentCandidate(
            platform_comment_id="comment-1",
            author="user",
            body="I need a workflow that helps me reuse the good ones.",
        ),
    )


def make_decision(promotion_mode: PromotionMode):
    return DecisionResult(
        action=DecisionAction.QUEUE_REVIEW_PRODUCT,
        promotion_mode=promotion_mode,
        requires_review=promotion_mode != PromotionMode.NONE,
        risk_level=RiskLevel.MEDIUM,
        selected_strategy=ResponseStrategy.EDUCATIONAL,
        trace=PolicyDecisionTrace(reason_codes=["test"]),
    )


def test_compose_uses_llm_output_when_candidate_is_safe():
    writer = DraftWriter(StubLLMClient("A practical fix is to store each prompt with the model, result notes, and reuse context so you can find proven versions quickly."))

    draft = writer.compose(make_thread(), make_decision(PromotionMode.NONE))

    assert draft is not None
    assert draft.body == "A practical fix is to store each prompt with the model, result notes, and reuse context so you can find proven versions quickly."
    assert draft.autopost_eligible is True
    assert draft.disclosure_text is None


def test_compose_falls_back_to_heuristic_when_llm_fails():
    writer = DraftWriter(FailingLLMClient())

    draft = writer.compose(make_thread(), make_decision(PromotionMode.PLAIN_MENTION))

    assert draft is not None
    assert "PromptHunt could fit" in draft.body
    assert draft.disclosure_text is None


def test_compose_appends_disclosure_for_monetized_mode():
    writer = DraftWriter(StubLLMClient("A good next step is to save prompts with outcome notes so you can compare versions and keep the useful ones."))

    draft = writer.compose(make_thread(), make_decision(PromotionMode.DISCLOSED_MONETIZED))

    assert draft is not None
    assert "PromptHunt" in draft.body
    assert draft.disclosure_text == "Disclosure: I'm affiliated with PromptHunt."
    assert draft.body.endswith("Disclosure: I'm affiliated with PromptHunt.")


def test_compose_keeps_plain_mention_mode_without_disclosure():
    writer = DraftWriter(StubLLMClient("A useful way to handle this is to keep your best prompts with notes, and a tool like PromptHunt can help if you want a shared library."))

    draft = writer.compose(make_thread(), make_decision(PromotionMode.PLAIN_MENTION))

    assert draft is not None
    assert "PromptHunt" in draft.body
    assert draft.disclosure_text is None


def test_compose_returns_none_for_skip():
    decision = DecisionResult(
        action=DecisionAction.SKIP,
        promotion_mode=PromotionMode.NONE,
        requires_review=False,
        risk_level=RiskLevel.BLOCK,
        selected_strategy=ResponseStrategy.EDUCATIONAL,
        trace=PolicyDecisionTrace(reason_codes=["skip"]),
    )

    assert DraftWriter(StubLLMClient("ignored")).compose(make_thread(), decision) is None


def test_generated_safe_reply_passes_evaluator():
    writer = DraftWriter(
        StubLLMClient("A practical next step is to save each prompt with the model, the output quality notes, and when it worked so reuse becomes deliberate instead of guesswork.")
    )

    draft = writer.compose(make_thread(), make_decision(PromotionMode.NONE))

    assert draft is not None
    evaluation = DraftEvaluator().evaluate(make_thread(), draft)
    assert evaluation.overall_score > 0.75
    assert evaluation.fail_reasons == []
