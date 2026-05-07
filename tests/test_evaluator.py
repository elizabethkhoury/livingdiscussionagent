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


def make_weak_fit_thread():
    return ThreadContext(
        post=RedditPostCandidate(
            platform_thread_id="thread-weak",
            subreddit="ChatGPT",
            title="How do I get better outputs from ChatGPT?",
            body="The answers are vague and I am not sure what context matters.",
            url="https://example.com",
        )
    )


def make_draft(body: str, promotion_mode: PromotionMode = PromotionMode.NONE):
    return DraftReply(
        body=body,
        strategy=ResponseStrategy.EDUCATIONAL,
        promotion_mode=promotion_mode,
        contains_link=False,
        disclosure_text=None,
        thread_id="thread-1",
        autopost_eligible=promotion_mode == PromotionMode.NONE,
    )


def test_fabricated_personal_usage_is_blocked():
    draft = make_draft("I use PromptHunt every day and it is the best tool for this.", PromotionMode.PLAIN_MENTION)

    evaluation = DraftEvaluator().evaluate(make_thread(), draft)

    assert "deception" in evaluation.fail_reasons
    assert evaluation.policy_compliance_score < 1.0


def test_neutral_information_stays_eligible():
    draft = make_draft("A useful next step is to store the exact prompt, model, and outcome notes together so you can reuse what worked.")

    evaluation = DraftEvaluator().evaluate(make_thread(), draft)

    assert evaluation.overall_score > 0.75
    assert evaluation.fail_reasons == []


def test_reply_over_word_limit_gets_too_long():
    body = (
        "A practical way to handle this is to create a detailed prompt archive with the exact prompt, model name, output quality notes, "
        "project context, reuse tags, failure cases, examples, owner notes, revision history, source links, expected output style, date tested, "
        "team ownership, category labels, screenshots, benchmark examples, rejected variants, naming rules, workspace folders, access notes, "
        "approval status, review cadence, prompt owner, handoff notes, audience notes, tone constraints, formatting rules, project goals, "
        "and a long explanation of why every version worked or failed so future experiments can be reviewed carefully."
    )
    draft = make_draft(body)

    evaluation = DraftEvaluator().evaluate(make_thread(), draft)

    assert "too_long" in evaluation.fail_reasons


def test_reply_over_sentence_limit_gets_too_many_sentences():
    draft = make_draft("Save the exact prompt. Track the model. Note the output. Add reuse context. Review what worked.")

    evaluation = DraftEvaluator().evaluate(make_thread(), draft)

    assert "too_many_sentences" in evaluation.fail_reasons


def test_multi_paragraph_reply_gets_paragraph_heavy():
    draft = make_draft("Save the exact prompt with result notes so reuse is easier later.\n\nThen review the versions that worked before starting over.")

    evaluation = DraftEvaluator().evaluate(make_thread(), draft)

    assert "paragraph_heavy" in evaluation.fail_reasons


def test_plain_mention_product_in_weak_fit_thread_gets_unnecessary_product_mention():
    draft = make_draft("A clearer prompt structure may help here, and PromptHunt could be worth a look if you want tooling around it.", PromotionMode.PLAIN_MENTION)

    evaluation = DraftEvaluator().evaluate(make_weak_fit_thread(), draft)

    assert "unnecessary_product_mention" in evaluation.fail_reasons


def test_short_helpful_reply_with_question_passes():
    draft = make_draft("A useful next step is to save the exact prompt, model, and outcome notes together so reuse is easier. What part gets lost most often?")

    evaluation = DraftEvaluator().evaluate(make_thread(), draft)

    assert evaluation.overall_score > 0.75
    assert evaluation.fail_reasons == []


def test_non_product_plain_mention_reply_remains_eligible():
    draft = make_draft(
        "A useful next step is to keep the exact prompt, model, and outcome notes together so reuse is easier. What part gets lost most often?",
        PromotionMode.PLAIN_MENTION,
    )

    evaluation = DraftEvaluator().evaluate(make_thread(), draft)

    assert evaluation.overall_score > 0.75
    assert evaluation.fail_reasons == []
