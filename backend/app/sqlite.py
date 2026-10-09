import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path


class RowDatabase:
    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        with closing(connect_row_database(self.database_path)) as connection:
            with connection:
                yield connection


def connect_row_database(database_path: str | Path) -> sqlite3.Connection:
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    return connection
