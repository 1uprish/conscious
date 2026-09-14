"""Durable inbox for MacMan's conversational hot path.

This store is intentionally separate from Hermes session state. Hermes remains
the execution authority; this database only owns conversational admission,
grouping, and delivery ordering at the gateway edge.
"""

from __future__ import annotations

import json
import math
import sqlite3
import time
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar


_T = TypeVar("_T")
_SOURCES = frozenset({"user", "worker", "trigger"})


def _required_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be non-empty text")
    return value.strip()


def _timestamp(value: float | None) -> float:
    stamp = time.time() if value is None else float(value)
    if not math.isfinite(stamp):
        raise ValueError("timestamp must be finite")
    return stamp


def _settings(grouping_window: float, max_coalesce_messages: int) -> tuple[float, int]:
    window = float(grouping_window)
    if not math.isfinite(window) or window < 0:
        raise ValueError("grouping_window must be finite and non-negative")
    if (
        isinstance(max_coalesce_messages, bool)
        or not isinstance(max_coalesce_messages, int)
        or max_coalesce_messages < 1
    ):
        raise ValueError("max_coalesce_messages must be a positive integer")
    return window, max_coalesce_messages


def _record(row: sqlite3.Row) -> dict:
    result = dict(row)
    result["envelope"] = json.loads(result.pop("envelope_json"))
    return result


