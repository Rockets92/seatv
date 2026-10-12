"""Archivio SQLite. Gli orari sono salvati in UTC come testo ISO ("...Z"),
così il confronto tra stringhe equivale a quello tra istanti."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS channels (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    logo       TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS channel_numbers (
    channel_id TEXT NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
    platform   TEXT NOT NULL,
    lcn        INTEGER NOT NULL,
    PRIMARY KEY (channel_id, platform)
);
CREATE INDEX IF NOT EXISTS channel_numbers_lcn ON channel_numbers (platform, lcn);

CREATE TABLE IF NOT EXISTS channel_sources (
    source            TEXT NOT NULL,
    source_channel_id TEXT NOT NULL,
    channel_id        TEXT NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
    PRIMARY KEY (source, source_channel_id)
);

CREATE TABLE IF NOT EXISTS programmes (
    channel_id  TEXT NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
    start       TEXT NOT NULL,
    stop        TEXT NOT NULL,
    title       TEXT NOT NULL,
    description TEXT,
    category    TEXT,
    image       TEXT,
    source      TEXT NOT NULL,
    PRIMARY KEY (channel_id, start)
);
CREATE INDEX IF NOT EXISTS programmes_stop ON programmes (channel_id, stop);

CREATE TABLE IF NOT EXISTS ingest_runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source      TEXT NOT NULL,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    channels    INTEGER NOT NULL DEFAULT 0,
    programmes  INTEGER NOT NULL DEFAULT 0,
    error       TEXT
);
"""

PLATFORMS = ("dtt", "tivusat", "sky")


