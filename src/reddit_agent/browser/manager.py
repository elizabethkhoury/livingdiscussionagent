from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from reddit_agent.settings import Settings


@dataclass(slots=True)
class KernelBrowserHandle:
    session_id: str
    cdp_ws_url: str
    browser_live_view_url: str | None
    persist_profile: bool


class KernelBrowserManager:
    def __init__(self, settings: Settings):
        self.settings = settings

    def _kernel_client(self):
        try:
            from kernel import Kernel
        except ImportError as exc:  # pragma: no cover - exercised only with runtime deps installed
            raise RuntimeError(
                'Kernel SDK is not installed. Add the `kernel` package before using browser flows.'
            ) from exc
        if not self.settings.kernel_api_key:
            return Kernel()
        try:
            return Kernel(api_key=self.settings.kernel_api_key)
        except TypeError:  # pragma: no cover - depends on SDK signature
            return Kernel(apiKey=self.settings.kernel_api_key)

    async def ensure_profile(self):
        profile_name = self.settings.kernel_profile_name
        profile_id = self.settings.kernel_profile_id
        if profile_id or not profile_name:
            return

        def _create_profile():
            kernel = self._kernel_client()
            try:
                kernel.profiles.create({'name': profile_name})
            except Exception as exc:  # pragma: no cover - API behavior depends on Kernel SDK
                if 'conflict' not in str(exc).lower() and 'already exists' not in str(exc).lower():
                    raise

        await asyncio.to_thread(_create_profile)

    def _profile_payload(self):
        if self.settings.kernel_profile_id:
            return {'id': self.settings.kernel_profile_id}
        if self.settings.kernel_profile_name:
            return {'name': self.settings.kernel_profile_name}
        return None

    async def create_browser(self, *, persist_profile: bool):
        await self.ensure_profile()

        def _create():
            kernel = self._kernel_client()
            payload: dict[str, Any] = {
                'headless': self.settings.kernel_headless,
                'stealth': True,
                'timeout_seconds': self.settings.kernel_browser_timeout_seconds,
                'viewport': {'width': 1280, 'height': 900},
            }
            profile = self._profile_payload()
            if profile:
                if persist_profile:
                    profile['save_changes'] = True
                payload['profile'] = profile
            browser = kernel.browsers.create(payload)
            return KernelBrowserHandle(
                session_id=browser.session_id,
                cdp_ws_url=browser.cdp_ws_url,
                browser_live_view_url=getattr(browser, 'browser_live_view_url', None),
                persist_profile=persist_profile,
            )

        return await asyncio.to_thread(_create)

    async def delete_browser(self, session_id: str):
        def _delete():
            kernel = self._kernel_client()
            delete = getattr(kernel.browsers, 'delete_by_id', None) or getattr(
                kernel.browsers, 'deleteByID', None
            )
            if delete is None:  # pragma: no cover - defensive for SDK drift
                raise RuntimeError('Kernel SDK does not expose a browser delete method.')
            delete(session_id)

        await asyncio.to_thread(_delete)
