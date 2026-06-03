"""Tests for corp_collab.file_share module."""

import json
import tempfile
from pathlib import Path

import pytest

from corp_collab.file_share import (
    AccessDeniedError,
    FileShare,
    ProjectNotFoundError,
)


@pytest.fixture
def tmp_base(tmp_path):
    return tmp_path / "collab"


@pytest.fixture
def fs(tmp_base):
    return FileShare(base_path=tmp_base)


# --- Project creation ---

class TestCreateProject:
    def test_create_basic(self, fs, tmp_base):
        path = fs.create_project("proj-1", "emp-alice")
        assert path.exists()
        assert (path / "manifest.json").exists()
        assert (path / "files").is_dir()

        manifest = json.loads((path / "manifest.json").read_text())
        assert manifest["project"] == "proj-1"
        assert manifest["created_by"] == "emp-alice"
        assert "emp-alice" in manifest["access"]

    def test_create_with_access_list(self, fs):
        fs.create_project("proj-2", "emp-alice", access=["emp-bob", "emp-carol"])
        manifest = fs._load_manifest("proj-2")
        assert "emp-alice" in manifest["access"]
        assert "emp-bob" in manifest["access"]
        assert "emp-carol" in manifest["access"]

    def test_creator_always_in_access(self, fs):
        fs.create_project("proj-3", "emp-alice", access=["emp-bob"])
        manifest = fs._load_manifest("proj-3")
        assert manifest["access"][0] == "emp-alice"


# --- Publish and read ---

class TestPublishRead:
    def test_publish_returns_notification(self, fs):
        fs.create_project("proj-1", "emp-alice")
        notif = fs.publish("proj-1", "readme.md", "# Hello", "emp-alice", "Alice", "initial commit")
        assert notif["type"] == "file_published"
        assert notif["project"] == "proj-1"
        assert notif["file_name"] == "readme.md"
        assert notif["author_id"] == "emp-alice"
        assert notif["author_name"] == "Alice"
        assert notif["message"] == "initial commit"
        assert "timestamp" in notif

    def test_read_text_file(self, fs):
        fs.create_project("proj-1", "emp-alice")
        fs.publish("proj-1", "notes.txt", "hello world", "emp-alice", "Alice")
        content = fs.read("proj-1", "notes.txt", "emp-alice")
        assert content == "hello world"

    def test_read_binary_file(self, fs):
        fs.create_project("proj-1", "emp-alice")
        data = b"\x00\x01\x02\xff"
        fs.publish("proj-1", "data.bin", data, "emp-alice", "Alice")
        result = fs.read("proj-1", "data.bin", "emp-alice")
        assert result == data

    def test_publish_auto_adds_access(self, fs):
        fs.create_project("proj-1", "emp-alice")
        # emp-bob not in access list initially
        fs.publish("proj-1", "file.txt", "content", "emp-bob", "Bob")
        manifest = fs._load_manifest("proj-1")
        assert "emp-bob" in manifest["access"]

    def test_read_nonexistent_file(self, fs):
        fs.create_project("proj-1", "emp-alice")
        with pytest.raises(FileNotFoundError):
            fs.read("proj-1", "nope.txt", "emp-alice")


# --- Access control ---

class TestAccessControl:
    def test_read_denied_without_access(self, fs):
        fs.create_project("proj-1", "emp-alice")
        fs.publish("proj-1", "secret.txt", "top secret", "emp-alice", "Alice")
        with pytest.raises(AccessDeniedError):
            fs.read("proj-1", "secret.txt", "emp-intruder")

    def test_list_denied_without_access(self, fs):
        fs.create_project("proj-1", "emp-alice")
        with pytest.raises(AccessDeniedError):
            fs.list_files("proj-1", "emp-intruder")

    def test_add_and_remove_access(self, fs):
        fs.create_project("proj-1", "emp-alice")
        fs.publish("proj-1", "doc.txt", "data", "emp-alice", "Alice")

        # Initially denied
        with pytest.raises(AccessDeniedError):
            fs.read("proj-1", "doc.txt", "emp-bob")

        # Grant access
        fs.add_access("proj-1", "emp-bob")
        assert fs.read("proj-1", "doc.txt", "emp-bob") == "data"

        # Revoke access
        fs.remove_access("proj-1", "emp-bob")
        with pytest.raises(AccessDeniedError):
            fs.read("proj-1", "doc.txt", "emp-bob")

    def test_add_access_idempotent(self, fs):
        fs.create_project("proj-1", "emp-alice")
        fs.add_access("proj-1", "emp-bob")
        fs.add_access("proj-1", "emp-bob")
        manifest = fs._load_manifest("proj-1")
        assert manifest["access"].count("emp-bob") == 1


