from __future__ import annotations

from src.app.settings import get_settings
from src.domain.enums import DecisionAction, PromotionMode, ResponseStrategy, RiskLevel
from src.domain.models import DecisionResult, PolicyDecisionTrace, RedditCommentCandidate, RedditPostCandidate, ThreadContext
from src.generate.draft_writer import DraftWriter
from src.generate.evaluators import DraftEvaluator


class StubLLMClient:
    def __init__(self, response: str):
        self.response = response
        self.messages = None  # Last call's messages
        self.all_messages = []  # Every call's messages, in order
        self.call_count = 0

    def complete(self, messages):
        self.call_count += 1
        self.all_messages.append(messages)
        # First call is always the draft-generation prompt. Subsequent calls
        # (on-topic judge, retries) get a "yes" so the gate passes.
        if self.call_count == 1:
            self.messages = messages
            return self.response
        return "yes"


class FailingLLMClient:
    def complete(self, messages):
        raise RuntimeError("boom")


class TimeoutLLMClient:
    def complete(self, messages):
        raise TimeoutError("The read operation timed out")


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


def make_weak_fit_thread():
    return ThreadContext(
        post=RedditPostCandidate(
            platform_thread_id="thread-weak",
            subreddit="ChatGPT",
            title="How do I get better outputs from ChatGPT?",
            body="My answers are vague and I am not sure what detail to add.",
            url="https://example.com",
        )
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


def test_prompt_includes_short_reply_question_and_product_guidance():
    client = StubLLMClient("A practical fix is to store prompts with result notes so reuse is easier later. What part gets lost most often?")
    writer = DraftWriter(client)

    draft = writer.compose(make_thread(), make_decision(PromotionMode.PLAIN_MENTION))

    assert draft is not None
    assert client.messages is not None
    user_prompt = client.messages[-1].content
    assert "Aim for 20-40 words. Hard cap: 45 words." in user_prompt
    assert "DO NOT default to ending with a question" in user_prompt
    assert "Product mentions are optional unless promotion mode is disclosed_monetized." in user_prompt
    assert "mention PromptHunt only if it directly improves the answer" in user_prompt


def test_compose_falls_back_to_heuristic_when_llm_fails():
    writer = DraftWriter(FailingLLMClient())

    draft = writer.compose(make_thread(), make_decision(PromotionMode.PLAIN_MENTION))

    assert draft is not None
    assert "PromptHunt could be relevant" in draft.body
    assert draft.disclosure_text is None


def test_compose_rejects_llm_output_over_four_sentences_and_falls_back():
    writer = DraftWriter(StubLLMClient("Save the prompt with notes. Keep the model name. Track the output. Add reuse context. Review it later."))

    draft = writer.compose(make_thread(), make_decision(PromotionMode.NONE))

    assert draft is not None
    assert draft.body != "Save the prompt with notes. Keep the model name. Track the output. Add reuse context. Review it later."
    # Fell back to heuristic — verify it returned the heuristic body shape, not the LLM output
    assert "workflow" in draft.body.lower() or "prompt" in draft.body.lower()


def test_compose_rejects_llm_output_over_word_limit_and_falls_back():
    long_reply = (
        "A practical way to handle this is to create a detailed prompt archive with the exact prompt, model name, output quality notes, "
        "project context, reuse tags, failure cases, examples, owner notes, revision history, source links, expected output style, date tested, "
        "team ownership, category labels, screenshots, benchmark examples, rejected variants, naming rules, workspace folders, access notes, "
        "approval status, review cadence, prompt owner, handoff notes, audience notes, tone constraints, formatting rules, project goals, "
        "and a long explanation of why every version worked or failed so future experiments can be reviewed carefully."
    )
    writer = DraftWriter(StubLLMClient(long_reply))

    draft = writer.compose(make_thread(), make_decision(PromotionMode.NONE))

    assert draft is not None
    assert draft.body != long_reply
    assert len(draft.body.split()) <= 85


def test_plain_mention_accepts_helpful_reply_without_product():
    body = "A practical fix is to save each prompt with result notes and reuse context so the useful versions are easier to find later. What part gets lost most often?"
    writer = DraftWriter(StubLLMClient(body))

    draft = writer.compose(make_thread(), make_decision(PromotionMode.PLAIN_MENTION))

    assert draft is not None
    assert draft.body == body
    assert "PromptHunt" not in draft.body
    assert draft.disclosure_text is None


def test_plain_mention_fallback_omits_product_for_weak_fit_thread():
    writer = DraftWriter(FailingLLMClient())

    draft = writer.compose(make_weak_fit_thread(), make_decision(PromotionMode.PLAIN_MENTION))

    assert draft is not None
    assert "PromptHunt" not in draft.body
    # Question appearance is now probabilistic (~25% by stable hash of thread_id),
    # so we only assert the product mention is absent for weak-fit threads.


def test_plain_mention_fallback_includes_product_for_strong_prompt_library_fit():
    writer = DraftWriter(FailingLLMClient())

    draft = writer.compose(make_thread(), make_decision(PromotionMode.PLAIN_MENTION))

    assert draft is not None
    assert "PromptHunt could be relevant" in draft.body
    # Question appearance is now probabilistic (~25% by stable hash of thread_id),
    # so we don't assert a specific follow-up question.


def test_compose_logs_and_falls_back_when_llm_raises(caplog):
    writer = DraftWriter(FailingLLMClient())

    with caplog.at_level("WARNING"):
        draft = writer.compose(make_thread(), make_decision(PromotionMode.PLAIN_MENTION))

    assert draft is not None
    assert "PromptHunt could be relevant" in draft.body
    assert caplog.records
    record = caplog.records[-1]
    assert record.message == "LLM generation failed; using heuristic fallback"
    assert record.exception_type == "RuntimeError"
    assert record.exception_message == "boom"
    assert record.thread_id == "thread-1"
    assert record.subreddit == "PromptEngineering"
    assert record.exc_info is None
    assert "Traceback" not in caplog.text
    assert "RuntimeError: boom" not in caplog.text


def test_compose_logs_traceback_when_enabled(monkeypatch, caplog):
    monkeypatch.setenv("OPENAI_LOG_TRACEBACKS", "true")
    get_settings.cache_clear()
    writer = DraftWriter(FailingLLMClient())

    with caplog.at_level("WARNING"):
        draft = writer.compose(make_thread(), make_decision(PromotionMode.PLAIN_MENTION))

    get_settings.cache_clear()
    assert draft is not None
    assert caplog.records
    record = caplog.records[-1]
    assert record.message == "LLM generation failed; using heuristic fallback"
    assert record.exc_info is not None
    assert "RuntimeError: boom" in caplog.text


def test_compose_logs_timeout_and_falls_back(caplog):
    writer = DraftWriter(TimeoutLLMClient())

    with caplog.at_level("WARNING"):
        draft = writer.compose(make_thread(), make_decision(PromotionMode.PLAIN_MENTION))

    assert draft is not None
    assert "PromptHunt could be relevant" in draft.body
    assert caplog.records
    record = caplog.records[-1]
    assert record.message == "LLM generation timed out; using heuristic fallback"
    assert record.exception_type == "TimeoutError"
    assert record.exception_message == "The read operation timed out"
    assert record.exc_info is None


def test_compose_appends_disclosure_for_monetized_mode():
    writer = DraftWriter(StubLLMClient("A good next step is to save prompts with outcome notes so you can compare versions and keep the useful ones."))

    draft = writer.compose(make_thread(), make_decision(PromotionMode.DISCLOSED_MONETIZED))

    assert draft is not None
    assert "PromptHunt" in draft.body
    assert draft.disclosure_text == "Disclosure: I'm affiliated with PromptHunt."
    assert draft.body.endswith("Disclosure: I'm affiliated with PromptHunt.")


def test_monetized_fallback_drops_question_to_preserve_disclosure_and_brevity():
    writer = DraftWriter(FailingLLMClient())

    draft = writer.compose(make_thread(), make_decision(PromotionMode.DISCLOSED_MONETIZED))

    assert draft is not None
    assert "PromptHunt" in draft.body
    assert "Disclosure: I'm affiliated with PromptHunt." in draft.body
    assert "?" not in draft.body
    assert DraftWriter()._sentence_count(draft.body) <= 4


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
