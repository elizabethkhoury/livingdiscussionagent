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

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
)


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
        try:
            async with async_playwright() as playwright:
                context, page = await self._make_context(playwright)
                if not await self._ensure_logged_in(page):
                    await context.close()
                    self._record_event("login_required", {"draft_id": draft_id})
                    return self._finish_attempt(attempt_id, "failed", error_message="not_logged_in")
                posted_comment_id = await self._post_comment(
                    page=page,
                    post_url=post_url,
                    reply_text=reply_text,
                    target_comment_id=target_comment_id,
                )
                if posted_comment_id:
                    attempt = self._finish_attempt(attempt_id, "posted", posted_comment_id=posted_comment_id)
                else:
                    self._write_failure_snapshot(draft_id, await page.content())
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
        suffix = "html" if "<html" in (error_message or "").lower() else "txt"
        timestamp = int(time.time())
        path = snapshot_dir / f"draft_{draft_id}_{timestamp}.{suffix}"
        path.write_text(error_message or "")

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

    async def _ensure_logged_in(self, page) -> bool:
        await page.goto("https://www.reddit.com/", wait_until="domcontentloaded")
        await page.wait_for_timeout(2500)
        return await self._is_logged_in(page)

    async def _is_logged_in(self, page) -> bool:
        username = (self.settings.reddit_username or "").lower()
        if not username:
            return False
        cookies = await page.context.cookies("https://www.reddit.com")
        cookie_names = {c.get("name", "") for c in cookies}
        if "reddit_session" not in cookie_names and "token_v2" not in cookie_names:
            return False
        try:
            indicator = await page.evaluate(
                """(uname) => {
                    const lower = uname.toLowerCase();
                    const links = Array.from(document.querySelectorAll('a[href]'));
                    if (links.some(a => (a.getAttribute('href') || '').toLowerCase() === '/user/' + lower
                        || (a.getAttribute('href') || '').toLowerCase() === '/user/' + lower + '/')) return true;
                    const html = document.documentElement.innerHTML.toLowerCase();
                    if (html.includes('"' + lower + '"') && html.includes('logged-in')) return true;
                    return false;
                }""",
                username,
            )
        except Exception:
            indicator = False
        return bool(indicator)

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

    async def _wait_for_editor(self, page, timeout_ms: int = 10000):
        deadline = time.time() + timeout_ms / 1000
        while time.time() < deadline:
            coords = await page.evaluate(
                """() => {
                    const results = [];
                    const seen = new WeakSet();
                    function walk(root) {
                        if (!root || seen.has(root)) return;
                        seen.add(root);
                        const editable = root.querySelectorAll
                            ? root.querySelectorAll('[contenteditable="true"]')
                            : [];
                        for (const el of editable) {
                            const rect = el.getBoundingClientRect();
                            if (rect.width > 80 && rect.height > 10 && rect.bottom > 0 && rect.top < window.innerHeight + 100) {
                                results.push({ x: rect.left + rect.width / 2, y: rect.top + rect.height / 2, top: rect.top });
                            }
                        }
                        const all = root.querySelectorAll ? root.querySelectorAll('*') : [];
                        for (const el of all) {
                            if (el.shadowRoot) walk(el.shadowRoot);
                        }
                    }
                    walk(document);
                    return results;
                }"""
            )
            if coords:
                return sorted(coords, key=lambda item: item["top"])[0]
            await page.wait_for_timeout(300)
        return None

    async def _open_post_composer(self, page):
        coords = None
        for attempt in range(8):
            await page.wait_for_timeout(800)
            coords = await page.evaluate(
                """() => {
                    const trigger = document.querySelector('faceplate-textarea-input[data-testid="trigger-button"]')
                        || document.querySelector('[data-testid="trigger-button"]');
                    if (!trigger) return null;
                    trigger.scrollIntoView({block: 'center'});
                    let inner = null;
                    if (trigger.shadowRoot) inner = trigger.shadowRoot.querySelector('textarea, [contenteditable]');
                    const target = inner || trigger;
                    const r = target.getBoundingClientRect();
                    if (r.width < 20 || r.height < 5) return null;
                    return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
                }"""
            )
            if coords:
                break
        if coords:
            await page.mouse.click(coords["x"], coords["y"])
            await page.wait_for_timeout(2500)
            editor = await self._wait_for_editor(page)
            if editor:
                return editor
            await page.mouse.click(coords["x"], coords["y"])
            await page.wait_for_timeout(2500)
            editor = await self._wait_for_editor(page)
            if editor:
                return editor
        for selector in [
            'shreddit-composer [contenteditable]',
            '[contenteditable="true"]',
            'textarea[placeholder*="Join the conversation"]',
            'textarea[placeholder*="comment"]',
            '[data-testid="comment-composer"] [contenteditable]',
        ]:
            try:
                locator = page.locator(selector).first
                await locator.scroll_into_view_if_needed(timeout=2000)
                await locator.click(timeout=2000)
                await page.wait_for_timeout(1500)
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

    async def _type_and_submit(self, page, editor_coords, text: str) -> bool:
        recentered = await page.evaluate(
            """() => {
                const seen = new WeakSet();
                function find(root, depth=0) {
                    if (!root || seen.has(root) || depth > 8) return null;
                    seen.add(root);
                    if (root.querySelectorAll) {
                        for (const el of root.querySelectorAll('[contenteditable=\"true\"]')) {
                            const r = el.getBoundingClientRect();
                            if (r.width > 80 && r.height > 10) return el;
                        }
                        for (const el of root.querySelectorAll('*')) {
                            if (el.shadowRoot) { const found = find(el.shadowRoot, depth+1); if (found) return found; }
                        }
                    }
                    return null;
                }
                const editor = find(document);
                if (!editor) return null;
                editor.scrollIntoView({block: 'center'});
                editor.focus();
                const r = editor.getBoundingClientRect();
                return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
            }"""
        )
        coords = recentered or editor_coords
        await page.mouse.click(coords["x"], coords["y"])
        await page.wait_for_timeout(300)
        modifier = "Meta" if self._is_mac() else "Control"
        await page.keyboard.press(f"{modifier}+a")
        await page.keyboard.press("Delete")
        clean = text.strip().replace("\n", " ")
        await page.keyboard.type(clean, delay=22)
        if await self._check_rate_limit(page):
            return False
        await page.keyboard.press(f"{modifier}+Enter")
        await page.wait_for_timeout(3500)
        return True

    @staticmethod
    def _is_mac() -> bool:
        import platform

        return platform.system() == "Darwin"

    async def _verify_posted(self, page, reply_text: str) -> str | None:
        username = (self.settings.reddit_username or "").lower()
        if not username:
            return None
        snippet = reply_text.strip().split("\n", 1)[0][:60].lower()
        for _ in range(6):
            comment_id = await page.evaluate(
                """({uname, snippet}) => {
                    // Old reddit: div.thing.comment with a.author
                    for (const n of document.querySelectorAll('div.thing.comment')) {
                        const a = n.querySelector('a.author');
                        if (!a) continue;
                        if (a.textContent.trim().toLowerCase() !== uname) continue;
                        const md = n.querySelector('.entry .md');
                        const text = (md ? md.innerText : n.innerText || '').toLowerCase();
                        if (text.includes(snippet)) {
                            const dn = n.getAttribute('data-fullname') || '';
                            if (dn) return dn;
                            const id = n.id || '';
                            return id.replace('thing_', '') || 'verified';
                        }
                    }
                    // New reddit fallback
                    for (const n of document.querySelectorAll('shreddit-comment, [data-testid=\"comment\"]')) {
                        const author = (n.getAttribute('author') || n.querySelector('[data-testid=\"comment_author_link\"]')?.textContent || '').toLowerCase();
                        if (author.replace('u/', '').trim() !== uname) continue;
                        const text = (n.innerText || '').toLowerCase();
                        if (text.includes(snippet)) {
                            return n.getAttribute('thingid') || n.getAttribute('id') || n.getAttribute('data-fullname') || 'verified';
                        }
                    }
                    return null;
                }""",
                {"uname": username, "snippet": snippet},
            )
            if comment_id:
                return comment_id
            await page.wait_for_timeout(1000)
        return None

    def _comment_permalink(self, post_url: str, target_comment_id: str):
        base_url = post_url.split("#", 1)[0].split("?", 1)[0].rstrip("/")
        if base_url.endswith(f"/{target_comment_id}") or base_url.endswith(f"/t1_{target_comment_id}"):
            return f"{base_url}/"
        return f"{base_url}/{target_comment_id}/"

    async def _post_comment(self, page, post_url: str, reply_text: str, target_comment_id: str | None = None) -> str | None:
        return await self._post_comment_old_reddit(page, post_url, reply_text, target_comment_id)

    @staticmethod
    def _to_old_reddit(url: str) -> str:
        return (
            url.replace("https://www.reddit.com", "https://old.reddit.com")
            .replace("https://reddit.com", "https://old.reddit.com")
            .replace("http://www.reddit.com", "https://old.reddit.com")
        )

    async def _post_comment_old_reddit(self, page, post_url: str, reply_text: str, target_comment_id: str | None = None) -> str | None:
        target_url = self._comment_permalink(post_url, target_comment_id) if target_comment_id else post_url
        target_url = self._to_old_reddit(target_url)
        await page.goto(target_url, wait_until="domcontentloaded")
        await page.wait_for_timeout(2500)
        if await self._check_rate_limit(page):
            return None
        clean = reply_text.strip().replace("\n", " ")

        if target_comment_id:
            cid = target_comment_id if target_comment_id.startswith("t1_") else f"t1_{target_comment_id}"
            reply_link = None
            for selector in (
                f'div#thing_{cid} li.reply > a',
                f'div#thing_{cid} a.access-required[data-event-action="comment"]',
                f'div#thing_{cid} a.reply-link',
                f'div[data-fullname="{cid}"] li.reply > a',
                f'div[data-fullname="{cid}"] a.access-required[data-event-action="comment"]',
            ):
                try:
                    candidate = page.locator(selector).first
                    await candidate.scroll_into_view_if_needed(timeout=3000)
                    await candidate.click(timeout=3000)
                    reply_link = candidate
                    break
                except Exception:
                    continue
            if reply_link is None:
                return None
            await page.wait_for_timeout(1500)
            textarea = page.locator(f'div#thing_{cid} textarea[name="text"]:visible, div[data-fullname="{cid}"] textarea[name="text"]:visible').first
            save_button = page.locator(f'div#thing_{cid} button.save:visible, div[data-fullname="{cid}"] button.save:visible').first
        else:
            textarea = page.locator('div.commentarea form.usertext textarea[name="text"]').first
            save_button = page.locator('div.commentarea form.usertext button.save').first

        try:
            await textarea.scroll_into_view_if_needed(timeout=4000)
            await textarea.fill(clean, timeout=4000)
            await page.wait_for_timeout(500)
            await save_button.scroll_into_view_if_needed(timeout=2000)
            await save_button.click(timeout=4000)
        except Exception:
            return None

        await page.wait_for_timeout(3500)
        if await self._check_rate_limit(page):
            return None
        verified_comment_id = await self._verify_posted(page, reply_text)
        if verified_comment_id:
            try:
                thread_id = self._extract_thread_id(post_url)
                await self._upvote_after_post(page, thread_id, target_comment_id)
            except Exception as exc:  # pragma: no cover - upvote is best-effort
                self._record_event("upvote_error", {"error": str(exc)[:200]})
        return verified_comment_id

    @staticmethod
    def _extract_thread_id(post_url: str) -> str | None:
        """Extract the t3 thread ID from a Reddit post URL.

        e.g. 'https://old.reddit.com/r/SUB/comments/abc123/foo/' -> 'abc123'
        """
        try:
            parts = post_url.split("/comments/", 1)
            if len(parts) < 2:
                return None
            return parts[1].split("/", 1)[0]
        except Exception:
            return None

    async def _upvote_after_post(self, page, thread_id: str | None, target_comment_id: str | None) -> None:
        """Upvote the post and (optionally) the target comment we just replied to.

        Best-effort — failures here don't fail the original post. A real user
        often upvotes a post they found worth replying to, and Reddit
        auto-upvotes our own comment so we don't need to click that.
        """
        results = {"post": None, "target_comment": None}

        # Upvote the post (t3_)
        if thread_id:
            results["post"] = await self._click_upvote(page, f"t3_{thread_id}")

        # Upvote the parent comment we're replying to (if any)
        if target_comment_id:
            cid = target_comment_id if target_comment_id.startswith("t1_") else f"t1_{target_comment_id}"
            results["target_comment"] = await self._click_upvote(page, cid)

        self._record_event("upvote_attempt", {"thread_id": thread_id, "target_comment_id": target_comment_id, "result": results})

    async def _click_upvote(self, page, fullname: str) -> str:
        """Click the upvote arrow for a thing (t1_X or t3_X). Returns status string.

        Returns 'already_upvoted', 'upvoted', 'not_found', or 'error'.
        """
        try:
            # Check if already upvoted (presence of .arrow.upmod)
            already = page.locator(f'.thing.id-{fullname} > .midcol > .arrow.upmod, .thing[data-fullname="{fullname}"] > .midcol > .arrow.upmod').first
            if await already.count() > 0:
                return "already_upvoted"
            # Click the un-voted up arrow
            arrow = page.locator(f'.thing.id-{fullname} > .midcol > .arrow.up, .thing[data-fullname="{fullname}"] > .midcol > .arrow.up').first
            if await arrow.count() == 0:
                return "not_found"
            await arrow.scroll_into_view_if_needed(timeout=2500)
            await arrow.click(timeout=2500)
            await page.wait_for_timeout(800)
            return "upvoted"
        except Exception:
            return "error"
