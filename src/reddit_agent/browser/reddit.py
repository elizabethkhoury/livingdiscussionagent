from __future__ import annotations

from datetime import UTC, datetime

from reddit_agent.browser.agent import RedditBrowserAgent
from reddit_agent.browser.manager import KernelBrowserManager
from reddit_agent.browser.session import open_reddit_browser_session
from reddit_agent.settings import Settings


class RedditBrowserDiscovery:
    def __init__(
        self,
        manager: KernelBrowserManager,
        agent: RedditBrowserAgent,
        settings: Settings,
    ):
        self.manager = manager
        self.agent = agent
        self.settings = settings

    async def fetch_new_posts(self, subreddit: str):
        results = []
        async with open_reddit_browser_session(
            self.manager, self.agent, persist_profile=False
        ) as session:
            await session.open_subreddit_new(subreddit)
            cards = await session.list_thread_cards(self.settings.reddit_discovery_thread_limit)
            for card in cards:
                await session.open_thread(card['permalink'])
                extracted = await session.extract_thread(subreddit)
                if not extracted['title']:
                    extracted['title'] = card['title']
                now = datetime.now(UTC)
                comment_snippets = extracted.pop('comment_snippets', [])
                results.append(
                    {
                        **extracted,
                        'freshness_hours': 0.0,
                        'browser_metadata': {
                            'session_id': session.session_id,
                            'live_view_url': session.live_view_url,
                            'extraction_timestamp': now.isoformat(),
                            'comment_snippets': comment_snippets[
                                : self.settings.reddit_discovery_comment_snippet_limit
                            ],
                            'extraction_mode': 'browser_agent',
                        },
                    }
                )
        return results


class RedditBrowserPoster:
    def __init__(
        self,
        manager: KernelBrowserManager,
        agent: RedditBrowserAgent,
    ):
        self.manager = manager
        self.agent = agent

    async def post_reply(self, *, permalink: str, body: str):
        async with open_reddit_browser_session(
            self.manager, self.agent, persist_profile=False
        ) as session:
            await session.open_thread(permalink)
            if await session.is_authentication_required():
                return {
                    'status': 'auth_required',
                    'diagnostics': await session.diagnostics(),
                }

            opened = await session.open_comment_composer()
            agent_result = None
            if not opened:
                agent_result = await session.recover_with_agent(
                    task=(
                        'Open the Reddit comment composer for the current thread. '
                        'Do not submit anything.'
                    )
                )
                opened = await session.open_comment_composer()
            if not opened:
                return {
                    'status': 'composer_not_found',
                    'diagnostics': {
                        **(await session.diagnostics()),
                        'agent_summary': agent_result.summary if agent_result else None,
                    },
                }

            await session.type_comment(body)
            await session.submit_comment()
            posted, comment_url = await session.confirm_comment_posted(body)
            diagnostics = await session.diagnostics()
            if posted:
                return {
                    'status': 'posted',
                    'comment_url': comment_url,
                    'diagnostics': diagnostics,
                }
            return {
                'status': 'unknown_result',
                'diagnostics': diagnostics,
            }
