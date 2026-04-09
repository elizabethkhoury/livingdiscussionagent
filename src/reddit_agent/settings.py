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
    posthog_api_key: str | None = None
    posthog_host: str = 'https://app.posthog.com'
    reddit_client_id: str | None = None
    reddit_client_secret: str | None = None
    reddit_user_agent: str = 'PromptHuntAgent/2.0'
    llm_mode: str = 'mock'
    generation_model: str = 'claude-opus-4-1'
    evaluator_model: str = 'gpt-5.4-mini'
    dashboard_api_origin: str = 'http://localhost:8000'
    config_dir: Path = Field(default_factory=lambda: Path('config/rules'))


@lru_cache
def get_settings():
    return Settings()
