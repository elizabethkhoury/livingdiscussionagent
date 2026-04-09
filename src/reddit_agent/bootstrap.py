from functools import lru_cache

from reddit_agent.clients.reddit import RedditClient
from reddit_agent.providers.mock_llm import MockLLMProvider
from reddit_agent.rules import load_lifecycle_rules, load_product_rules, load_subreddit_rules
from reddit_agent.settings import get_settings


@lru_cache
def get_runtime():
    settings = get_settings()
    return {
        'settings': settings,
        'reddit_client': RedditClient(
            client_id=settings.reddit_client_id,
            client_secret=settings.reddit_client_secret,
            user_agent=settings.reddit_user_agent,
        ),
        'llm_provider': MockLLMProvider(),
        'subreddit_rules': load_subreddit_rules(settings.config_dir),
        'product_rules': load_product_rules(settings.config_dir),
        'lifecycle_rules': load_lifecycle_rules(settings.config_dir),
    }
