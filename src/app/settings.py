from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_SUBREDDITS = [
    "PromptEngineering",
    "aipromptprogramming",
    "promptdesign",
    "ClaudeAI",
    "ChatGPT",
    "OpenAI",
    "midjourney",
    "StableDiffusion",
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
    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    llm_model: str = Field(default="gpt-5-mini", alias="OPENAI_MODEL")
    openai_timeout_seconds: int = Field(default=30, alias="OPENAI_TIMEOUT_SECONDS")
    openai_max_output_tokens: int = Field(default=220, alias="OPENAI_MAX_OUTPUT_TOKENS")
    openai_log_tracebacks: bool = Field(default=False, alias="OPENAI_LOG_TRACEBACKS")
    postgres_dsn: str = "postgresql+psycopg://localhost/prompthunt"
    reddit_username: str | None = Field(default=None, alias="REDDIT_USERNAME")
    reddit_password: str | None = Field(default=None, alias="REDDIT_PASSWORD")
    reddit_posts_per_subreddit: int = Field(default=2, alias="REDDIT_POSTS_PER_SUBREDDIT")
    reddit_comment_limit: int = Field(default=5, alias="REDDIT_COMMENT_LIMIT")
    reddit_request_delay_seconds: float = Field(default=0.25, alias="REDDIT_REQUEST_DELAY_SECONDS")
    reddit_reprocess_after_hours: int = Field(default=24, alias="REDDIT_REPROCESS_AFTER_HOURS")
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
    memory_diary_path: str = Field(default="memory/agent_diary.md", alias="MEMORY_DIARY_PATH")
    memory_recent_days: int = Field(default=30, alias="MEMORY_RECENT_DAYS")
    memory_monthly_recap_months: int = Field(default=6, alias="MEMORY_MONTHLY_RECAP_MONTHS")
    memory_enabled: bool = Field(default=True, alias="MEMORY_ENABLED")

    @field_validator("postgres_dsn", mode="before")
    @classmethod
    def normalize_postgres_dsn(cls, value: str):
        if value.startswith("postgres://"):
            return value.replace("postgres://", "postgresql+psycopg://", 1)
        if value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+psycopg://", 1)
        return value


@lru_cache(maxsize=1)
def get_settings():
    return AppSettings()
