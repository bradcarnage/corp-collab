"""Corp-Collab: SQLite-backed mailbox with IM and email channels."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel TEXT NOT NULL,
    from_id TEXT NOT NULL,
    from_name TEXT NOT NULL,
    to_id TEXT NOT NULL,
    to_name TEXT NOT NULL,
    subject TEXT,
    body TEXT NOT NULL,
    priority TEXT DEFAULT 'normal',
    read BOOLEAN DEFAULT 0,
    created_at TEXT NOT NULL,
    read_at TEXT,
    archived BOOLEAN DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_messages_to_id ON messages(to_id);
CREATE INDEX IF NOT EXISTS idx_messages_channel ON messages(channel);
CREATE INDEX IF NOT EXISTS idx_messages_read ON messages(read);
CREATE INDEX IF NOT EXISTS idx_messages_archived ON messages(archived);
"""

VALID_CHANNELS = {"im", "email"}
VALID_PRIORITIES = {"normal", "urgent", "fyi"}


def _utcnow() -> str:
    """Return current UTC time as ISO string."""
    return datetime.now(timezone.utc).isoformat()


def _row_to_dict(row: sqlite3.Row) -> dict:
    """Convert a sqlite3.Row to a plain dict."""
    return dict(row)


class Mailbox:
    """SQLite-backed inbox/outbox supporting IM and email channels.

    IM messages are ephemeral (pruned to last 50 per conversation pair).
    Email messages are permanent until archived.
    """

    def __init__(self, employee_id: str, db_path: Optional[Path] = None) -> None:
        self.employee_id = employee_id
        if db_path is None:
            db_path = (
                Path.home()
                / ".claude-code"
                / "collab"
                / "employees"
                / employee_id
                / "mailbox.db"
            )
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self._conn = sqlite3.connect(
            str(self.db_path),
            check_same_thread=False,
            detect_types=sqlite3.PARSE_DECLTYPES,
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def send(
        self,
        channel: str,
        to_id: str,
        to_name: str,
        from_id: str,
        from_name: str,
        body: str,
        subject: Optional[str] = None,
        priority: str = "normal",
    ) -> int:
        """Send a message. Returns the new message ID."""
        channel = channel.lower()
        if channel not in VALID_CHANNELS:
            raise ValueError(f"Invalid channel {channel!r}, must be one of {VALID_CHANNELS}")
        if priority not in VALID_PRIORITIES:
            raise ValueError(f"Invalid priority {priority!r}, must be one of {VALID_PRIORITIES}")

        # IM is always urgent, no subject
        if channel == "im":
            priority = "urgent"
            subject = None

        cur = self._conn.execute(
            """INSERT INTO messages
               (channel, from_id, from_name, to_id, to_name, subject, body, priority, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (channel, from_id, from_name, to_id, to_name, subject, body, priority, _utcnow()),
        )
        self._conn.commit()
        msg_id = cur.lastrowid

        # Auto-prune IMs after send
        if channel == "im":
            self.prune_im()

        return msg_id  # type: ignore[return-value]

    def get_unread(self, channel: Optional[str] = None) -> list[dict]:
        """Get all unread, non-archived messages for this employee, optionally filtered by channel."""
        sql = "SELECT * FROM messages WHERE to_id = ? AND read = 0 AND archived = 0"
        params: list = [self.employee_id]
        if channel:
            sql += " AND channel = ?"
            params.append(channel)
        sql += " ORDER BY created_at DESC"
        rows = self._conn.execute(sql, params).fetchall()
        return [_row_to_dict(r) for r in rows]

    def mark_read(self, message_ids: list[int]) -> None:
        """Mark messages as read."""
        if not message_ids:
            return
        placeholders = ",".join("?" for _ in message_ids)
        self._conn.execute(
            f"UPDATE messages SET read = 1, read_at = ? WHERE id IN ({placeholders})",
            [_utcnow(), *message_ids],
        )
        self._conn.commit()

    def get_all(
        self, channel: Optional[str] = None, limit: int = 50, offset: int = 0
    ) -> list[dict]:
        """Get all non-archived messages for this employee (inbox)."""
        sql = "SELECT * FROM messages WHERE to_id = ? AND archived = 0"
        params: list = [self.employee_id]
        if channel:
            sql += " AND channel = ?"
            params.append(channel)
        sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        rows = self._conn.execute(sql, params).fetchall()
        return [_row_to_dict(r) for r in rows]

    def count_unread(self, channel: Optional[str] = None) -> int:
        """Count unread, non-archived messages."""
        sql = "SELECT COUNT(*) FROM messages WHERE to_id = ? AND read = 0 AND archived = 0"
        params: list = [self.employee_id]
        if channel:
            sql += " AND channel = ?"
            params.append(channel)
        row = self._conn.execute(sql, params).fetchone()
        return row[0]

    def prune_im(self, keep: int = 50) -> int:
        """Remove old IMs beyond *keep* limit per conversation pair. Returns count deleted."""
        # Find all conversation pairs involving this employee
        pairs = self._conn.execute(
            """SELECT DISTINCT
                   CASE WHEN from_id < to_id THEN from_id ELSE to_id END AS pair_a,
                   CASE WHEN from_id < to_id THEN to_id ELSE from_id END AS pair_b
               FROM messages
               WHERE channel = 'im' AND (from_id = ? OR to_id = ?)""",
            (self.employee_id, self.employee_id),
        ).fetchall()

        total_deleted = 0
        for pair in pairs:
            pair_a, pair_b = pair["pair_a"], pair["pair_b"]
            # Get IDs to keep (most recent `keep` messages in this pair)
            keep_ids = self._conn.execute(
                """SELECT id FROM messages
                   WHERE channel = 'im'
                     AND ((from_id = ? AND to_id = ?) OR (from_id = ? AND to_id = ?))
                   ORDER BY created_at DESC
                   LIMIT ?""",
                (pair_a, pair_b, pair_b, pair_a, keep),
            ).fetchall()
            keep_set = {r["id"] for r in keep_ids}

            if len(keep_set) < keep:
                continue  # not enough messages to prune

            # Delete older messages
            cur = self._conn.execute(
                f"""DELETE FROM messages
                    WHERE channel = 'im'
                      AND ((from_id = ? AND to_id = ?) OR (from_id = ? AND to_id = ?))
                      AND id NOT IN ({','.join('?' for _ in keep_set)})""",
                (pair_a, pair_b, pair_b, pair_a, *keep_set),
            )
            total_deleted += cur.rowcount

        if total_deleted > 0:
            self._conn.commit()
        return total_deleted

    def archive_read(self, older_than_hours: int = 24) -> int:
        """Archive read email messages older than the given hours. Returns count archived."""
        cutoff = datetime.now(timezone.utc)
        # We compare ISO strings; compute cutoff
        from datetime import timedelta

        cutoff_str = (cutoff - timedelta(hours=older_than_hours)).isoformat()
        cur = self._conn.execute(
            """UPDATE messages SET archived = 1
               WHERE channel = 'email'
                 AND read = 1
                 AND archived = 0
                 AND created_at < ?""",
            (cutoff_str,),
        )
        self._conn.commit()
        return cur.rowcount

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()

    def __del__(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass
