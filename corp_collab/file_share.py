"""Corp-Collab: file_share module.

Project-scoped shared workspaces with access control.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Union


class AccessDeniedError(PermissionError):
    """Raised when an employee lacks access to a project."""
    pass


class ProjectNotFoundError(FileNotFoundError):
    """Raised when a project does not exist."""
    pass


class FileShare:
    """Manage project-scoped shared file workspaces with access control."""

    def __init__(self, base_path: Optional[Path] = None):
        if base_path is None:
            base_path = Path.home() / ".claude-code" / "collab"
        self.base_path = Path(base_path)
        self.projects_dir = self.base_path / "projects"
        self.projects_dir.mkdir(parents=True, exist_ok=True)

    def _project_dir(self, project_id: str) -> Path:
        return self.projects_dir / project_id

    def _manifest_path(self, project_id: str) -> Path:
        return self._project_dir(project_id) / "manifest.json"

    def _files_dir(self, project_id: str) -> Path:
        return self._project_dir(project_id) / "files"

    def _load_manifest(self, project_id: str) -> dict:
        mpath = self._manifest_path(project_id)
        if not mpath.exists():
            raise ProjectNotFoundError(f"Project '{project_id}' not found")
        with open(mpath, "r") as f:
            return json.load(f)

    def _save_manifest(self, project_id: str, manifest: dict) -> None:
        with open(self._manifest_path(project_id), "w") as f:
            json.dump(manifest, f, indent=2)

    def _check_access(self, manifest: dict, employee_id: str, project_id: str) -> None:
        if employee_id not in manifest["access"]:
            raise AccessDeniedError(
                f"Employee '{employee_id}' does not have access to project '{project_id}'"
            )

    def create_project(
        self, project_id: str, created_by: str, access: Optional[list] = None
    ) -> Path:
        """Create a new project workspace.

        Args:
            project_id: Unique project identifier.
            created_by: Employee ID of the creator.
            access: Initial access list. Creator is always included.

        Returns:
            Path to the project directory.
        """
        pdir = self._project_dir(project_id)
        pdir.mkdir(parents=True, exist_ok=True)
        self._files_dir(project_id).mkdir(exist_ok=True)

        access_list = list(access) if access else []
        if created_by not in access_list:
            access_list.insert(0, created_by)

        manifest = {
            "project": project_id,
            "created_by": created_by,
            "access": access_list,
            "files": {},
            "notifications": [],
        }
        self._save_manifest(project_id, manifest)
        return pdir

    def add_access(self, project_id: str, employee_id: str) -> None:
        """Grant an employee access to a project."""
        manifest = self._load_manifest(project_id)
        if employee_id not in manifest["access"]:
            manifest["access"].append(employee_id)
            self._save_manifest(project_id, manifest)

    def remove_access(self, project_id: str, employee_id: str) -> None:
        """Revoke an employee's access to a project."""
        manifest = self._load_manifest(project_id)
        if employee_id in manifest["access"]:
            manifest["access"].remove(employee_id)
            self._save_manifest(project_id, manifest)

    def publish(
        self,
        project_id: str,
        file_name: str,
        content: Union[str, bytes],
        author_id: str,
        author_name: str,
        message: str = "",
    ) -> dict:
        """Publish a file to a project workspace.

        Auto-adds the author to the access list if not already present.

        Args:
            project_id: Target project.
            file_name: Name of the file to publish.
            content: File content (str or bytes).
            author_id: Employee ID of the author.
            author_name: Display name of the author.
            message: Optional commit-style message.

        Returns:
            Notification dict.
        """
        manifest = self._load_manifest(project_id)

        # Auto-add author to access list
        if author_id not in manifest["access"]:
            manifest["access"].append(author_id)

        self._check_access(manifest, author_id, project_id)

        # Write file
        fpath = self._files_dir(project_id) / file_name
        if isinstance(content, bytes):
            fpath.write_bytes(content)
        else:
            fpath.write_text(content)

        timestamp = datetime.now(timezone.utc).isoformat()

        # Update manifest
        manifest["files"][file_name] = {
            "author": author_id,
            "shared_at": timestamp,
            "message": message,
        }

        notification = {
            "type": "file_published",
            "project": project_id,
            "file_name": file_name,
            "author_id": author_id,
            "author_name": author_name,
            "message": message,
            "timestamp": timestamp,
        }
        manifest["notifications"].append(notification)
        self._save_manifest(project_id, manifest)

        return notification

    def read(self, project_id: str, file_name: str, reader_id: str) -> Union[str, bytes]:
        """Read a file from a project workspace.

        Args:
            project_id: Target project.
            file_name: File to read.
            reader_id: Employee requesting access.

        Returns:
            File content as str or bytes.
        """
        manifest = self._load_manifest(project_id)
        self._check_access(manifest, reader_id, project_id)

        fpath = self._files_dir(project_id) / file_name
        if not fpath.exists():
            raise FileNotFoundError(f"File '{file_name}' not found in project '{project_id}'")

        # Try text first, fall back to bytes
        try:
            return fpath.read_text()
        except UnicodeDecodeError:
            return fpath.read_bytes()

    def list_files(self, project_id: str, reader_id: str) -> list:
        """List all files in a project workspace.

        Returns:
            List of dicts with file metadata.
        """
        manifest = self._load_manifest(project_id)
        self._check_access(manifest, reader_id, project_id)

        result = []
        for name, meta in manifest["files"].items():
            result.append({
                "file_name": name,
                "author": meta["author"],
                "shared_at": meta["shared_at"],
                "message": meta.get("message", ""),
            })
        return result

    def list_projects(self, employee_id: Optional[str] = None) -> list:
        """List projects, optionally filtered by employee access.

        Args:
            employee_id: If provided, only return projects this employee can access.

        Returns:
            List of project summary dicts.
        """
        results = []
        if not self.projects_dir.exists():
            return results

        for pdir in sorted(self.projects_dir.iterdir()):
            mpath = pdir / "manifest.json"
            if not mpath.is_file():
                continue
            with open(mpath) as f:
                manifest = json.load(f)

            if employee_id and employee_id not in manifest["access"]:
                continue

            results.append({
                "project": manifest["project"],
                "created_by": manifest["created_by"],
                "access": manifest["access"],
                "file_count": len(manifest["files"]),
            })
        return results

    def delete_file(self, project_id: str, file_name: str, deleter_id: str) -> None:
        """Delete a file from a project. Only the file author or project creator can delete.

        Args:
            project_id: Target project.
            file_name: File to delete.
            deleter_id: Employee requesting deletion.
        """
        manifest = self._load_manifest(project_id)
        self._check_access(manifest, deleter_id, project_id)

        if file_name not in manifest["files"]:
            raise FileNotFoundError(f"File '{file_name}' not found in project '{project_id}'")

        file_meta = manifest["files"][file_name]
        if deleter_id != file_meta["author"] and deleter_id != manifest["created_by"]:
            raise AccessDeniedError(
                f"Employee '{deleter_id}' cannot delete '{file_name}' — "
                f"only the author or project creator can delete"
            )

        # Remove from disk
        fpath = self._files_dir(project_id) / file_name
        if fpath.exists():
            fpath.unlink()

        # Remove from manifest
        del manifest["files"][file_name]
        self._save_manifest(project_id, manifest)

    def get_notifications(self, project_id: str, since: Optional[str] = None) -> list:
        """Get notifications for a project.

        Args:
            project_id: Target project.
            since: ISO timestamp — only return notifications after this time.

        Returns:
            List of notification dicts.
        """
        manifest = self._load_manifest(project_id)
        notifications = manifest.get("notifications", [])

        if since:
            since_dt = datetime.fromisoformat(since)
            notifications = [
                n for n in notifications
                if datetime.fromisoformat(n["timestamp"]) > since_dt
            ]

        return notifications
