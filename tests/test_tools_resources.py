"""Tests for resource acquisition and release tools."""

from pathlib import Path

import pytest
import yaml

from tools.acquire_resource import acquire_resource
from tools.release_resource import release_resource


@pytest.fixture
def base(tmp_path: Path) -> Path:
    """Provide a temp base_path for lock files."""
    return tmp_path


class TestAcquireExclusive:
    def test_acquire_available(self, base: Path):
        result = acquire_resource("db-main", "alice", lock_type="exclusive", base_path=base)
        assert result["acquired"] is True
        assert result["resource_id"] == "db-main"
        assert result["lock_type"] == "exclusive"

    def test_acquire_when_held_queues(self, base: Path):
        acquire_resource("db-main", "alice", lock_type="exclusive", base_path=base)
        result = acquire_resource("db-main", "bob", lock_type="exclusive", base_path=base)
        assert result["acquired"] is False
        assert result["position"] == 1
        assert result["holder"] == "alice"

    def test_acquire_already_held_by_self(self, base: Path):
        acquire_resource("db-main", "alice", lock_type="exclusive", base_path=base)
        result = acquire_resource("db-main", "alice", lock_type="exclusive", base_path=base)
        assert result["acquired"] is True
        assert result.get("already_held") is True


class TestReleaseExclusive:
    def test_release_and_promote(self, base: Path):
        acquire_resource("db-main", "alice", lock_type="exclusive", base_path=base)
        acquire_resource("db-main", "bob", lock_type="exclusive", base_path=base)

        result = release_resource("db-main", "alice", base_path=base)
        assert result["released"] is True
        assert result["promoted"] == "bob"

        # Verify bob is now the holder
        lock_file = base / "locks" / "db-main.yaml"
        data = yaml.safe_load(lock_file.read_text())
        assert len(data["holders"]) == 1
        assert data["holders"][0]["employee_id"] == "bob"
        assert len(data["queue"]) == 0

    def test_release_no_queue(self, base: Path):
        acquire_resource("db-main", "alice", lock_type="exclusive", base_path=base)
        result = release_resource("db-main", "alice", base_path=base)
        assert result["released"] is True
        assert result["promoted"] is None

    def test_release_not_holding(self, base: Path):
        acquire_resource("db-main", "alice", lock_type="exclusive", base_path=base)
        result = release_resource("db-main", "bob", base_path=base)
        assert result["error"] == "not holding resource"

    def test_release_nonexistent_resource(self, base: Path):
        result = release_resource("nonexistent", "alice", base_path=base)
        assert result["error"] == "not holding resource"


class TestSemaphore:
    def test_acquire_under_limit(self, base: Path):
        r1 = acquire_resource("shared-db", "alice", lock_type="semaphore", base_path=base, max_holders=3)
        r2 = acquire_resource("shared-db", "bob", lock_type="semaphore", base_path=base, max_holders=3)
        assert r1["acquired"] is True
        assert r2["acquired"] is True
        assert r2["lock_type"] == "semaphore"

    def test_acquire_at_max_queues(self, base: Path):
        acquire_resource("shared-db", "alice", lock_type="semaphore", base_path=base, max_holders=2)
        acquire_resource("shared-db", "bob", lock_type="semaphore", base_path=base, max_holders=2)
        result = acquire_resource("shared-db", "carol", lock_type="semaphore", base_path=base, max_holders=2)
        assert result["acquired"] is False
        assert result["position"] == 1

    def test_release_semaphore_promotes(self, base: Path):
        acquire_resource("shared-db", "alice", lock_type="semaphore", base_path=base, max_holders=2)
        acquire_resource("shared-db", "bob", lock_type="semaphore", base_path=base, max_holders=2)
        acquire_resource("shared-db", "carol", lock_type="semaphore", base_path=base, max_holders=2)

        result = release_resource("shared-db", "alice", base_path=base)
        assert result["released"] is True
        assert result["promoted"] == "carol"

        # Verify carol is now a holder
        lock_file = base / "locks" / "shared-db.yaml"
        data = yaml.safe_load(lock_file.read_text())
        holder_ids = [h["employee_id"] for h in data["holders"]]
        assert "carol" in holder_ids
        assert "bob" in holder_ids
        assert len(data["queue"]) == 0
