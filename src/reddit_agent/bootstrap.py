from functools import lru_cache

from reddit_agent.browser.agent import RedditBrowserAgent
from reddit_agent.browser.manager import KernelBrowserManager
from reddit_agent.browser.reddit import RedditBrowserDiscovery, RedditBrowserPoster
from reddit_agent.providers.mock_llm import MockLLMProvider
from reddit_agent.rules import load_lifecycle_rules, load_product_rules, load_subreddit_rules
from reddit_agent.services.dispatch import PostingDispatcher
from reddit_agent.services.posting import PostingService
from reddit_agent.settings import get_settings


@lru_cache
def get_runtime():
    settings = get_settings()
    kernel_browser_manager = KernelBrowserManager(settings)
    reddit_browser_agent = RedditBrowserAgent(settings)
    reddit_browser_poster = RedditBrowserPoster(kernel_browser_manager, reddit_browser_agent)
    posting_service = PostingService(reddit_browser_poster)
    return {
        'settings': settings,
        'kernel_browser_manager': kernel_browser_manager,
        'reddit_browser_agent': reddit_browser_agent,
        'reddit_browser_discovery': RedditBrowserDiscovery(
            kernel_browser_manager, reddit_browser_agent, settings
        ),
        'reddit_browser_poster': reddit_browser_poster,
        'posting_service': posting_service,
        'posting_dispatcher': PostingDispatcher(settings, posting_service),
        'llm_provider': MockLLMProvider(),
        'subreddit_rules': load_subreddit_rules(settings.config_dir),
        'product_rules': load_product_rules(settings.config_dir),
        'lifecycle_rules': load_lifecycle_rules(settings.config_dir),
    }
