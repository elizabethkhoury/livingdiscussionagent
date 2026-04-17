from src.classify.pipeline import ClassificationPipeline
from src.decide.engine import RuleBasedDecisionEngine
from src.domain.models import RedditPostCandidate, ThreadContext
from src.generate.draft_writer import DraftWriter
from src.generate.evaluators import DraftEvaluator


def score_reply(post_or_comment_text: str, reply_text: str):
    post = RedditPostCandidate(
        platform_thread_id="legacy",
        subreddit="legacy",
        title=post_or_comment_text,
        body="",
        url="https://example.com",
    )
    thread = ThreadContext(post=post)
    classification = ClassificationPipeline().classify(thread)
    decision = RuleBasedDecisionEngine().decide(thread, classification)
    draft = DraftWriter().compose(thread, decision)
    if draft is None:
        return 1
    draft.body = reply_text
    evaluation = DraftEvaluator().evaluate(thread, draft)
    return max(1, min(5, round(evaluation.overall_score * 5)))
