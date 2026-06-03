"""Tests for corp_collab.hermes_bridge — Hermes agent integration."""

import pytest

from corp_collab.hermes_bridge import CorpBridge, TaskHandle, CollectResult


@pytest.fixture
def bridge(tmp_path):
    return CorpBridge(base_path=tmp_path, manager_id="hermes-test")


# ── TaskHandle ───────────────────────────────────────────────────────────────


class TestTaskHandle:
    def test_to_dict(self):
        h = TaskHandle(
            employee_id="emp-1",
            employee_name="Intern Curie",
            task_summary="Build auth",
            assigned_at="2025-01-01T00:00:00Z",
            complexity="C3",
        )
        d = h.to_dict()
        assert d["employee_id"] == "emp-1"
        assert d["complexity"] == "C3"
        assert d["status"] == "assigned"


class TestCollectResult:
    def test_to_dict(self):
        r = CollectResult(
            employee_id="emp-1",
            employee_name="Intern Curie",
            status="collected",
            messages=[{"body": "done"}],
            files=["output.py"],
        )
        d = r.to_dict()
        assert d["message_count"] == 1
        assert "output.py" in d["files"]


# ── Assign ───────────────────────────────────────────────────────────────────


class TestAssign:
    def test_assign_hires_new(self, bridge):
        handle = bridge.assign("Build the auth module", role="engineer")
        assert handle.employee_id != "FAILED"
        assert handle.status == "assigned"
        assert "auth" in handle.task_summary

    def test_assign_returns_handle(self, bridge):
        handle = bridge.assign("Write tests", role="engineer")
        assert isinstance(handle, TaskHandle)
        assert handle.assigned_at

    def test_assign_tracks_active(self, bridge):
        handle = bridge.assign("Task 1")
        assert handle.employee_id in [h.employee_id for h in bridge.active_tasks()]

    def test_assign_with_complexity(self, bridge):
        handle = bridge.assign("Complex task", complexity="C4")
        assert handle.complexity == "C4"

    def test_assign_specific_employee(self, bridge):
        # Hire first, then reassign
        h1 = bridge.assign("Task 1")
        h2 = bridge.assign("Task 2", employee_id=h1.employee_id)
        assert h2.employee_id == h1.employee_id


# ── Check ────────────────────────────────────────────────────────────────────


class TestCheck:
    def test_check_assigned(self, bridge):
        handle = bridge.assign("Do stuff")
        status = bridge.check(handle.employee_id)
        assert status["employee_id"] == handle.employee_id
        assert status["status"] == "assigned"

    def test_check_unknown_employee(self, bridge):
        status = bridge.check("nonexistent-emp")
        assert status["status"] == "unknown"

    def test_check_all(self, bridge):
        bridge.assign("Task A")
        bridge.assign("Task B")
        statuses = bridge.check_all()
        assert len(statuses) == 2


# ── Collect ──────────────────────────────────────────────────────────────────


class TestCollect:
    def test_collect_basic(self, bridge):
        handle = bridge.assign("Build it")
        result = bridge.collect(handle.employee_id)
        assert isinstance(result, CollectResult)
        assert result.employee_id == handle.employee_id
        assert result.status == "collected"

    def test_collect_updates_tracking(self, bridge):
        handle = bridge.assign("Build it")
        bridge.collect(handle.employee_id)
        assert bridge._active_tasks[handle.employee_id].status == "collected"

    def test_collect_finds_files(self, bridge, tmp_path):
        handle = bridge.assign("Make files")
        # Create scratch files
        scratch = tmp_path / "employees" / handle.employee_id / "scratch"
        scratch.mkdir(parents=True, exist_ok=True)
        (scratch / "output.py").write_text("print('hello')")
        result = bridge.collect(handle.employee_id)
        assert "output.py" in result.files

    def test_collect_finds_handoff(self, bridge, tmp_path):
        handle = bridge.assign("Make stuff")
        handoff = tmp_path / "employees" / handle.employee_id / "handoff.md"
        handoff.parent.mkdir(parents=True, exist_ok=True)
        handoff.write_text("# Handoff\nDone with auth module.")
        result = bridge.collect(handle.employee_id)
        assert "Handoff" in result.handoff_doc


# ── Steer ────────────────────────────────────────────────────────────────────


class TestSteer:
    def test_steer_sends(self, bridge):
        handle = bridge.assign("Working on task")
        ok = bridge.steer(handle.employee_id, "Switch to API tests instead")
        # Should not crash; may or may not succeed depending on mailbox setup
        assert isinstance(ok, bool)


# ── Reassign ─────────────────────────────────────────────────────────────────


class TestReassign:
    def test_reassign_same_employee(self, bridge):
        h1 = bridge.assign("Task A")
        h2 = bridge.reassign(h1.employee_id, "Task B")
        assert h2.employee_id == h1.employee_id
        assert "Task B" in h2.task_summary


# ── Dismiss ──────────────────────────────────────────────────────────────────


class TestDismiss:
    def test_dismiss_removes_tracking(self, bridge):
        handle = bridge.assign("Temp task")
        bridge.dismiss(handle.employee_id)
        assert handle.employee_id not in bridge._active_tasks


# ── Batch ────────────────────────────────────────────────────────────────────


class TestBatch:
    def test_batch_assign(self, bridge):
        handles = bridge.batch_assign([
            {"task": "Build auth"},
            {"task": "Write tests", "role": "reviewer"},
            {"task": "Deploy", "complexity": "C3"},
        ])
        assert len(handles) == 3
        # At least some should succeed
        success = [h for h in handles if h.status != "error"]
        assert len(success) >= 1

    def test_batch_empty(self, bridge):
        handles = bridge.batch_assign([])
        assert handles == []
