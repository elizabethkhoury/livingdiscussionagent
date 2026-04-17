from src.classify.pipeline import ClassificationPipeline
from src.domain.models import RedditPostCandidate, ThreadContext


def is_relevant(post_text: str, threshold: float = 0.65):
    placeholder = RedditPostCandidate(
        platform_thread_id="legacy",
        subreddit="legacy",
        title=post_text,
        body="",
        url="https://example.com",
    )
    result = ClassificationPipeline().classify(ThreadContext(post=placeholder))
    return result.relevance_score >= threshold