# --- Listing ---

class TestListing:
    def test_list_files(self, fs):
        fs.create_project("proj-1", "emp-alice")
        fs.publish("proj-1", "a.txt", "aaa", "emp-alice", "Alice", "first")
        fs.publish("proj-1", "b.txt", "bbb", "emp-alice", "Alice", "second")

        files = fs.list_files("proj-1", "emp-alice")
        assert len(files) == 2
        names = {f["file_name"] for f in files}
        assert names == {"a.txt", "b.txt"}
        assert files[0]["author"] == "emp-alice"

    def test_list_projects_all(self, fs):
        fs.create_project("proj-a", "emp-alice")
        fs.create_project("proj-b", "emp-bob")
        projects = fs.list_projects()
        assert len(projects) == 2

    def test_list_projects_filtered(self, fs):
        fs.create_project("proj-a", "emp-alice")
        fs.create_project("proj-b", "emp-bob")
        projects = fs.list_projects(employee_id="emp-alice")
        assert len(projects) == 1
        assert projects[0]["project"] == "proj-a"


# --- Delete permissions ---

class TestDelete:
    def test_author_can_delete(self, fs):
        fs.create_project("proj-1", "emp-alice", access=["emp-bob"])
        fs.publish("proj-1", "file.txt", "content", "emp-bob", "Bob")
        fs.delete_file("proj-1", "file.txt", "emp-bob")
        assert fs.list_files("proj-1", "emp-bob") == []

    def test_creator_can_delete(self, fs):
        fs.create_project("proj-1", "emp-alice", access=["emp-bob"])
        fs.publish("proj-1", "file.txt", "content", "emp-bob", "Bob")
        fs.delete_file("proj-1", "file.txt", "emp-alice")
        assert fs.list_files("proj-1", "emp-alice") == []

    def test_other_cannot_delete(self, fs):
        fs.create_project("proj-1", "emp-alice", access=["emp-bob", "emp-carol"])
        fs.publish("proj-1", "file.txt", "content", "emp-bob", "Bob")
        with pytest.raises(AccessDeniedError):
            fs.delete_file("proj-1", "file.txt", "emp-carol")

    def test_delete_nonexistent_file(self, fs):
        fs.create_project("proj-1", "emp-alice")
        with pytest.raises(FileNotFoundError):
            fs.delete_file("proj-1", "nope.txt", "emp-alice")

    def test_delete_no_access(self, fs):
        fs.create_project("proj-1", "emp-alice")
        fs.publish("proj-1", "file.txt", "x", "emp-alice", "Alice")
        with pytest.raises(AccessDeniedError):
            fs.delete_file("proj-1", "file.txt", "emp-intruder")


# --- Notifications ---

class TestNotifications:
    def test_notifications_recorded(self, fs):
        fs.create_project("proj-1", "emp-alice")
        fs.publish("proj-1", "a.txt", "aaa", "emp-alice", "Alice", "first")
        fs.publish("proj-1", "b.txt", "bbb", "emp-alice", "Alice", "second")

        notifs = fs.get_notifications("proj-1")
        assert len(notifs) == 2
        assert notifs[0]["file_name"] == "a.txt"
        assert notifs[1]["file_name"] == "b.txt"

    def test_notifications_since_filter(self, fs):
        fs.create_project("proj-1", "emp-alice")
        n1 = fs.publish("proj-1", "a.txt", "aaa", "emp-alice", "Alice")
        ts = n1["timestamp"]
        fs.publish("proj-1", "b.txt", "bbb", "emp-alice", "Alice")

        notifs = fs.get_notifications("proj-1", since=ts)
        assert len(notifs) == 1
        assert notifs[0]["file_name"] == "b.txt"

    def test_project_not_found(self, fs):
        with pytest.raises(ProjectNotFoundError):
            fs.get_notifications("nonexistent")
