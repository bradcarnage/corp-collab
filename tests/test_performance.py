"""Tests for corp_collab.performance — historical calibration and tracking."""

import shutil
from pathlib import Path

import pytest

from corp_collab.performance import PerformanceTracker, TaskRecord, PerformanceSnapshot


@pytest.fixture
def tmp_base(tmp_path):
    return tmp_path / "employees"


@pytest.fixture
def tracker(tmp_base):
    return PerformanceTracker("emp-1234", base_path=tmp_base)


# ── TaskRecord ───────────────────────────────────────────────────────────────


class TestTaskRecord:
    def test_accuracy_ratio_normal(self):
        r = TaskRecord("t1", "C2", 30.0, 45.0, "2026-01-01T00:00:00Z", "2026-01-01T00:45:00Z")
        assert r.accuracy_ratio == 1.5

    def test_accuracy_ratio_perfect(self):
        r = TaskRecord("t1", "C1", 10.0, 10.0, "2026-01-01T00:00:00Z", "2026-01-01T00:10:00Z")
        assert r.accuracy_ratio == 1.0

    def test_accuracy_ratio_zero_estimate(self):
        r = TaskRecord("t1", "C1", 0.0, 5.0, "2026-01-01T00:00:00Z", "2026-01-01T00:05:00Z")
        assert r.accuracy_ratio == float("inf")

    def test_overran_true(self):
        r = TaskRecord("t1", "C2", 30.0, 45.0, "2026-01-01T00:00:00Z", "2026-01-01T00:45:00Z")
        assert r.overran is True

    def test_overran_false(self):
        r = TaskRecord("t1", "C2", 30.0, 20.0, "2026-01-01T00:00:00Z", "2026-01-01T00:20:00Z")
        assert r.overran is False

    def test_roundtrip(self):
        r = TaskRecord("t1", "C3", 60.0, 72.0, "2026-01-01T00:00:00Z", "2026-01-01T01:12:00Z", tags=["web"])
        d = r.to_dict()
        r2 = TaskRecord.from_dict(d)
        assert r2.task_id == "t1"
        assert r2.tags == ["web"]
        assert r2.success is True

    def test_failed_task(self):
        r = TaskRecord("t1", "C2", 30.0, 15.0, "2026-01-01T00:00:00Z", "2026-01-01T00:15:00Z", success=False)
        assert r.success is False


# ── PerformanceTracker — recording ───────────────────────────────────────────


class TestRecording:
    def test_record_and_retrieve(self, tracker):
        tracker.record_task("t1", "C2", 30.0, 35.0)
        records = tracker.get_records()
        assert len(records) == 1
        assert records[0].task_id == "t1"
        assert records[0].actual_minutes == 35.0

    def test_deduplication(self, tracker):
        tracker.record_task("t1", "C2", 30.0, 35.0)
        tracker.record_task("t1", "C2", 30.0, 40.0)  # update
        records = tracker.get_records()
        assert len(records) == 1
        assert records[0].actual_minutes == 40.0

    def test_multiple_records(self, tracker):
        for i in range(5):
            tracker.record_task(f"t{i}", "C2", 30.0, 30.0 + i * 5)
        records = tracker.get_records()
        assert len(records) == 5

    def test_filter_by_tier(self, tracker):
        tracker.record_task("t1", "C1", 5.0, 4.0)
        tracker.record_task("t2", "C2", 30.0, 35.0)
        tracker.record_task("t3", "C3", 60.0, 70.0)
        c2_only = tracker.get_records(tier="C2")
        assert len(c2_only) == 1
        assert c2_only[0].task_id == "t2"

    def test_filter_success_only(self, tracker):
        tracker.record_task("t1", "C2", 30.0, 35.0, success=True)
        tracker.record_task("t2", "C2", 30.0, 10.0, success=False)
        success = tracker.get_records(success_only=True)
        assert len(success) == 1

    def test_limit(self, tracker):
        for i in range(10):
            tracker.record_task(f"t{i}", "C2", 30.0, 30.0 + i)
        limited = tracker.get_records(limit=3)
        assert len(limited) == 3

    def test_clear_records(self, tracker):
        tracker.record_task("t1", "C2", 30.0, 35.0)
        tracker.clear_records()
        assert len(tracker.get_records()) == 0

    def test_case_insensitive_tier(self, tracker):
        tracker.record_task("t1", "c2", 30.0, 35.0)
        records = tracker.get_records()
        assert records[0].complexity_tier == "C2"

    def test_tags_stored(self, tracker):
        tracker.record_task("t1", "C2", 30.0, 35.0, tags=["web", "research"])
        records = tracker.get_records()
        assert records[0].tags == ["web", "research"]


# ── Calibration ──────────────────────────────────────────────────────────────


