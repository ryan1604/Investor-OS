from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field, SecretStr


class Settings(BaseModel):
    """Fixed local backend defaults plus explicit .env-backed secrets."""

    ib_host: str = "127.0.0.1"
    ib_port: int = 7496
    ib_client_id: int = 0
    options_database_path: str = "data/options.sqlite3"
    options_screeners_database_path: str = "data/options_screeners.sqlite3"
    options_trade_trackers_database_path: str = "data/options_trade_trackers.sqlite3"
    day_trading_tracker_database_path: str = "data/day_trading_tracker.sqlite3"
    orders_database_path: str = "data/orders.sqlite3"
    stock_analysis_database_path: str = "data/stock_analysis.sqlite3"
    portfolio_chart_values_database_path: str = "data/portfolio_chart_values.sqlite3"
    earnings_watch_database_path: str = "data/earnings_watch.sqlite3"
    alpha_vantage_api_key: str | None = None
    ibkr_flex_token: SecretStr | None = Field(default=None, exclude=True, repr=False)
    ibkr_flex_query_id: str | None = None
    ib_request_queue_timeout_seconds: float = 0.25
    max_concurrent_options_analysis: int = 2
    max_concurrent_option_chains: int = 2
    max_concurrent_order_writes: int = 1
    max_concurrent_stock_analysis_reads: int = 4
    max_concurrent_stock_analysis_writes: int = 2
    max_concurrent_options_screener_tickers: int = 4
    options_screener_job_retention_minutes: int = 30
    options_screener_subscriber_queue_size: int = 64
    option_chain_context_workers: int = 2
    max_option_chain_stream_strikes: int = 80
    order_subscriber_queue_size: int = 32
    allowed_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    @property
    def ibkr_flex_configured(self) -> bool:
        return bool(
            self.ibkr_flex_token
            and self.ibkr_flex_token.get_secret_value().strip()
            and self.ibkr_flex_query_id
            and self.ibkr_flex_query_id.strip()
        )


@lru_cache
def get_settings() -> Settings:
    return Settings(
        alpha_vantage_api_key=alpha_vantage_api_key(),
        ibkr_flex_token=dotenv_value("IBKR_FLEX_TOKEN"),
        ibkr_flex_query_id=dotenv_value("IBKR_FLEX_QUERY_ID"),
    )


def alpha_vantage_api_key() -> str | None:
    return dotenv_value("ALPHA_VANTAGE_API_KEY")


def dotenv_value(key: str) -> str | None:
    for path in (Path(".env"), Path("..") / ".env"):
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            name, separator, value = line.partition("=")
            if separator and name.strip() == key:
                return value.strip().strip("'\"") or None
    return None
