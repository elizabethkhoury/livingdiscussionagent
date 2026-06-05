"""Booster transport — a lightweight Playwright session for the second Reddit account.

This is only used for upvoting. It:
  1. Launches a persistent Chrome context from chrome_profile_booster/ so login persists.
  2. Logs in as the booster account if not already logged in.
  3. Navigates to a thread on old.reddit.com and clicks upvote arrows.
  4. Closes the browser.

No posting, no reading, no drafts. Pure upvotes only.
"""

from __future__ import annotations

import logging
import os

from playwright.async_api import async_playwright

from src.app.settings import get_settings

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
)


class BoosterTransport:
    """Thin Playwright session for the booster account. Only upvotes, never posts."""

    def __init__(self):
        self.settings = get_settings()
        self.profile_dir = os.path.join(os.getcwd(), self.settings.chrome_profile_booster_dir)

    def is_configured(self) -> bool:
        return bool(self.settings.reddit_booster_username and self.settings.reddit_booster_password)

    async def upvote_items(self, thread_url: str, fullnames: list[str]) -> dict[str, str]:
        """Log in as the booster account and upvote each fullname (t1_X or t3_X).

        Args:
            thread_url: old.reddit.com URL of the thread (so the items are on the page).
            fullnames: list of Reddit fullnames to upvote, e.g. ['t3_abc', 't1_xyz'].

        Returns:
            dict mapping fullname -> result string ('upvoted', 'already_upvoted',
            'not_found', 'error', 'not_logged_in').
        """
        if not self.is_configured():
            return {fn: "not_configured" for fn in fullnames}

        results: dict[str, str] = {}
        try:
            async with async_playwright() as pw:
                context, page = await self._make_context(pw)
                logged_in = await self._ensure_logged_in(page)
                if not logged_in:
                    await context.close()
                    return {fn: "not_logged_in" for fn in fullnames}

                # Navigate to the thread so the items are present on the page.
                url = self._to_old_reddit(thread_url)
                await page.goto(url, wait_until="domcontentloaded", timeout=20000)
                await page.wait_for_timeout(2000)

                for fn in fullnames:
                    results[fn] = await self._click_upvote(page, fn)
                    await page.wait_for_timeout(1200)  # small gap between clicks

                await context.close()
        except Exception as exc:
            logger.warning("booster_transport error: %s", exc)
            for fn in fullnames:
                if fn not in results:
                    results[fn] = "error"
        return results

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _make_context(self, pw):
        os.makedirs(self.profile_dir, exist_ok=True)
        context = await pw.chromium.launch_persistent_context(
            self.profile_dir,
            headless=True,   # booster runs silently — no visible window
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
            user_agent=USER_AGENT,
            viewport={"width": 1280, "height": 900},
            locale="en-US",
            timezone_id="America/Los_Angeles",
        )
        await context.add_init_script(
            """
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'plugins', { get: () => [1,2,3,4,5] });
            Object.defineProperty(navigator, 'languages', { get: () => ['en-US','en'] });
            window.chrome = { runtime: {} };
            """
        )
        page = await context.new_page()
        return context, page

    async def _ensure_logged_in(self, page) -> bool:
        username = (self.settings.reddit_booster_username or "").lower()
        password = self.settings.reddit_booster_password or ""
        if not username or not password:
            return False

        # Check if already logged in via saved session.
        await page.goto("https://old.reddit.com/", wait_until="domcontentloaded", timeout=15000)
        await page.wait_for_timeout(2000)
        if await self._is_logged_in(page, username):
            logger.info("booster already logged in as %s", username)
            return True

        # Not logged in — perform login.
        logger.info("booster logging in as %s", username)
        await page.goto("https://old.reddit.com/login", wait_until="domcontentloaded", timeout=15000)
        await page.wait_for_timeout(1500)
        try:
            await page.fill("#user_login", username, timeout=5000)
            await page.fill("#passwd_login", password, timeout=5000)
            await page.wait_for_timeout(500)
            await page.click(".btn-primary", timeout=5000)
            await page.wait_for_timeout(3000)
        except Exception as exc:
            logger.warning("booster login failed: %s", exc)
            return False

        return await self._is_logged_in(page, username)

    async def _is_logged_in(self, page, username: str) -> bool:
        try:
            cookies = await page.context.cookies("https://www.reddit.com")
            cookie_names = {c.get("name", "") for c in cookies}
            if "reddit_session" not in cookie_names and "token_v2" not in cookie_names:
                return False
            html = (await page.content()).lower()
            return username.lower() in html
        except Exception:
            return False

    async def _click_upvote(self, page, fullname: str) -> str:
        """Click the upvote arrow for a fullname on old.reddit.com. Returns status string."""
        try:
            already = page.locator(
                f'.thing.id-{fullname} > .midcol > .arrow.upmod, '
                f'.thing[data-fullname="{fullname}"] > .midcol > .arrow.upmod'
            ).first
            if await already.count() > 0:
                return "already_upvoted"
            arrow = page.locator(
                f'.thing.id-{fullname} > .midcol > .arrow.up, '
                f'.thing[data-fullname="{fullname}"] > .midcol > .arrow.up'
            ).first
            if await arrow.count() == 0:
                return "not_found"
            await arrow.scroll_into_view_if_needed(timeout=3000)
            await arrow.click(timeout=3000)
            await page.wait_for_timeout(800)
            return "upvoted"
        except Exception as exc:
            logger.debug("click_upvote error fullname=%s err=%s", fullname, exc)
            return "error"

    @staticmethod
    def _to_old_reddit(url: str) -> str:
        """Ensure the URL uses old.reddit.com for CSS-selector compatibility."""
        return url.replace("www.reddit.com", "old.reddit.com").replace(
            "reddit.com/r/", "old.reddit.com/r/"
        ) if "old.reddit.com" not in url else url
