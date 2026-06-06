from functools import lru_cache

from pydantic import BaseModel


class Settings(BaseModel):
    """Fixed local backend defaults; these are not loaded from environment."""

    ib_host: str = "127.0.0.1"
    ib_port: int = 7497
    ib_client_id: int = 1
    options_database_path: str = "data/options.sqlite3"
    stock_analysis_database_path: str = "data/stock_analysis.sqlite3"
    portfolio_chart_values_database_path: str = "data/portfolio_chart_values.sqlite3"
    ib_request_queue_timeout_seconds: float = 0.25
    max_concurrent_options_analysis: int = 2
    max_concurrent_option_chains: int = 2
    max_concurrent_order_writes: int = 1
    max_concurrent_stock_analysis_reads: int = 4
    max_concurrent_stock_analysis_writes: int = 2
    option_chain_context_workers: int = 2
    max_option_chain_stream_strikes: int = 80
    order_subscriber_queue_size: int = 32
    allowed_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]


@lru_cache
def get_settings() -> Settings:
    return Settings()
