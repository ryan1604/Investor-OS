from datetime import UTC, date, datetime
from contextlib import closing, contextmanager
from decimal import Decimal
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas import normalize_required_account
from app.sqlite import RowDatabase


class DailyNav(BaseModel):
    model_config = ConfigDict(frozen=True)

    account: str
    report_date: str
    nav: Decimal = Field(allow_inf_nan=False)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    source: Literal["flex", "portfolioanalyst"]

    @field_validator("account")
    @classmethod
    def valid_account(cls, value: str) -> str:
        return normalize_required_account(value)

    @field_validator("report_date")
    @classmethod
    def valid_date(cls, value: str) -> str:
        if date.fromisoformat(value).isoformat() != value:
            raise ValueError("report_date must use YYYY-MM-DD format.")
        return value

    @field_validator("nav", mode="before")
    @classmethod
    def exact_amount(cls, value):
        if isinstance(value, (float, bool)):
            raise ValueError("NAV must be supplied as a decimal string or Decimal.")
        return value


class DailyNavRow(DailyNav):
    updated_at: str


SyncError = Literal["unavailable", "credentials", "invalid_report"]
SYNC_ERRORS = {
    "unavailable": "IBKR reporting is temporarily unavailable.",
    "credentials": "Check the IBKR Flex credentials.",
    "invalid_report": "The IBKR report could not be validated.",
}


class NavSyncStatus(BaseModel):
    configured: bool
    last_successful_sync: str | None = None
    error: str | None = None
    state: Literal["unconfigured", "pending", "syncing", "current", "stale", "failed"] = "unconfigured"


class DailyNavResponse(BaseModel):
    account: str
    rows: list[DailyNavRow]
    latest_report_date: str | None
    currencies: list[str]
    currency_changed: bool
    sync: NavSyncStatus


class DailyNavStore(RowDatabase):
    @contextmanager
    def _connect(self):
        with closing(super()._connect()) as connection:
            with connection:
                yield connection

    def __init__(self, database_path: str | Path) -> None:
        super().__init__(database_path)
        with self._connect() as connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS portfolio_daily_nav (
                    account TEXT NOT NULL,
                    report_date TEXT NOT NULL,
                    nav TEXT NOT NULL,
                    currency TEXT NOT NULL,
                    source TEXT NOT NULL CHECK(source IN ('flex', 'portfolioanalyst')),
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(account, report_date)
                )
            """)
            connection.execute("""
                CREATE TABLE IF NOT EXISTS portfolio_nav_sync (
                    account TEXT PRIMARY KEY,
                    last_successful_sync TEXT,
                    error_code TEXT CHECK(error_code IN (
                        'unavailable', 'credentials', 'invalid_report'
                    ))
                )
            """)

    def upsert_values(self, values: list[DailyNav]) -> None:
        # Revalidate even model_construct/model_copy inputs at the storage boundary.
        validated = [DailyNav.model_validate(value.model_dump()) for value in values]
        unique: dict[tuple[str, str], DailyNav] = {}
        for value in validated:
            key = (value.account, value.report_date)
            if key in unique and unique[key] != value:
                raise ValueError("Conflicting daily NAV rows in one batch.")
            unique[key] = value
        timestamp = datetime.now(UTC).isoformat()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            for value in unique.values():
                existing = connection.execute(
                    "SELECT currency FROM portfolio_daily_nav WHERE account = ? AND report_date = ?",
                    (value.account, value.report_date),
                ).fetchone()
                if existing and existing["currency"] != value.currency:
                    raise ValueError("Conflicting currency for an existing NAV date.")
                connection.execute("""
                    INSERT INTO portfolio_daily_nav
                        (account, report_date, nav, currency, source, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(account, report_date) DO UPDATE SET
                        nav = excluded.nav, source = excluded.source,
                        updated_at = excluded.updated_at
                    WHERE (portfolio_daily_nav.source != 'flex' OR excluded.source = 'flex')
                      AND (portfolio_daily_nav.nav != excluded.nav
                           OR portfolio_daily_nav.source != excluded.source)
                """, (value.account, value.report_date, str(value.nav), value.currency,
                      value.source, timestamp))

    def record_sync(self, account: str, *, error: SyncError | None = None) -> None:
        account = normalize_required_account(account)
        if error is not None and error not in SYNC_ERRORS:
            raise ValueError("Unknown sync error code.")
        with self._connect() as connection:
            connection.execute("""
                INSERT INTO portfolio_nav_sync (account, last_successful_sync, error_code)
                VALUES (?, ?, ?)
                ON CONFLICT(account) DO UPDATE SET
                    last_successful_sync = COALESCE(excluded.last_successful_sync,
                        portfolio_nav_sync.last_successful_sync),
                    error_code = excluded.error_code
            """, (account, datetime.now(UTC).isoformat() if error is None else None, error))

    def list_accounts(self) -> list[str]:
        with self._connect() as connection:
            return [row["account"] for row in connection.execute(
                "SELECT DISTINCT account FROM portfolio_daily_nav ORDER BY account"
            )]

    def history(self, account: str, *, configured: bool = False) -> DailyNavResponse:
        account = normalize_required_account(account)
        with self._connect() as connection:
            connection.execute("BEGIN")
            rows = [DailyNavRow.model_validate(dict(row)) for row in connection.execute(
                "SELECT * FROM portfolio_daily_nav WHERE account = ? ORDER BY report_date",
                (account,),
            )]
            status = connection.execute(
                "SELECT * FROM portfolio_nav_sync WHERE account = ?", (account,)
            ).fetchone()
        currencies = sorted({row.currency for row in rows})
        return DailyNavResponse(
            account=account, rows=rows,
            latest_report_date=rows[-1].report_date if rows else None,
            currencies=currencies, currency_changed=len(currencies) > 1,
            sync=NavSyncStatus(
                configured=configured,
                last_successful_sync=status["last_successful_sync"] if status else None,
                error=SYNC_ERRORS.get(status["error_code"]) if status else None,
            ),
        )
