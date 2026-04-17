from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_SUBREDDITS = [
    "PromptEngineering",
    "ChatGPTPromptEngineering",
    "aipromptprogramming",
    "promptdesign",
    "ClaudeAI",
    "ChatGPT",
    "OpenAI",
    "midjourney",
    "StableDiffusion",
    "AIAssistants",
    "cursor",
    "lovable",
    "CursorAI",
    "vibecoding",
    "VibeCodingSaaS",
    "vibecodersnest",
    "vibecodedevs",
    "nocode",
    "nocodesaas",
    "boltnewbuilders",
    "base44",
    "replit",
    "Lovable",
    "learnmachinelearning",
    "learnprogramming",
    "SideProject",
    "sideprojects",
    "microsaas",
    "indiehackers",
    "buildinpublic",
    "solopreneur",
]


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    dashboard_auth_secret: str = "local-dev-secret"
    autopost_enabled: bool = True
    llm_provider: str = "mistral"
    llm_api_key: str | None = Field(default=None, alias="MISTRAL_API_KEY")
    postgres_dsn: str = "postgresql+psycopg://localhost/prompthunt"
    reddit_username: str | None = Field(default=None, alias="REDDIT_USERNAME")
    reddit_password: str | None = Field(default=None, alias="REDDIT_PASSWORD")
    chrome_profile_dir: str = "chrome_profile"
    enabled_subreddits: list[str] = Field(default_factory=lambda: DEFAULT_SUBREDDITS.copy())
    monetized_link_domains: list[str] = Field(default_factory=lambda: ["prompthunt.me"])
    product_name: str = "PromptHunt"
    product_domain: str = "prompthunt.me"
    plain_mention_allowed: bool = True
    first_person_claims_allowed: bool = False
    default_disclosure_template: str = "Disclosure: I'm affiliated with PromptHunt."
    max_autoposts_per_hour: int = 2
    max_total_posts_per_day: int = 12
    cooldown_between_threads_minutes: int = 25
    subreddit_daily_cap: int = 2
    moderator_removals_circuit_breaker: int = 2
    rate_limits_circuit_breaker: int = 3
    ingest_interval_seconds: int = 300
    review_interval_seconds: int = 60
    monitor_interval_seconds: int = 600
    learning_interval_seconds: int = 86400
    relevance_threshold_default: float = 0.65
    value_add_threshold_default: float = 0.70
    autopost_overall_threshold_default: float = 0.80


@lru_cache(maxsize=1)
def get_settings():
    return AppSettings()

