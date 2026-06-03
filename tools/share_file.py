"""Corp-Collab tool: share_file.

Publish a file to a project workspace.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional


DEFAULT_BASE = Path.home() / ".claude-code" / "collab"


def share_file(
    project_id: str,
    file_name: str,
    content: str,
    author_id: str,
    author_name: str,
    message: str = "",
    base_path: Optional[str | Path] = None,
) -> dict:
    """Publish a file to a shared project workspace.

    Wraps FileShare.publish().

    Returns:
        The notification dict from publish, or {error: str}.
    """
    try:
        from corp_collab.file_share import FileShare

        bp = Path(base_path) if base_path else DEFAULT_BASE
        fs = FileShare(base_path=bp)

        result = fs.publish(
            project_id=project_id,
            file_name=file_name,
            content=content,
            author_id=author_id,
            author_name=author_name,
            message=message,
        )
        return result

    except Exception as e:
        return {"error": str(e)}
