from src.domain.enums import SubredditPromoPolicy

DEFAULT_RULES = {
    "PromptEngineering": SubredditPromoPolicy.REVIEW_ONLY,
    "OpenAI": SubredditPromoPolicy.REVIEW_ONLY,
    "ClaudeAI": SubredditPromoPolicy.REVIEW_ONLY,
    "SideProject": SubredditPromoPolicy.DENY,
    "sideprojects": SubredditPromoPolicy.DENY,
    "buildinpublic": SubredditPromoPolicy.DENY,
}


def subreddit_policy(subreddit: str):
    return DEFAULT_RULES.get(subreddit, SubredditPromoPolicy.ALLOW)
