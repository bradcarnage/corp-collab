"""Corp-Collab tool: release_resource."""

from __future__ import annotations

import fcntl
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml


_DEFAULT_BASE = Path.home() / ".claude-code" / "collab"


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def release_resource(
    resource_id: str,
    employee_id: str,
    base_path: Optional[Path] = None,
) -> dict:
    """Release a previously acquired resource lock.

    Parameters
    ----------
    resource_id : str
        Identifier for the resource to release.
    employee_id : str
        Employee releasing the lock.
    base_path : Path, optional
        Root collab directory. Defaults to ~/.claude-code/collab.

    Returns
    -------
    dict
        {released: True, promoted: employee_id|None} or {error: str}.
    """
    base = Path(base_path) if base_path else _DEFAULT_BASE
    lock_file = base / "locks" / f"{resource_id}.yaml"

    if not lock_file.exists():
        return {"error": "not holding resource"}

    with open(lock_file, "r+") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            content = f.read()
            if not content.strip():
                return {"error": "not holding resource"}

            data = yaml.safe_load(content)

            holder_ids = [h["employee_id"] for h in data["holders"]]
            if employee_id not in holder_ids:
                return {"error": "not holding resource"}

            # Remove from holders
            data["holders"] = [h for h in data["holders"] if h["employee_id"] != employee_id]

            # Promote first in queue if any
            promoted = None
            if data["queue"]:
                next_up = data["queue"].pop(0)
                promoted = next_up["employee_id"]
                data["holders"].append({
                    "employee_id": promoted,
                    "acquired_at": _utcnow(),
                })

            f.seek(0)
            f.truncate()
            yaml.safe_dump(data, f, default_flow_style=False)
            f.flush()

            return {"released": True, "promoted": promoted}
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)