class ConversationInboxStore:
    """SQLite-backed serialized inbox, scoped by conversational owner."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._closed = False
        self._initialize()

    def __enter__(self) -> "ConversationInboxStore":
        if self._closed:
            raise RuntimeError("store is closed")
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.close()

    def close(self) -> None:
        self._closed = True

    def _connect(self) -> sqlite3.Connection:
        if self._closed:
            raise RuntimeError("store is closed")
        connection = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=10000")
        return connection

    def _initialize(self) -> None:
        connection = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        try:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA busy_timeout=10000")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS macman_conversation_inbox (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner_id TEXT NOT NULL,
                    source TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    thread_id TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    envelope_json TEXT NOT NULL,
                    state TEXT NOT NULL DEFAULT 'accepted',
                    accepted_at REAL NOT NULL,
                    available_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    claim_token TEXT,
                    claim_expires_at REAL,
                    UNIQUE (owner_id, source, channel, thread_id, message_id)
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS macman_conversation_inbox_ready
                ON macman_conversation_inbox (owner_id, state, source, id)
                """
            )
        finally:
            connection.close()

    def _write(self, operation: Callable[[sqlite3.Connection], _T]) -> _T:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            result = operation(connection)
            connection.commit()
            return result
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _read_all(self, sql: str, parameters: tuple) -> list[sqlite3.Row]:
        connection = self._connect()
        try:
            return connection.execute(sql, parameters).fetchall()
        finally:
            connection.close()

    def accept(
        self,
        owner_id: str,
        envelope: dict,
        *,
        now: float | None = None,
        grouping_window: float = 0.5,
        max_coalesce_messages: int = 5,
    ) -> tuple[dict, bool]:
        owner = _required_text(owner_id, "owner_id")
        window, cap = _settings(grouping_window, max_coalesce_messages)
        stamp = _timestamp(now)
        if not isinstance(envelope, dict):
            raise ValueError("envelope must be an object")
        source = envelope.get("source")
        if not isinstance(source, str) or source not in _SOURCES:
            raise ValueError("source must be user, worker, or trigger")
        channel = _required_text(envelope.get("channel"), "channel")
        message_id = _required_text(envelope.get("message_id"), "message_id")
        thread_id = envelope.get("thread_id", "")
        if not isinstance(thread_id, str):
            raise ValueError("thread_id must be text")
        attachments = envelope.get("attachments", [])
        if not isinstance(attachments, list) or any(not isinstance(item, dict) for item in attachments):
            raise ValueError("attachments must be a list of objects")
        content = envelope.get("content", "")
        if not isinstance(content, str) or (source == "user" and not content.strip() and not attachments):
            raise ValueError("user input must contain text or attachments")
        payload = json.dumps(envelope, sort_keys=True, ensure_ascii=True, allow_nan=False)
        key = (owner, source, channel, thread_id, message_id)

        def operation(connection: sqlite3.Connection) -> tuple[dict, bool]:
            existing = connection.execute(
                """
                SELECT * FROM macman_conversation_inbox
                WHERE owner_id=? AND source=? AND channel=? AND thread_id=? AND message_id=?
                """,
                key,
            ).fetchone()
            if existing is not None:
                if existing["envelope_json"] != payload:
                    raise ValueError("message ID was already accepted with a different payload")
                return _record(existing), False

            processing = connection.execute(
                """
                SELECT 1 FROM macman_conversation_inbox
                WHERE owner_id=? AND state='processing' LIMIT 1
                """,
                (owner,),
            ).fetchone()
            available_at = stamp
            if source == "user" and processing is None:
                pending_count = connection.execute(
                    """
                    SELECT count(*) FROM macman_conversation_inbox
                    WHERE owner_id=? AND state='accepted' AND source='user'
                      AND channel=? AND thread_id=?
                    """,
                    (owner, channel, thread_id),
                ).fetchone()[0]
                available_at = stamp if pending_count + 1 >= cap else stamp + window
                connection.execute(
                    """
                    UPDATE macman_conversation_inbox SET available_at=?, updated_at=?
                    WHERE owner_id=? AND state='accepted' AND source='user'
                      AND channel=? AND thread_id=?
                    """,
                    (available_at, stamp, owner, channel, thread_id),
                )

            cursor = connection.execute(
                """
                INSERT INTO macman_conversation_inbox
                    (owner_id, source, channel, thread_id, message_id, envelope_json,
                     accepted_at, available_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (*key, payload, stamp, available_at, stamp),
            )
            row = connection.execute(
                "SELECT * FROM macman_conversation_inbox WHERE id=?",
                (cursor.lastrowid,),
            ).fetchone()
            return _record(row), True

        return self._write(operation)

    def claim(
        self,
        owner_id: str,
        claim_token: str,
        *,
        now: float | None = None,
        lease_seconds: float = 120,
        max_coalesce_messages: int = 5,
    ) -> list[dict]:
        owner = _required_text(owner_id, "owner_id")
        token = _required_text(claim_token, "claim_token")
        _, cap = _settings(0, max_coalesce_messages)
        stamp = _timestamp(now)
        lease = float(lease_seconds)
        if not math.isfinite(lease) or lease <= 0:
            raise ValueError("lease_seconds must be finite and positive")

        def operation(connection: sqlite3.Connection) -> list[dict]:
            if connection.execute(
                """
                SELECT 1 FROM macman_conversation_inbox
                WHERE owner_id=? AND state='processing' LIMIT 1
                """,
                (owner,),
            ).fetchone():
                return []

            user_rows = connection.execute(
                """
                SELECT * FROM macman_conversation_inbox
                WHERE owner_id=? AND state='accepted' AND source='user'
                ORDER BY id LIMIT ?
                """,
                (owner, cap),
            ).fetchall()
            if user_rows:
                if user_rows[0]["available_at"] > stamp:
                    return []
                destination = (user_rows[0]["channel"], user_rows[0]["thread_id"])
                selected = []
                for row in user_rows:
                    if (row["channel"], row["thread_id"]) != destination:
                        break
                    selected.append(row)
            else:
                selected = connection.execute(
                    """
                    SELECT * FROM macman_conversation_inbox
                    WHERE owner_id=? AND state='accepted'
                    ORDER BY id LIMIT 1
                    """,
                    (owner,),
                ).fetchall()
            if not selected:
                return []
            if connection.execute(
                "SELECT 1 FROM macman_conversation_inbox WHERE owner_id=? AND claim_token=? LIMIT 1",
                (owner, token),
            ).fetchone():
                raise ValueError("claim_token must not be reused")

            ids = [row["id"] for row in selected]
            placeholders = ",".join("?" for _ in ids)
            connection.execute(
                f"""
                UPDATE macman_conversation_inbox
                SET state='processing', claim_token=?, claim_expires_at=?, updated_at=?
                WHERE id IN ({placeholders})
                """,
                (token, stamp + lease, stamp, *ids),
            )
            claimed = connection.execute(
                f"SELECT * FROM macman_conversation_inbox WHERE id IN ({placeholders}) ORDER BY id",
                ids,
            ).fetchall()
            return [_record(row) for row in claimed]

        return self._write(operation)

    def settle(
        self,
        owner_id: str,
        claim_token: str,
        *,
        state: str,
        now: float | None = None,
    ) -> bool:
        if state not in {"handled", "failed"}:
            raise ValueError("terminal state must be handled or failed")
        owner = _required_text(owner_id, "owner_id")
        token = _required_text(claim_token, "claim_token")
        stamp = _timestamp(now)

        def operation(connection: sqlite3.Connection) -> bool:
            cursor = connection.execute(
                """
                UPDATE macman_conversation_inbox
                SET state=?, claim_expires_at=NULL, updated_at=?
                WHERE owner_id=? AND claim_token=? AND state='processing'
                """,
                (state, stamp, owner, token),
            )
            return cursor.rowcount > 0

        return self._write(operation)

    def list_pending(self, owner_id: str, *, limit: int = 100) -> list[dict]:
        owner = _required_text(owner_id, "owner_id")
        _, bounded_limit = _settings(0, limit)
        rows = self._read_all(
            """
            SELECT * FROM macman_conversation_inbox
            WHERE owner_id=? AND state IN ('accepted', 'processing')
            ORDER BY id LIMIT ?
            """,
            (owner, bounded_limit),
        )
        return [_record(row) for row in rows]
