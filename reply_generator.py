from src.classify.pipeline import ClassificationPipeline
from src.decide.engine import RuleBasedDecisionEngine
from src.domain.models import RedditCommentCandidate, RedditPostCandidate, ThreadContext
from src.generate.draft_writer import DraftWriter


def generate_reply(post_title: str, post_body: str, comment_text: str, subreddit: str):
    post = RedditPostCandidate(
        platform_thread_id="legacy",
        subreddit=subreddit,
        title=post_title,
        body=post_body,
        url="https://example.com",
    )
    target_comment = None
    if comment_text:
        target_comment = RedditCommentCandidate(
            platform_comment_id="legacy-comment",
            author="legacy",
            body=comment_text,
        )
    thread = ThreadContext(post=post, target_comment=target_comment)
    classification = ClassificationPipeline().classify(thread)
    decision = RuleBasedDecisionEngine().decide(thread, classification)
    draft = DraftWriter().compose(thread, decision)
    return draft.body if draft else None
