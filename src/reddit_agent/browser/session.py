from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from reddit_agent.browser.agent import BrowserAgentResult, RedditBrowserAgent
from reddit_agent.browser.manager import KernelBrowserHandle, KernelBrowserManager


class RedditBrowserSession:
    def __init__(
        self,
        manager: KernelBrowserManager,
        agent: RedditBrowserAgent,
        *,
        persist_profile: bool,
    ):
        self.manager = manager
        self.agent = agent
        self.persist_profile = persist_profile
        self.handle: KernelBrowserHandle | None = None
        self._playwright = None
        self._browser = None
        self.context = None
        self.page = None

    async def __aenter__(self):
        self.handle = await self.manager.create_browser(persist_profile=self.persist_profile)
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:  # pragma: no cover - exercised only with runtime deps installed
            raise RuntimeError(
                'Playwright is not installed. '
                'Add the `playwright` package before using browser flows.'
            ) from exc

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.connect_over_cdp(self.handle.cdp_ws_url)
        self.context = (
            self._browser.contexts[0]
            if self._browser.contexts
            else await self._browser.new_context()
        )
        self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if self._browser is not None:
            await self._browser.close()
        if self._playwright is not None:
            await self._playwright.stop()
        if self.handle is not None:
            await self.manager.delete_browser(self.handle.session_id)

    @property
    def live_view_url(self):
        return self.handle.browser_live_view_url if self.handle else None

    @property
    def session_id(self):
        return self.handle.session_id if self.handle else None

    async def open_subreddit_new(self, subreddit: str):
        await self.page.goto(
            f'https://www.reddit.com/r/{subreddit}/new/', wait_until='domcontentloaded'
        )
        await self.page.wait_for_timeout(1500)

    async def list_thread_cards(self, limit: int):
        cards = await self.page.evaluate(
            """(limit) => {
                const anchors = Array.from(document.querySelectorAll('a[href*="/comments/"]'));
                const seen = new Set();
                const results = [];
                for (const anchor of anchors) {
                    const href = anchor.getAttribute('href');
                    if (!href || seen.has(href) || href.includes('/comments') === false) continue;
                    const text = (anchor.textContent || '').trim();
                    if (!text) continue;
                    seen.add(href);
                    results.push({
                        title: text,
                        permalink: href.startsWith('http') ? href : `https://www.reddit.com${href}`,
                    });
                    if (results.length >= limit) break;
                }
                return results;
            }""",
            limit,
        )
        return cards

    async def open_thread(self, permalink: str):
        await self.page.goto(permalink, wait_until='domcontentloaded')
        await self.page.wait_for_timeout(1500)

    async def extract_thread(self, subreddit: str):
        payload = await self.page.evaluate(
            """() => {
                const title = document.querySelector('h1')?.textContent?.trim() || '';
                const bodyNodes = document.querySelectorAll(
                    'shreddit-post, article, [data-test-id="post-content"] p'
                );
                const body = Array.from(bodyNodes)
                    .map((node) => node.textContent?.trim() || '')
                    .filter(Boolean)
                    .join('\\n')
                    .slice(0, 8000);
                const commentNodes = document.querySelectorAll(
                    '[data-testid="comment"], shreddit-comment'
                );
                const commentSnippets = Array.from(commentNodes)
                    .map((node) => (node.textContent || '').trim())
                    .filter((text) => text.length > 20)
                    .slice(0, 5);
                const canonical =
                    document.querySelector('link[rel="canonical"]')?.getAttribute('href') ||
                    window.location.href;
                const postID = canonical.match(/comments\\/([^/]+)/)?.[1] || '';
                const authorNode = document.querySelector(
                    'a[data-testid="post_author_link"], shreddit-post a[href*="/user/"]'
                );
                const author = authorNode?.textContent?.trim() || null;
                const commentsMatch = document.body.innerText.match(
                    /(\\d+[.,]?\\d*)\\s+comments?/i
                );
                const commentsText = commentsMatch?.[1] || '0';
                const normalizedComments =
                    Number.parseInt(String(commentsText).replace(/[^0-9]/g, ''), 10) || 0;
                return {
                    title,
                    body,
                    permalink: canonical,
                    reddit_post_id: postID,
                    author,
                    num_comments: normalizedComments,
                    comment_snippets: commentSnippets,
                };
            }"""
        )
        return {
            **payload,
            'subreddit': subreddit,
            'source_kind': 'post',
        }

    async def diagnostics(self):
        title = await self.page.title()
        url = self.page.url
        return {
            'page_title': title,
            'current_url': url,
            'session_id': self.session_id,
            'live_view_url': self.live_view_url,
        }

    async def is_authentication_required(self):
        text = (await self.page.locator('body').inner_text()).lower()
        return 'log in' in text or 'sign up' in text or 'continue with email' in text

    async def open_comment_composer(self):
        selectors = [
            'button:has-text("Comment")',
            'button:has-text("Reply")',
            '[data-testid="comment-composer"]',
            'shreddit-comment-composer',
        ]
        for selector in selectors:
            locator = self.page.locator(selector).first
            try:
                await locator.click(timeout=2000)
                await self.page.wait_for_timeout(800)
                if await self._editor_visible():
                    return True
            except Exception:
                continue
        return False

    async def _editor_visible(self):
        editors = self.page.locator('[contenteditable="true"], textarea')
        return await editors.count() > 0

    async def type_comment(self, body: str):
        locator = self.page.locator('[contenteditable="true"], textarea').last
        await locator.click(timeout=2000)
        try:
            await locator.fill(body)
        except Exception:
            await self.page.keyboard.press('Control+a')
            await self.page.keyboard.type(body, delay=10)
        await self.page.wait_for_timeout(500)

    async def submit_comment(self):
        buttons = [
            'button:has-text("Comment")',
            'button:has-text("Reply")',
            'button:has-text("Save")',
        ]
        for selector in buttons:
            locator = self.page.locator(selector).last
            try:
                await locator.click(timeout=2000)
                await self.page.wait_for_timeout(2000)
                return
            except Exception:
                continue
        await self.page.keyboard.press('Control+Enter')
        await self.page.wait_for_timeout(2000)

    async def confirm_comment_posted(self, body: str):
        snippet = body.strip()[:80]
        if not snippet:
            return False, None
        text = await self.page.locator('body').inner_text()
        if snippet in text:
            return True, self.page.url
        return False, None

    async def recover_with_agent(self, *, task: str):
        if self.handle is None:
            return BrowserAgentResult(ok=False, summary='No active browser session.')
        return await self.agent.recover(cdp_ws_url=self.handle.cdp_ws_url, task=task)


@asynccontextmanager
async def open_reddit_browser_session(
    manager: KernelBrowserManager,
    agent: RedditBrowserAgent,
    *,
    persist_profile: bool,
) -> AsyncIterator[RedditBrowserSession]:
    session = RedditBrowserSession(manager, agent, persist_profile=persist_profile)
    await session.__aenter__()
    try:
        yield session
    finally:
        await session.__aexit__(None, None, None)
