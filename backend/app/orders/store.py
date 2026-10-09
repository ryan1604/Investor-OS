from pathlib import Path

from app.schemas import OrderRecord
from app.sqlite import RowDatabase


class OrderStore(RowDatabase):
    def __init__(self, database_path: str | Path) -> None:
        super().__init__(database_path)
        self.initialize()

    def initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS orders (
                    order_id INTEGER PRIMARY KEY,
                    perm_id INTEGER,
                    parent_order_id INTEGER,
                    account TEXT NOT NULL,
                    status TEXT NOT NULL,
                    editable INTEGER NOT NULL,
                    submitted_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    record_json TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_orders_perm_id ON orders(perm_id)",
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_orders_account ON orders(account)",
            )

    def list_orders(self) -> list[OrderRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT record_json
                FROM orders
                ORDER BY submitted_at ASC, order_id ASC
                """
            ).fetchall()
        return [OrderRecord.model_validate_json(row["record_json"]) for row in rows]

    def upsert_order(self, record: OrderRecord) -> None:
        self.upsert_orders([record])

    def delete_order(self, order_id: int) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM orders WHERE order_id = ?", (order_id,))

    def upsert_orders(self, records: list[OrderRecord]) -> None:
        with self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO orders (
                    order_id,
                    perm_id,
                    parent_order_id,
                    account,
                    status,
                    editable,
                    submitted_at,
                    updated_at,
                    record_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(order_id) DO UPDATE SET
                    perm_id = excluded.perm_id,
                    parent_order_id = excluded.parent_order_id,
                    account = excluded.account,
                    status = excluded.status,
                    editable = excluded.editable,
                    submitted_at = excluded.submitted_at,
                    updated_at = excluded.updated_at,
                    record_json = excluded.record_json
                """,
                [order_row(record) for record in records],
            )

def order_row(record: OrderRecord) -> tuple[
    int,
    int | None,
    int | None,
    str,
    str,
    int,
    str,
    str,
    str,
]:
    return (
        record.order_id,
        record.perm_id,
        record.parent_order_id,
        record.account,
        record.status,
        int(record.editable),
        record.submitted_at,
        record.updated_at,
        record.model_dump_json(),
    )