def to_db_time(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("serve un datetime con fuso orario")
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def from_db_time(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


class Database:
    def __init__(self, path: str) -> None:
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    # --- scrittura -------------------------------------------------------

    def upsert_channel(
        self,
        conn: sqlite3.Connection,
        channel_id: str,
        name: str,
        logo: str | None,
        numbers: dict[str, int],
        now: datetime,
    ) -> None:
        """Il nome resta quello della prima fonte che ha visto il canale."""
        conn.execute(
            """
            INSERT INTO channels (id, name, logo, updated_at) VALUES (?, ?, ?, ?)
            ON CONFLICT (id) DO UPDATE SET
                logo = COALESCE(excluded.logo, channels.logo),
                updated_at = excluded.updated_at
            """,
            (channel_id, name, logo, to_db_time(now)),
        )
        for platform, lcn in numbers.items():
            if platform not in PLATFORMS:
                continue
            conn.execute(
                """
                INSERT INTO channel_numbers (channel_id, platform, lcn) VALUES (?, ?, ?)
                ON CONFLICT (channel_id, platform) DO UPDATE SET lcn = excluded.lcn
                """,
                (channel_id, platform, lcn),
            )

    def link_source(
        self, conn: sqlite3.Connection, source: str, source_channel_id: str, channel_id: str
    ) -> None:
        conn.execute(
            """
            INSERT INTO channel_sources (source, source_channel_id, channel_id) VALUES (?, ?, ?)
            ON CONFLICT (source, source_channel_id) DO UPDATE SET channel_id = excluded.channel_id
            """,
            (source, source_channel_id, channel_id),
        )

    def replace_programmes(
        self,
        conn: sqlite3.Connection,
        channel_id: str,
        source: str,
        programmes: list[tuple[datetime, datetime, str, str | None, str | None, str | None]],
    ) -> int:
        """Sostituisce i programmi del canale nell'intervallo coperto dai dati nuovi.

        Così un programma spostato di orario non resta duplicato col vecchio inizio.
        """
        if not programmes:
            return 0
        rows = sorted(
            {to_db_time(p[0]): (to_db_time(p[0]), to_db_time(p[1]), *p[2:]) for p in programmes}.values()
        )
        conn.execute(
            "DELETE FROM programmes WHERE channel_id = ? AND start >= ? AND start <= ?",
            (channel_id, rows[0][0], rows[-1][0]),
        )
        conn.executemany(
            """
            INSERT OR REPLACE INTO programmes
                (channel_id, start, stop, title, description, category, image, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [(channel_id, *row, source) for row in rows],
        )
        return len(rows)

    def prune_programmes(self, conn: sqlite3.Connection, before: datetime) -> int:
        cursor = conn.execute("DELETE FROM programmes WHERE stop < ?", (to_db_time(before),))
        return cursor.rowcount

    def start_run(self, source: str, now: datetime) -> int:
        with self.connect() as conn:
            cursor = conn.execute(
                "INSERT INTO ingest_runs (source, started_at) VALUES (?, ?)",
                (source, to_db_time(now)),
            )
            return cursor.lastrowid

    def finish_run(
        self, run_id: int, now: datetime, channels: int, programmes: int, error: str | None
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE ingest_runs
                SET finished_at = ?, channels = ?, programmes = ?, error = ?
                WHERE id = ?
                """,
                (to_db_time(now), channels, programmes, error, run_id),
            )

    # --- lettura ---------------------------------------------------------

    def list_channels(self, platform: str | None = None) -> list[dict]:
        with self.connect() as conn:
            if platform:
                rows = conn.execute(
                    """
                    SELECT c.* FROM channels c
                    JOIN channel_numbers n ON n.channel_id = c.id AND n.platform = ?
                    ORDER BY n.lcn, c.name
                    """,
                    (platform,),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT c.* FROM channels c
                    LEFT JOIN channel_numbers n ON n.channel_id = c.id AND n.platform = 'dtt'
                    ORDER BY n.lcn IS NULL, n.lcn, c.name
                    """
                ).fetchall()
            numbers = self._numbers(conn)
        return [self._channel(row, numbers) for row in rows]

    def get_channel(self, channel_id: str) -> dict | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM channels WHERE id = ?", (channel_id,)).fetchone()
            if row is None:
                return None
            numbers = self._numbers(conn, channel_id)
        return self._channel(row, numbers)

    def programmes_between(self, channel_id: str, start: datetime, end: datetime) -> list[dict]:
        """Programmi che iniziano in [start, end)."""
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM programmes
                WHERE channel_id = ? AND start >= ? AND start < ?
                ORDER BY start
                """,
                (channel_id, to_db_time(start), to_db_time(end)),
            ).fetchall()
        return [self._programme(row) for row in rows]

    def on_air(self, at: datetime, channel_ids: list[str] | None = None) -> dict[str, dict]:
        """Per ogni canale: il programma in onda in `at` e quello successivo."""
        at_text = to_db_time(at)
        with self.connect() as conn:
            current = conn.execute(
                "SELECT * FROM programmes WHERE start <= ? AND stop > ?", (at_text, at_text)
            ).fetchall()
            following = conn.execute(
                """
                SELECT p.* FROM programmes p
                JOIN (
                    SELECT channel_id, MIN(start) AS start FROM programmes
                    WHERE start > ? GROUP BY channel_id
                ) n ON n.channel_id = p.channel_id AND n.start = p.start
                """,
                (at_text,),
            ).fetchall()
        result: dict[str, dict] = {}
        for row in current:
            result.setdefault(row["channel_id"], {})["now"] = self._programme(row)
        for row in following:
            result.setdefault(row["channel_id"], {})["next"] = self._programme(row)
        if channel_ids is not None:
            wanted = set(channel_ids)
            result = {k: v for k, v in result.items() if k in wanted}
        return result

    def last_runs(self) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT r.* FROM ingest_runs r
                JOIN (SELECT source, MAX(id) AS id FROM ingest_runs GROUP BY source) l
                    ON l.id = r.id
                ORDER BY r.source
                """
            ).fetchall()
        return [dict(row) for row in rows]

    # --- helper ----------------------------------------------------------

    @staticmethod
    def _numbers(conn: sqlite3.Connection, channel_id: str | None = None) -> dict[str, dict[str, int]]:
        if channel_id is None:
            rows = conn.execute("SELECT * FROM channel_numbers").fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM channel_numbers WHERE channel_id = ?", (channel_id,)
            ).fetchall()
        numbers: dict[str, dict[str, int]] = {}
        for row in rows:
            numbers.setdefault(row["channel_id"], {})[row["platform"]] = row["lcn"]
        return numbers

    @staticmethod
    def _channel(row: sqlite3.Row, numbers: dict[str, dict[str, int]]) -> dict:
        return {
            "id": row["id"],
            "name": row["name"],
            "logo": row["logo"],
            "numbers": numbers.get(row["id"], {}),
        }

    @staticmethod
    def _programme(row: sqlite3.Row) -> dict:
        return {
            "channel_id": row["channel_id"],
            "start": from_db_time(row["start"]),
            "stop": from_db_time(row["stop"]),
            "title": row["title"],
            "description": row["description"],
            "category": row["category"],
            "image": row["image"],
        }
