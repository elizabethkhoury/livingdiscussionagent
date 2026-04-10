from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore')

    app_env: str = 'development'
    database_url: str = 'sqlite+aiosqlite:///./reddit_agent.sqlite3'
    redis_url: str = 'redis://localhost:6379/0'
    temporal_target: str = 'localhost:7233'
    temporal_task_queue: str = 'reddit-agent'
    posthog_api_key: str | None = None
    posthog_host: str = 'https://app.posthog.com'
    reddit_user_agent: str = 'PromptHuntAgent/2.0'
    llm_mode: str = 'openai'
    generation_model: str = 'gpt-5.4'
    evaluator_model: str = 'gpt-5.4-mini'
    openai_api_key: str | None = None
    openai_base_url: str | None = None
    kernel_api_key: str | None = None
    kernel_profile_id: str | None = None
    kernel_profile_name: str | None = 'reddit-agent'
    kernel_browser_timeout_seconds: int = 120
    kernel_headless: bool = True
    browser_agent_model: str = 'gpt-5.4-mini'
    browser_agent_base_url: str | None = None
    browser_agent_api_key: str | None = None
    reddit_discovery_thread_limit: int = 10
    reddit_discovery_comment_snippet_limit: int = 3
    dashboard_api_origin: str = 'http://localhost:8000'
    config_dir: Path = Field(default_factory=lambda: Path('config/rules'))


@lru_cache
def get_settings():
    return Settings()
