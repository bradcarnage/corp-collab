"""Corp-Collab tool: acquire_resource."""

from __future__ import annotations

import fcntl
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml


_DEFAULT_BASE = Path.home() / ".claude-code" / "collab"


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def acquire_resource(
    resource_id: str,
    employee_id: str,
    lock_type: str = "exclusive",
    base_path: Optional[Path] = None,
    max_holders: int = 3,
) -> dict:
    """Acquire a resource lock.

    Parameters
    ----------
    resource_id : str
        Identifier for the resource to lock.
    employee_id : str
        Employee requesting the lock.
    lock_type : str
        'exclusive' (single holder) or 'semaphore' (multiple holders).
    base_path : Path, optional
        Root collab directory. Defaults to ~/.claude-code/collab.
    max_holders : int
        Maximum concurrent holders for semaphore locks (default 3).

    Returns
    -------
    dict
        {acquired: True/False, ...} with context depending on outcome.
    """
    if lock_type not in ("exclusive", "semaphore"):
        raise ValueError(f"Invalid lock_type {lock_type!r}, must be 'exclusive' or 'semaphore'")

    base = Path(base_path) if base_path else _DEFAULT_BASE
    locks_dir = base / "locks"
    locks_dir.mkdir(parents=True, exist_ok=True)
    lock_file = locks_dir / f"{resource_id}.yaml"

    # Create file if it doesn't exist
    if not lock_file.exists():
        lock_file.touch()

    with open(lock_file, "r+") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            content = f.read()
            if content.strip():
                data = yaml.safe_load(content)
            else:
                data = None

            if data is None:
                data = {
                    "resource_id": resource_id,
                    "lock_type": lock_type,
                    "max_holders": max_holders if lock_type == "semaphore" else 1,
                    "holders": [],
                    "queue": [],
                }

            # Check if already holding or queued
            holder_ids = [h["employee_id"] for h in data["holders"]]
            queue_ids = [q["employee_id"] for q in data["queue"]]
            if employee_id in holder_ids:
                return {"acquired": True, "resource_id": resource_id, "lock_type": data["lock_type"], "already_held": True}
            if employee_id in queue_ids:
                pos = queue_ids.index(employee_id) + 1
                result: dict = {"acquired": False, "position": pos}
                if data["lock_type"] == "exclusive" and data["holders"]:
                    result["holder"] = data["holders"][0]["employee_id"]
                return result

            if data["lock_type"] == "exclusive":
                if len(data["holders"]) == 0:
                    # Available — acquire
                    data["holders"].append({"employee_id": employee_id, "acquired_at": _utcnow()})
                    _write_lock(f, data)
                    return {"acquired": True, "resource_id": resource_id, "lock_type": "exclusive"}
                else:
                    # Already held — queue
                    data["queue"].append({"employee_id": employee_id, "queued_at": _utcnow()})
                    _write_lock(f, data)
                    return {
                        "acquired": False,
                        "position": len(data["queue"]),
                        "holder": data["holders"][0]["employee_id"],
                    }
            else:
                # Semaphore
                effective_max = data.get("max_holders", max_holders)
                if len(data["holders"]) < effective_max:
                    data["holders"].append({"employee_id": employee_id, "acquired_at": _utcnow()})
                    _write_lock(f, data)
                    return {"acquired": True, "resource_id": resource_id, "lock_type": "semaphore"}
                else:
                    data["queue"].append({"employee_id": employee_id, "queued_at": _utcnow()})
                    _write_lock(f, data)
                    return {"acquired": False, "position": len(data["queue"])}
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def _write_lock(f, data: dict) -> None:
    """Rewrite lock file with updated data."""
    f.seek(0)
    f.truncate()
    yaml.safe_dump(data, f, default_flow_style=False)
    f.flush()
