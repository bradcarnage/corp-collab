"""Corp-Collab: IM steer channel helpers built on mailbox + checkpoint."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from corp_collab.mailbox import Mailbox


def _get_mailbox(employee_id: str, base_path: Path | None = None) -> Mailbox:
    bp = base_path or Path.home() / ".claude-code" / "collab"
    return Mailbox(employee_id, db_path=bp / "employees" / employee_id / "mailbox.db")


def send_steer(
    from_id: str,
    from_name: str,
    to_id: str,
    to_name: str,
    instruction: str,
    base_path: Path | None = None,
) -> dict:
    """Send a steer/redirect IM. Prefixes body with [STEER] marker."""
    mailbox = _get_mailbox(to_id, base_path)
    try:
        body = f"[STEER] {instruction}"
        msg_id = mailbox.send(
            to_id=to_id,
            to_name=to_name,
            channel="im",
            body=body,
            from_id=from_id,
            from_name=from_name,
            priority="urgent",
        )
        return {"message_id": msg_id, "delivered_to": to_id, "type": "steer"}
    finally:
        mailbox.close()


def send_broadcast(
    from_id: str,
    from_name: str,
    to_ids: list[str],
    body: str,
    to_names: Optional[list[str]] = None,
    base_path: Path | None = None,
) -> dict:
    """Send IM to multiple employees at once.

    *to_names* should parallel *to_ids*; defaults to the id if not provided.
    """
    if to_names is None:
        to_names = to_ids  # fall back to ids as display names
    results = []
    for tid, tname in zip(to_ids, to_names):
        mailbox = _get_mailbox(tid, base_path)
        try:
            msg_id = mailbox.send(
                to_id=tid,
                to_name=tname,
                channel="im",
                body=body,
                from_id=from_id,
                from_name=from_name,
            )
            results.append({"to": tid, "message_id": msg_id, "status": "sent"})
        except Exception as e:
            results.append({"to": tid, "error": str(e), "status": "failed"})
        finally:
            mailbox.close()
    return {"broadcast": True, "recipients": len(to_ids), "results": results}


def get_pending_steers(
    employee_id: str, base_path: Path | None = None
) -> list[dict]:
    """Get unread steer IMs for an employee."""
    mailbox = _get_mailbox(employee_id, base_path)
    try:
        ims = mailbox.get_unread(channel="im")
        return [m for m in ims if "[STEER]" in m.get("body", "")]
    finally:
        mailbox.close()


def count_pending(employee_id: str, base_path: Path | None = None) -> dict:
    """Quick count of pending IMs and steers."""
    mailbox = _get_mailbox(employee_id, base_path)
    try:
        ims = mailbox.get_unread(channel="im")
        steers = [m for m in ims if "[STEER]" in m.get("body", "")]
        return {
            "total_im": len(ims),
            "steers": len(steers),
            "regular": len(ims) - len(steers),
        }
    finally:
        mailbox.close()
