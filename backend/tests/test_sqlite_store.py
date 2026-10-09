import sqlite3

import pytest

from app.sqlite import RowDatabase


def test_connection_commits_and_closes_after_success(tmp_path):
    database = RowDatabase(tmp_path / "rows.sqlite3")
    with database._connect() as connection:
        connection.execute("CREATE TABLE records (value TEXT)")
        connection.execute("INSERT INTO records VALUES ('saved')")
        cursor = connection.execute("SELECT value FROM records")
        row = cursor.fetchone()
        assert row["value"] == "saved"

    with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
        connection.execute("SELECT 1")
    with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
        cursor.fetchone()
    assert row["value"] == "saved"
    with database._connect() as reopened:
        assert reopened.execute("SELECT value FROM records").fetchone()["value"] == "saved"


@pytest.mark.parametrize("error_class", [ValueError, KeyboardInterrupt])
def test_connection_rolls_back_and_closes_after_body_error(tmp_path, error_class):
    database = RowDatabase(tmp_path / "rows.sqlite3")
    with database._connect() as connection:
        connection.execute("CREATE TABLE records (value TEXT)")
        connection.execute("INSERT INTO records VALUES ('saved')")

    with pytest.raises(error_class, match="block failed"):
        with database._connect() as connection:
            connection.execute("INSERT INTO records VALUES ('pending')")
            raise error_class("block failed")

    with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
        connection.execute("SELECT 1")
    with database._connect() as reopened:
        assert [row["value"] for row in reopened.execute("SELECT value FROM records")] == [
            "saved",
        ]


def test_connection_rolls_back_and_closes_after_commit_error(tmp_path):
    database = RowDatabase(tmp_path / "rows.sqlite3")
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY constraint failed"):
        with database._connect() as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("CREATE TABLE parents (id INTEGER PRIMARY KEY)")
            connection.execute(
                "CREATE TABLE children (parent_id INTEGER REFERENCES parents(id) "
                "DEFERRABLE INITIALLY DEFERRED)"
            )
            connection.execute("INSERT INTO children VALUES (1)")

    with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
        connection.execute("SELECT 1")
    with database._connect() as reopened:
        assert reopened.execute("SELECT * FROM children").fetchall() == []
