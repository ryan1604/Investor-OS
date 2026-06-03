from functools import lru_cache

from pydantic import BaseModel


class Settings(BaseModel):
    """Fixed local backend defaults; these are not loaded from environment."""

    ib_host: str = "127.0.0.1"
    ib_port: int = 7496
    ib_client_id: int = 1
    options_database_path: str = "data/options.sqlite3"
    allowed_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]


@lru_cache
def get_settings() -> Settings:
    return Settings()
