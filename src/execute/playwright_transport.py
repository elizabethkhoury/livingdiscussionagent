from __future__ import annotations

import asyncio
import os
import re
import time
from pathlib import Path

from playwright.async_api import async_playwright

from src.app.settings import get_settings
from src.domain.models import PostAttempt
from src.storage.db import session_scope
from src.storage.repositories import DecisionRepository, LearningRepository

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"


class PlaywrightPostingTransport:
    def __init__(self):
        self.settings = get_settings()
        self.profile_dir = os.path.join(os.getcwd(), self.settings.chrome_profile_dir)

    async def publish(self, draft_id: int, attempt_id: int):
        with session_scope() as session:
            decisions = DecisionRepository(session)
            draft = decisions.get_draft(draft_id)
            if draft is None:
                raise ValueError(f"Unknown draft {draft_id}")
            classification = draft.decision.classification
            thread = classification.thread
            target_comment_id = classification.target_comment.platform_comment_id if classification.target_comment else None
            post_url = thread.url
            reply_text = draft.body
            posted_comment_id = f"{thread.platform_thread_id}-posted"
        try:
            async with async_playwright() as playwright:
                context, page = await self._make_context(playwright)
                await self._login(page)
                success = await self._post_comment(
                    page=page,
                    post_url=post_url,
                    reply_text=reply_text,
                    target_comment_id=target_comment_id,
                )
                if success:
                    attempt = self._finish_attempt(attempt_id, "posted", posted_comment_id=posted_comment_id)
                else:
                    attempt = self._finish_attempt(attempt_id, "failed", error_message="publish_failed")
                await context.close()
                return attempt
        except Exception as exc:  # pragma: no cover - browser/runtime integration
            self._record_event("playwright_error", {"draft_id": draft_id, "error": str(exc)})
            self._write_failure_snapshot(draft_id, str(exc))
            return self._finish_attempt(attempt_id, "failed", error_message=str(exc))

    def _finish_attempt(self, attempt_id: int, status: str, posted_comment_id: str | None = None, error_message: str | None = None):
        with session_scope() as session:
            decisions = DecisionRepository(session)
            record = decisions.finish_attempt(
                attempt_id=attempt_id,
                status=status,
                posted_comment_id=posted_comment_id,
                error_message=error_message,
            )
            return PostAttempt(
                attempt_id=record.id,
                draft_id=record.draft_id,
                transport=record.transport,
                status=record.status,
                posted_comment_id=record.posted_comment_id,
                error_message=record.error_message,
            )

    def _record_event(self, event_type: str, payload: dict):
        with session_scope() as session:
            LearningRepository(session).log_event(event_type, payload)

    def _write_failure_snapshot(self, draft_id: int, error_message: str):
        snapshot_dir = Path("runtime_failures")
        snapshot_dir.mkdir(exist_ok=True)
        path = snapshot_dir / f"draft_{draft_id}.txt"
        path.write_text(error_message)

    async def _make_context(self, playwright):
        os.makedirs(self.profile_dir, exist_ok=True)
        context = await playwright.chromium.launch_persistent_context(
            self.profile_dir,
            headless=False,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--start-maximized",
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

    async def _is_logged_in(self, page):
        content = await page.content()
        username = (self.settings.reddit_username or "").lower()
        return bool(username and username in content.lower())

    async def _login(self, page):
        await page.goto("https://www.reddit.com/", wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)
        if await self._is_logged_in(page):
            return
        await page.goto("https://www.reddit.com/login", wait_until="domcontentloaded")
        await page.wait_for_timeout(4000)
        if not self.settings.reddit_username or not self.settings.reddit_password:
            raise ValueError("Reddit credentials are required for Playwright publishing")
        await page.fill('input[name="username"]', self.settings.reddit_username)
        await page.fill('input[name="password"]', self.settings.reddit_password)
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(6000)

    async def _check_rate_limit(self, page):
        text = await page.inner_text("body")
        lower = text.lower()
        if "rate limit" in lower or "ratelimit" in lower:
            match = re.search(r"wait\\s+(\\d+)\\s+second", lower)
            wait_seconds = int(match.group(1)) if match else 120
            total = wait_seconds + 30
            self._record_event("rate_limit", {"wait_seconds": wait_seconds})
            await asyncio.sleep(total)
            return True
        return False

    async def _wait_for_editor(self, page, timeout_ms: int = 8000):
        deadline = time.time() + timeout_ms / 1000
        while time.time() < deadline:
            coords = await page.evaluate(
                """() => {
                    const results = [];
                    for (const el of document.querySelectorAll('[contenteditable="true"]')) {
                        const rect = el.getBoundingClientRect();
                        if (rect.width > 80 && rect.height > 10 && rect.top >= 0 && rect.top < 900) {
                            results.push({ x: rect.left + rect.width / 2, y: rect.top + rect.height / 2, top: rect.top });
                        }
                    }
                    return results;
                }"""
            )
            if coords:
                return sorted(coords, key=lambda item: item["top"])[-1]
            await page.wait_for_timeout(300)
        return None

    async def _open_post_composer(self, page):
        await page.evaluate("window.scrollTo(0, 0)")
        await page.wait_for_timeout(1000)
        for selector in [
            '[contenteditable="true"]',
            'textarea[placeholder*="comment"]',
            '[data-testid="comment-composer"] [contenteditable]',
        ]:
            try:
                locator = page.locator(selector).first
                await locator.scroll_into_view_if_needed(timeout=2000)
                await locator.click(timeout=2000)
                await page.wait_for_timeout(1000)
                editor = await self._wait_for_editor(page)
                if editor:
                    return editor
            except Exception:
                continue
        return None

    async def _open_reply_composer(self, page, target_comment_id: str):
        for selector in self._target_comment_selectors(target_comment_id):
            try:
                target = page.locator(selector).first
                await target.scroll_into_view_if_needed(timeout=3000)
                clicked = await target.evaluate(
                    """(node) => {
                        const buttons = Array.from(node.querySelectorAll('button'));
                        const reply = buttons.find((button) => {
                            const text = (button.innerText || button.textContent || '').trim().toLowerCase();
                            const aria = (button.getAttribute('aria-label') || '').trim().toLowerCase();
                            return text === 'reply' || aria === 'reply' || aria.includes('reply to comment');
                        });
                        if (!reply) {
                            return false;
                        }
                        reply.click();
                        return true;
                    }"""
                )
                if clicked:
                    await page.wait_for_timeout(1500)
                    editor = await self._wait_for_editor(page)
                    if editor:
                        return editor
            except Exception:
                continue
        return None

    def _target_comment_selectors(self, target_comment_id: str):
        comment_ids = [target_comment_id]
        if not target_comment_id.startswith("t1_"):
            comment_ids.append(f"t1_{target_comment_id}")
        selectors = []
        for comment_id in comment_ids:
            selectors.extend(
                [
                    f'shreddit-comment[thingid="{comment_id}"]',
                    f'[thingid="{comment_id}"]',
                    f'[id="{comment_id}"]',
                    f'[data-testid="comment"][id*="{comment_id}"]',
                    f'[data-fullname="{comment_id}"]',
                ]
            )
        return selectors

    async def _type_and_submit(self, page, editor_coords, text: str):
        await page.mouse.click(editor_coords["x"], editor_coords["y"])
        await page.keyboard.press("Control+a")
        await page.keyboard.press("Delete")
        clean = text.strip().replace("\n", " ")
        await page.keyboard.type(clean, delay=10)
        if await self._check_rate_limit(page):
            return False
        await page.keyboard.press("Control+Enter")
        await page.wait_for_timeout(2000)
        return True

    def _comment_permalink(self, post_url: str, target_comment_id: str):
        base_url = post_url.split("#", 1)[0].split("?", 1)[0].rstrip("/")
        if base_url.endswith(f"/{target_comment_id}") or base_url.endswith(f"/t1_{target_comment_id}"):
            return f"{base_url}/"
        return f"{base_url}/{target_comment_id}/"

    async def _post_comment(self, page, post_url: str, reply_text: str, target_comment_id: str | None = None):
        target_url = self._comment_permalink(post_url, target_comment_id) if target_comment_id else post_url
        await page.goto(target_url, wait_until="domcontentloaded")
        await page.wait_for_timeout(5000)
        if await self._check_rate_limit(page):
            return False
        editor = await self._open_reply_composer(page, target_comment_id) if target_comment_id else await self._open_post_composer(page)
        if not editor:
            return False
        return await self._type_and_submit(page, editor, reply_text)
