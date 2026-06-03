"""Corp-Collab tool: email_send — send an email to an employee."""

from __future__ import annotations

from pathlib import Path
from typing import Any

DEFAULT_BASE = Path.home() / ".claude-code" / "collab"


def email_send(
    from_id: str,
    from_name: str,
    to_id: str,
    subject: str,
    body: str,
    priority: str = "normal",
    base_path: str | Path | None = None,
) -> dict[str, Any]:
    """Send an email to an employee's mailbox.

    Args:
        from_id: Sender employee ID.
        from_name: Sender display name.
        to_id: Recipient employee ID.
        subject: Email subject line.
        body: Email body text.
        priority: Priority level (normal, urgent, fyi).
        base_path: Override collab base directory.

    Returns:
        Dict with message_id, delivered_to, channel, priority.
    """
    try:
        from corp_collab.mailbox import Mailbox

        base = Path(base_path) if base_path else DEFAULT_BASE
        db_path = base / "employees" / to_id / "mailbox.db"

        mbox = Mailbox(employee_id=to_id, db_path=db_path)
        msg_id = mbox.send(
            channel="email",
            to_id=to_id,
            to_name=to_id,
            from_id=from_id,
            from_name=from_name,
            body=body,
            subject=subject,
            priority=priority,
        )
        mbox.close()

        return {
            "message_id": msg_id,
            "delivered_to": to_id,
            "channel": "email",
            "priority": priority,
        }

    except Exception as exc:
        return {"error": str(exc)}
