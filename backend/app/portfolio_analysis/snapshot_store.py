import json
from pathlib import Path

from app.schemas import AnalysisRiskSnapshot
from app.sqlite import RowDatabase

KEY_FIELDS = {"session_date", "kind", "captured_at"}


class RiskSnapshotStore(RowDatabase):
    """One risk snapshot per account and US session; post_close beats intraday."""

    def __init__(self, database_path: str | Path) -> None:
        super().__init__(database_path)
        self.initialize()

    def initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS risk_snapshots (
                    account TEXT NOT NULL,
                    session_date TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    captured_at TEXT NOT NULL,
                    metrics TEXT NOT NULL,
                    PRIMARY KEY (account, session_date)
                )
                """
            )

    def save(self, account: str, snapshot: AnalysisRiskSnapshot) -> bool:
        """Store the snapshot unless it is intraday and the session already has a
        post_close row. Returns whether a row was written.
        """
        metrics = snapshot.model_dump(mode="json", exclude=KEY_FIELDS)
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO risk_snapshots (account, session_date, kind, captured_at, metrics)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT (account, session_date) DO UPDATE SET
                    kind = excluded.kind,
                    captured_at = excluded.captured_at,
                    metrics = excluded.metrics
                WHERE excluded.kind = 'post_close' OR risk_snapshots.kind = 'intraday'
                """,
                (
                    account,
                    snapshot.session_date.isoformat(),
                    snapshot.kind,
                    snapshot.captured_at.isoformat(),
                    json.dumps(metrics),
                ),
            )
            return cursor.rowcount > 0

    def history(self, account: str) -> list[AnalysisRiskSnapshot]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT session_date, kind, captured_at, metrics FROM risk_snapshots
                WHERE account = ? ORDER BY session_date
                """,
                (account,),
            ).fetchall()
        return [
            AnalysisRiskSnapshot(
                session_date=row["session_date"],
                kind=row["kind"],
                captured_at=row["captured_at"],
                **json.loads(row["metrics"]),
            )
            for row in rows
        ]
