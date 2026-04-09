from __future__ import annotations

from dataclasses import dataclass

from reddit_agent.settings import Settings


@dataclass(slots=True)
class BrowserAgentResult:
    ok: bool
    summary: str


class RedditBrowserAgent:
    def __init__(self, settings: Settings):
        self.settings = settings

    def _build_llm(self):
        try:
            from browser_use import ChatOpenAI
        except ImportError as exc:  # pragma: no cover - exercised only with runtime deps installed
            raise RuntimeError(
                'Browser Use is not installed. '
                'Add the `browser-use` package before using agent recovery.'
            ) from exc

        kwargs = {
            'model': self.settings.browser_agent_model,
            'api_key': self.settings.browser_agent_api_key,
        }
        if self.settings.browser_agent_base_url:
            kwargs['base_url'] = self.settings.browser_agent_base_url
        return ChatOpenAI(**kwargs)

    async def recover(self, *, cdp_ws_url: str, task: str):
        try:
            from browser_use import Agent, Browser
        except ImportError as exc:  # pragma: no cover - exercised only with runtime deps installed
            raise RuntimeError(
                'Browser Use is not installed. '
                'Add the `browser-use` package before using agent recovery.'
            ) from exc

        browser = Browser(
            cdp_url=cdp_ws_url,
            headless=self.settings.kernel_headless,
            window_size={'width': 1280, 'height': 900},
            viewport={'width': 1280, 'height': 900},
        )
        agent = Agent(task=task, browser=browser, llm=self._build_llm())
        history = await agent.run(max_steps=10)
        return BrowserAgentResult(ok=True, summary=str(history))
