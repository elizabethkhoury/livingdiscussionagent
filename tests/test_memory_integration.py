from __future__ import annotations

from datetime import date

from src.decide.engine import RuleBasedDecisionEngine
from src.domain.enums import CommercialOpportunity, DecisionAction, PromotionMode, ResponseStrategy, RiskLevel, SubredditPromoPolicy, Tone
from src.domain.models import ClassificationResult, DecisionResult, DiaryEntry, MemoryContext, PolicyDecisionTrace, RedditPostCandidate, ThreadContext
from src.generate.draft_writer import DraftWriter
from src.learn.diary_memory import format_memory_context
from src.learn.memory_provider import MemoryProvider


class FakeMemoryProvider(MemoryProvider):
    def __init__(self, context: MemoryContext):
        self.context = context

    def get_context(self):
        return self.context


class CapturingLLMClient:
    def __init__(self):
        self.messages = []

    def complete(self, messages):
        self.messages = messages
        return "A practical fix is to store each prompt with model notes and outcome context so reuse becomes easier later."


class FailingLLMClient:
    def complete(self, messages):
        raise RuntimeError("boom")


def make_memory_context(**metrics):
    entry = DiaryEntry(
        date=date(2026, 4, 29),
        yesterday="I tested recent replies.",
        what_happened="Some replies produced weak signals.",
        what_i_learned="I should prefer comparative replies and prioritize specificity.",
        metrics={
            "learning_examples": 3,
            "removals": metrics.get("removals", 0),
            "negative_rewards": metrics.get("negative_rewards", 0),
            "average_reward": metrics.get("average_reward", 0.5),
        },
    )
    context = MemoryContext(daily_entries=[entry], monthly_recaps=[])
    return context.model_copy(update={"prompt_text": format_memory_context(context)})


def make_thread(title: str):
    return ThreadContext(
        post=RedditPostCandidate(
            platform_thread_id="thread-1",
            subreddit="PromptEngineering",
            title=title,
            body="I need a better prompt workflow.",
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


def make_decision():
    return DecisionResult(
        action=DecisionAction.AUTOPOST_INFO,
        promotion_mode=PromotionMode.NONE,
        requires_review=False,
        risk_level=RiskLevel.LOW,
        selected_strategy=ResponseStrategy.EDUCATIONAL,
        trace=PolicyDecisionTrace(reason_codes=["autopost_information_only"]),
    )


def test_decision_engine_uses_memory_but_preserves_hard_skip():
    engine = RuleBasedDecisionEngine(memory_provider=FakeMemoryProvider(make_memory_context()))

    decision = engine.decide(make_thread("This is a job posting for prompt work"), make_classification())

    assert decision.action == DecisionAction.SKIP
    assert decision.selected_strategy == ResponseStrategy.COMPARATIVE
    assert "memory_prefers_comparative_strategy" in decision.trace.reason_codes
    assert "hard_block_signal" in decision.trace.reason_codes
    assert decision.trace.classifier_summary["memory_context"] != "none"


def test_decision_engine_routes_autopost_to_review_when_memory_is_cautious():
    engine = RuleBasedDecisionEngine(memory_provider=FakeMemoryProvider(make_memory_context(removals=1)))

    decision = engine.decide(make_thread("How do I save prompts?"), make_classification())

    assert decision.action == DecisionAction.QUEUE_REVIEW_RISKY
    assert decision.requires_review is True
    assert "memory_caution_requires_review" in decision.trace.reason_codes


def test_draft_writer_includes_memory_in_llm_prompt():
    client = CapturingLLMClient()
    writer = DraftWriter(client, memory_provider=FakeMemoryProvider(make_memory_context()))

    draft = writer.compose(make_thread("How do I save prompts?"), make_decision())

    assert draft is not None
    assert "Recent agent memory:" in client.messages[-1].content
    assert "prefer comparative replies" in client.messages[-1].content


def test_heuristic_fallback_uses_memory_caution():
    writer = DraftWriter(FailingLLMClient(), memory_provider=FakeMemoryProvider(make_memory_context(negative_rewards=3)))

    draft = writer.compose(make_thread("How do I save prompts?"), make_decision())

    assert draft is not None
    assert "Given recent outcome signals" in draft.body
    assert "PromptHunt" not in draft.body


def test_memory_provider_degrades_missing_or_corrupt_file_to_empty_context(tmp_path):
    missing = MemoryProvider(tmp_path / "missing.md").get_context()
    corrupt_path = tmp_path / "corrupt.md"
    corrupt_path.write_text("not a diary file", encoding="utf-8")
    corrupt = MemoryProvider(corrupt_path).get_context()

    assert missing.daily_entries == []
    assert missing.monthly_recaps == []
    assert corrupt.daily_entries == []
    assert corrupt.monthly_recaps == []
