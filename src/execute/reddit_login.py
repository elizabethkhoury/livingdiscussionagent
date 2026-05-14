from __future__ import annotations

import asyncio
import os

from playwright.async_api import async_playwright

from src.app.settings import get_settings

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
)


async def launch_login_session() -> dict:
    settings = get_settings()
    profile_dir = os.path.join(os.getcwd(), settings.chrome_profile_dir)
    os.makedirs(profile_dir, exist_ok=True)

    print(f"Profile dir: {profile_dir}")
    print("Opening Chromium. Log in to Reddit manually (handle any captcha or 2FA).")
    print("When you see your username in the top-right, you can close the window.")

    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            profile_dir,
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
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto("https://www.reddit.com/login", wait_until="domcontentloaded")

        close_event = asyncio.Event()
        context.on("close", lambda *_: close_event.set())
        await close_event.wait()

    print("Browser closed. Cookies are persisted in the profile directory.")
    return {"status": "ok", "command": "reddit-login", "profile_dir": profile_dir}
