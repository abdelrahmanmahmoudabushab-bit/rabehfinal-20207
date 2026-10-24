"""Runtime configuration, read from environment variables (or a .env file)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./rahbeh.db"

    # Claude agents. Without a key the agents fall back to transparent heuristics.
    anthropic_api_key: str | None = None
    claude_model: str = "claude-opus-5-5"
    agent_effort: str = "medium"
    max_candidates_per_cycle: int = 3  # caps Claude spend per scan
    # starter: specialists (news, chart, company, mood) are rule-based and only the Analyst, Devil's advocate,
    # Manager, Reviewer and Coach call Claude. full: every specialist is its own Claude agent (about 2x the cost).
    agent_team: str = "starter"
    hunt_depth: int = 5  # deal finder: how many top-ranked stocks get the full specialist + analyst review
    keeper_interval_seconds: int = 300  # how often the Claude Position keeper re-checks each open trade (rules run every cycle)

    # Broker and data. Without Alpaca keys the app runs on the built-in market simulator.
    alpaca_api_key: str | None = None
    alpaca_secret_key: str | None = None
    alpaca_paper: bool = True
    alpaca_data_feed: str = "iex"  # "sip" needs a paid Alpaca data plan
    finnhub_api_key: str | None = None  # second price source + news
    fmp_api_key: str | None = None  # fundamentals, economic calendar fallback
    fred_api_key: str | None = None  # VIX, Fed funds, 10-year yield, oil (free key)
    sec_user_agent: str = "Rahbeh research admin@example.com"  # SEC asks for a contact email here

    # Alerts
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None

    # Scheduling
    scan_interval_seconds: int = 60
    demo_always_open: bool = True  # demo market trades around the clock
    watchlist: str = ""  # comma-separated; empty = built-in universe

    cors_origins: str = "http://localhost:3000"

    @property
    def demo(self) -> bool:
        return not (self.alpaca_api_key and self.alpaca_secret_key)

    @property
    def claude_enabled(self) -> bool:
        return bool(self.anthropic_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
