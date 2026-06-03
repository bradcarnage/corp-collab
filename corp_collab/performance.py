"""Corp-Collab: performance tracking with historical calibration.

Tracks task completion times per employee, calculates accuracy metrics,
and provides calibrated time estimates based on historical data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import yaml


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


# ── Data Structures ──────────────────────────────────────────────────────────


@dataclass
class TaskRecord:
    """Single completed task record for performance analysis."""

    task_id: str
    complexity_tier: str
    estimated_minutes: float
    actual_minutes: float
    started_at: str
    completed_at: str
    success: bool = True
    tags: list[str] = field(default_factory=list)

    @property
    def accuracy_ratio(self) -> float:
        """Ratio of actual to estimated. 1.0 = perfect, >1.0 = overran."""
        if self.estimated_minutes <= 0:
            return float("inf")
        return round(self.actual_minutes / self.estimated_minutes, 4)

    @property
    def overran(self) -> bool:
        """True if task took longer than estimated."""
        return self.actual_minutes > self.estimated_minutes

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "complexity_tier": self.complexity_tier,
            "estimated_minutes": self.estimated_minutes,
            "actual_minutes": self.actual_minutes,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "success": self.success,
            "tags": self.tags,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TaskRecord:
        return cls(
            task_id=data["task_id"],
            complexity_tier=data["complexity_tier"],
            estimated_minutes=data["estimated_minutes"],
            actual_minutes=data["actual_minutes"],
            started_at=data["started_at"],
            completed_at=data["completed_at"],
            success=data.get("success", True),
            tags=data.get("tags", []),
        )


@dataclass
class PerformanceSnapshot:
    """Aggregated performance metrics at a point in time."""

    employee_id: str
    total_tasks: int
    successful_tasks: int
    failed_tasks: int
    avg_accuracy_ratio: float
    median_accuracy_ratio: float
    overrun_rate: float  # fraction of tasks that overran
    avg_actual_minutes_by_tier: dict[str, float]
    calibration_factor: float  # multiply estimates by this for better accuracy
    generated_at: str = field(default_factory=_utcnow_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "employee_id": self.employee_id,
            "total_tasks": self.total_tasks,
            "successful_tasks": self.successful_tasks,
            "failed_tasks": self.failed_tasks,
            "avg_accuracy_ratio": self.avg_accuracy_ratio,
            "median_accuracy_ratio": self.median_accuracy_ratio,
            "overrun_rate": self.overrun_rate,
            "avg_actual_minutes_by_tier": self.avg_actual_minutes_by_tier,
            "calibration_factor": self.calibration_factor,
            "generated_at": self.generated_at,
        }


# ── Performance Tracker ──────────────────────────────────────────────────────


class PerformanceTracker:
    """Track and analyze employee task performance with historical calibration.

    Stores per-employee performance YAML files and provides calibrated
    time estimates based on historical accuracy.
    """

    def __init__(self, employee_id: str, base_path: Path | None = None) -> None:
        self.employee_id = employee_id
        self.base_path = base_path or Path.home() / ".claude-code" / "collab" / "employees"
        self._perf_dir = self.base_path / employee_id
        self._perf_dir.mkdir(parents=True, exist_ok=True)
        self._perf_file = self._perf_dir / "performance.yaml"

    # ── Persistence ──────────────────────────────────────────────────────

    def _load_records(self) -> list[dict[str, Any]]:
        if self._perf_file.exists():
            with open(self._perf_file) as f:
                data = yaml.safe_load(f)
            return data.get("records", []) if data else []
        return []

    def _save_records(self, records: list[dict[str, Any]]) -> None:
        with open(self._perf_file, "w") as f:
            yaml.dump(
                {"employee_id": self.employee_id, "records": records},
                f,
                default_flow_style=False,
                sort_keys=False,
            )

    # ── Record Management ────────────────────────────────────────────────

    def record_task(
        self,
        task_id: str,
        complexity_tier: str,
        estimated_minutes: float,
        actual_minutes: float,
        started_at: str | None = None,
        completed_at: str | None = None,
        success: bool = True,
        tags: list[str] | None = None,
    ) -> TaskRecord:
        """Record a completed task's performance data."""
        now = _utcnow_iso()
        record = TaskRecord(
            task_id=task_id,
            complexity_tier=complexity_tier.upper(),
            estimated_minutes=estimated_minutes,
            actual_minutes=actual_minutes,
            started_at=started_at or now,
            completed_at=completed_at or now,
            success=success,
            tags=tags or [],
        )

        records = self._load_records()
        # Deduplicate by task_id
        records = [r for r in records if r.get("task_id") != task_id]
        records.append(record.to_dict())
        self._save_records(records)
        return record

    def get_records(
        self,
        tier: str | None = None,
        success_only: bool = False,
        limit: int | None = None,
    ) -> list[TaskRecord]:
        """Retrieve task records with optional filtering."""
        raw = self._load_records()
        records = [TaskRecord.from_dict(r) for r in raw]

        if tier:
            records = [r for r in records if r.complexity_tier == tier.upper()]
        if success_only:
            records = [r for r in records if r.success]

        # Sort by completed_at descending (most recent first)
        records.sort(key=lambda r: r.completed_at, reverse=True)

        if limit:
            records = records[:limit]
        return records

    def clear_records(self) -> None:
        """Remove all performance records."""
        self._save_records([])

    # ── Analysis ─────────────────────────────────────────────────────────

    def _median(self, values: list[float]) -> float:
        """Calculate median of a list of floats."""
        if not values:
            return 0.0
        s = sorted(values)
        n = len(s)
        mid = n // 2
        if n % 2 == 0:
            return round((s[mid - 1] + s[mid]) / 2, 4)
        return round(s[mid], 4)

    def calibration_factor(self, tier: str | None = None, min_samples: int = 3) -> float:
        """Calculate calibration factor from historical accuracy ratios.

        The calibration factor is the median accuracy ratio — multiply
        future estimates by this to get calibrated estimates.

        Returns 1.0 if insufficient data (< min_samples).
        """
        records = self.get_records(tier=tier, success_only=True)
        if len(records) < min_samples:
            return 1.0

        ratios = [r.accuracy_ratio for r in records if r.accuracy_ratio != float("inf")]
        if not ratios:
            return 1.0

        return self._median(ratios)

    def calibrated_estimate(
        self,
        base_estimate: float,
        tier: str | None = None,
        min_samples: int = 3,
    ) -> float:
        """Return a calibrated time estimate based on historical performance.

        If employee historically takes 1.3x estimates, a 30min estimate
        becomes 39min.
        """
        factor = self.calibration_factor(tier=tier, min_samples=min_samples)
        return round(base_estimate * factor, 1)

    def snapshot(self) -> PerformanceSnapshot:
        """Generate a full performance snapshot for the employee."""
        records = self.get_records()

        if not records:
            return PerformanceSnapshot(
                employee_id=self.employee_id,
                total_tasks=0,
                successful_tasks=0,
                failed_tasks=0,
                avg_accuracy_ratio=0.0,
                median_accuracy_ratio=0.0,
                overrun_rate=0.0,
                avg_actual_minutes_by_tier={},
                calibration_factor=1.0,
            )

        successful = [r for r in records if r.success]
        failed = [r for r in records if not r.success]
        ratios = [r.accuracy_ratio for r in successful if r.accuracy_ratio != float("inf")]
        overruns = sum(1 for r in successful if r.overran)

        # Avg actual minutes by tier
        tier_totals: dict[str, list[float]] = {}
        for r in successful:
            tier_totals.setdefault(r.complexity_tier, []).append(r.actual_minutes)
        avg_by_tier = {
            tier: round(sum(vals) / len(vals), 1)
            for tier, vals in tier_totals.items()
        }

        return PerformanceSnapshot(
            employee_id=self.employee_id,
            total_tasks=len(records),
            successful_tasks=len(successful),
            failed_tasks=len(failed),
            avg_accuracy_ratio=round(sum(ratios) / len(ratios), 4) if ratios else 0.0,
            median_accuracy_ratio=self._median(ratios),
            overrun_rate=round(overruns / len(successful), 4) if successful else 0.0,
            avg_actual_minutes_by_tier=avg_by_tier,
            calibration_factor=self.calibration_factor(),
        )

    # ── Escalation Detection ─────────────────────────────────────────────

    def should_escalate(
        self,
        elapsed_minutes: float,
        estimated_minutes: float,
        tier: str | None = None,
        multiplier: float = 1.4,
    ) -> tuple[bool, str]:
        """Check if a running task should trigger escalation.

        Uses calibrated estimate if available, otherwise raw estimate.
        Returns (should_escalate, reason).
        """
        calibrated = self.calibrated_estimate(estimated_minutes, tier=tier)
        threshold = calibrated * multiplier

        if elapsed_minutes > threshold:
            return True, (
                f"Elapsed {elapsed_minutes:.0f}min exceeds threshold "
                f"{threshold:.0f}min (calibrated={calibrated:.0f}min × {multiplier}x)"
            )
        return False, f"Within threshold ({elapsed_minutes:.0f}/{threshold:.0f}min)"

    # ── Comparison ───────────────────────────────────────────────────────

    def accuracy_trend(self, window: int = 5) -> str:
        """Assess recent accuracy trend: 'improving', 'declining', or 'stable'.

        Compares the average accuracy ratio of the last *window* tasks
        to the previous *window* tasks.
        """
        records = self.get_records(success_only=True)
        if len(records) < window * 2:
            return "insufficient_data"

        recent = records[:window]
        previous = records[window : window * 2]

        recent_avg = sum(r.accuracy_ratio for r in recent) / len(recent)
        prev_avg = sum(r.accuracy_ratio for r in previous) / len(previous)

        # Closer to 1.0 is better
        recent_err = abs(recent_avg - 1.0)
        prev_err = abs(prev_avg - 1.0)

        diff = prev_err - recent_err  # positive = improving
        if diff > 0.1:
            return "improving"
        elif diff < -0.1:
            return "declining"
        return "stable"
