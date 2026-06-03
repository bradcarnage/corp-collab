"""Corp-Collab tool: im_send — send an instant message to an employee."""

from __future__ import annotations

from pathlib import Path
from typing import Any

DEFAULT_BASE = Path.home() / ".claude-code" / "collab"


def im_send(
    from_id: str,
    from_name: str,
    to_id: str,
    body: str,
    base_path: str | Path | None = None,
) -> dict[str, Any]:
    """Send an instant message to an employee's mailbox.

    Args:
        from_id: Sender employee ID.
        from_name: Sender display name.
        to_id: Recipient employee ID.
        body: Message body text.
        base_path: Override collab base directory.

    Returns:
        Dict with message_id, delivered_to, channel.
    """
    try:
        from corp_collab.mailbox import Mailbox

        base = Path(base_path) if base_path else DEFAULT_BASE
        db_path = base / "employees" / to_id / "mailbox.db"

        mbox = Mailbox(employee_id=to_id, db_path=db_path)
        msg_id = mbox.send(
            channel="im",
            to_id=to_id,
            to_name=to_id,  # caller may not know name; use id as fallback
            from_id=from_id,
            from_name=from_name,
            body=body,
        )
        mbox.close()

        return {
            "message_id": msg_id,
            "delivered_to": to_id,
            "channel": "im",
        }

    except Exception as exc:
        return {"error": str(exc)}