class TestCalibration:
    def _seed_records(self, tracker, ratios, tier="C2"):
        """Helper: seed tasks where actual/estimated matches given ratios."""
        for i, ratio in enumerate(ratios):
            tracker.record_task(
                f"t{i}", tier, 30.0, 30.0 * ratio,
                completed_at=f"2026-01-{i + 1:02d}T00:00:00Z",
            )

    def test_calibration_factor_insufficient_data(self, tracker):
        tracker.record_task("t1", "C2", 30.0, 45.0)
        assert tracker.calibration_factor() == 1.0

    def test_calibration_factor_with_data(self, tracker):
        # Ratios: 1.2, 1.3, 1.5 → median = 1.3
        self._seed_records(tracker, [1.2, 1.3, 1.5])
        assert tracker.calibration_factor() == 1.3

    def test_calibration_factor_even_count(self, tracker):
        # Ratios: 1.0, 1.2, 1.4, 1.6 → median = (1.2+1.4)/2 = 1.3
        self._seed_records(tracker, [1.0, 1.2, 1.4, 1.6])
        assert tracker.calibration_factor() == 1.3

    def test_calibration_factor_per_tier(self, tracker):
        self._seed_records(tracker, [1.0, 1.0, 1.0], tier="C1")
        self._seed_records(tracker, [2.0, 2.0, 2.0], tier="C2")
        assert tracker.calibration_factor(tier="C1") == 1.0
        assert tracker.calibration_factor(tier="C2") == 2.0

    def test_calibrated_estimate(self, tracker):
        self._seed_records(tracker, [1.2, 1.3, 1.5])
        # factor=1.3, base=30 → 39.0
        assert tracker.calibrated_estimate(30.0) == 39.0

    def test_calibrated_estimate_no_data(self, tracker):
        # No data → factor=1.0 → same as input
        assert tracker.calibrated_estimate(30.0) == 30.0

    def test_calibration_ignores_failures(self, tracker):
        self._seed_records(tracker, [1.0, 1.0, 1.0])
        tracker.record_task("fail1", "C2", 30.0, 300.0, success=False)
        assert tracker.calibration_factor() == 1.0

    def test_min_samples_threshold(self, tracker):
        self._seed_records(tracker, [2.0, 2.0])  # only 2
        assert tracker.calibration_factor(min_samples=3) == 1.0
        assert tracker.calibration_factor(min_samples=2) == 2.0


# ── Snapshot ─────────────────────────────────────────────────────────────────


class TestSnapshot:
    def test_empty_snapshot(self, tracker):
        snap = tracker.snapshot()
        assert snap.total_tasks == 0
        assert snap.calibration_factor == 1.0
        assert snap.avg_actual_minutes_by_tier == {}

    def test_full_snapshot(self, tracker):
        tracker.record_task("t1", "C1", 5.0, 4.0)
        tracker.record_task("t2", "C2", 30.0, 45.0)
        tracker.record_task("t3", "C2", 30.0, 36.0)
        tracker.record_task("t4", "C3", 60.0, 50.0, success=False)

        snap = tracker.snapshot()
        assert snap.total_tasks == 4
        assert snap.successful_tasks == 3
        assert snap.failed_tasks == 1
        assert "C1" in snap.avg_actual_minutes_by_tier
        assert "C2" in snap.avg_actual_minutes_by_tier
        assert snap.overrun_rate > 0  # t2 overran

    def test_snapshot_to_dict(self, tracker):
        tracker.record_task("t1", "C2", 30.0, 35.0)
        snap = tracker.snapshot()
        d = snap.to_dict()
        assert d["employee_id"] == "emp-1234"
        assert d["total_tasks"] == 1


# ── Escalation ───────────────────────────────────────────────────────────────


class TestEscalation:
    def test_no_escalation_within_threshold(self, tracker):
        should, reason = tracker.should_escalate(20.0, 30.0)
        assert should is False
        assert "Within threshold" in reason

    def test_escalation_beyond_threshold(self, tracker):
        # No calibration data → threshold = 30 * 1.4 = 42
        should, reason = tracker.should_escalate(50.0, 30.0)
        assert should is True
        assert "exceeds threshold" in reason

    def test_escalation_with_calibration(self, tracker):
        # Seed calibration: factor = 1.5
        for i in range(3):
            tracker.record_task(f"t{i}", "C2", 30.0, 45.0)
        # Calibrated = 30 * 1.5 = 45, threshold = 45 * 1.4 = 63
        should, _ = tracker.should_escalate(50.0, 30.0)
        assert should is False  # 50 < 63

        should, _ = tracker.should_escalate(70.0, 30.0)
        assert should is True  # 70 > 63

    def test_escalation_custom_multiplier(self, tracker):
        should, _ = tracker.should_escalate(35.0, 30.0, multiplier=1.1)
        assert should is True  # 35 > 30*1.1=33


# ── Accuracy Trend ───────────────────────────────────────────────────────────


class TestAccuracyTrend:
    def test_insufficient_data(self, tracker):
        tracker.record_task("t1", "C2", 30.0, 35.0)
        assert tracker.accuracy_trend() == "insufficient_data"

    def test_improving_trend(self, tracker):
        # Older tasks: way off (ratio ~2.0)
        for i in range(5):
            tracker.record_task(
                f"old{i}", "C2", 30.0, 60.0,
                completed_at=f"2026-01-{i + 1:02d}T00:00:00Z",
            )
        # Recent tasks: accurate (ratio ~1.0)
        for i in range(5):
            tracker.record_task(
                f"new{i}", "C2", 30.0, 30.0,
                completed_at=f"2026-02-{i + 1:02d}T00:00:00Z",
            )
        assert tracker.accuracy_trend() == "improving"

    def test_declining_trend(self, tracker):
        # Older tasks: accurate
        for i in range(5):
            tracker.record_task(
                f"old{i}", "C2", 30.0, 30.0,
                completed_at=f"2026-01-{i + 1:02d}T00:00:00Z",
            )
        # Recent tasks: way off
        for i in range(5):
            tracker.record_task(
                f"new{i}", "C2", 30.0, 60.0,
                completed_at=f"2026-02-{i + 1:02d}T00:00:00Z",
            )
        assert tracker.accuracy_trend() == "declining"

    def test_stable_trend(self, tracker):
        # All tasks similar accuracy
        for i in range(10):
            tracker.record_task(
                f"t{i}", "C2", 30.0, 33.0,
                completed_at=f"2026-01-{i + 1:02d}T00:00:00Z",
            )
        assert tracker.accuracy_trend() == "stable"
