"""Corp-Collab: hybrid burst spawner — launches agent sessions for employees."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional

import yaml


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


class BurstStatus(str, Enum):
    PENDING = 'pending'
    RUNNING = 'running'
    COMPLETED = 'completed'
    FAILED = 'failed'
    TIMEOUT = 'timeout'


@dataclass
class BurstConfig:
    """Configuration for a burst session."""
    employee_id: str
    task_id: str
    task_description: str
    tools: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    context: str = ''
    timeout_seconds: int = 600
    working_dir: Optional[str] = None
    environment: dict[str, str] = field(default_factory=dict)


@dataclass
class BurstResult:
    """Result of a completed burst."""
    burst_id: str
    employee_id: str
    task_id: str
    status: BurstStatus
    started_at: str
    completed_at: Optional[str] = None
    output: str = ''
    error: Optional[str] = None
    files_created: list[str] = field(default_factory=list)
    handoff_path: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            'burst_id': self.burst_id,
            'employee_id': self.employee_id,
            'task_id': self.task_id,
            'status': self.status.value,
            'started_at': self.started_at,
            'completed_at': self.completed_at,
            'output': self.output,
            'error': self.error,
            'files_created': self.files_created,
            'handoff_path': self.handoff_path,
        }

    @classmethod
    def from_dict(cls, data: dict) -> BurstResult:
        data = dict(data)
        data['status'] = BurstStatus(data['status'])
        return cls(**data)


class BurstSpawner:
    """Spawns agent sessions for employees in hybrid burst model."""

    def __init__(self, base_path: Path | None = None, dry_run: bool = False) -> None:
        self.base_path = base_path or Path.home() / '.claude-code' / 'collab'
        self.dry_run = dry_run
        self._bursts_dir = self.base_path / 'bursts'
        self._bursts_dir.mkdir(parents=True, exist_ok=True)
        self._active_bursts: dict[str, BurstResult] = {}

    def _burst_path(self, burst_id: str) -> Path:
        return self._bursts_dir / f'{burst_id}.yaml'

    @property
    def _employees_path(self) -> Path:
        return self.base_path / 'employees'

    def prepare_context(self, config: BurstConfig) -> str:
        """Build full context for burst: handoff + task + mailbox summary."""
        sections: list[str] = []

        # Load handoff from last burst (if exists)
        from corp_collab.handoff import HandoffGenerator
        try:
            handoff = HandoffGenerator.load_burst_handoff(
                config.employee_id, base_path=self._employees_path,
            )
            if handoff:
                sections.append(f'## Previous Handoff\n{handoff}')
        except Exception:
            pass

        # Load employee profile
        from corp_collab.employee import Employee
        try:
            emp = Employee.load(config.employee_id, base_path=self._employees_path)
            sections.append(
                f'## Your Identity\n'
                f'You are {emp.full_name} (ID: {emp.id}), role: {emp.role}\n'
                f'Skills: {", ".join(emp.all_skills)}'
            )
        except Exception:
            pass

        # Task description
        sections.append(f'## Current Task\nTask ID: {config.task_id}\n{config.task_description}')

        # Check pending messages
        from corp_collab.mailbox import Mailbox
        try:
            db_path = self._employees_path / config.employee_id / 'mailbox.db'
            mailbox = Mailbox(config.employee_id, db_path=db_path)
            unread_im = mailbox.count_unread('im')
            unread_email = mailbox.count_unread('email')
            if unread_im or unread_email:
                sections.append(f'## Pending Messages\nUnread IMs: {unread_im}, Unread emails: {unread_email}')
            mailbox.close()
        except Exception:
            pass

        # Additional context
        if config.context:
            sections.append(f'## Additional Context\n{config.context}')

        return '\n\n'.join(sections)

    def spawn(self, config: BurstConfig) -> BurstResult:
        """Spawn a burst session for an employee."""
        burst_id = f'burst-{uuid.uuid4().hex[:8]}'

        # Activate employee
        from corp_collab.employee import Employee
        try:
            emp = Employee.load(config.employee_id, base_path=self._employees_path)
            emp.activate(config.task_id)
            emp.save(base_path=self._employees_path)
        except Exception as e:
            return BurstResult(
                burst_id=burst_id,
                employee_id=config.employee_id,
                task_id=config.task_id,
                status=BurstStatus.FAILED,
                started_at=_utcnow_iso(),
                error=f'Failed to activate: {e}',
            )

        context = self.prepare_context(config)
        result = BurstResult(
            burst_id=burst_id,
            employee_id=config.employee_id,
            task_id=config.task_id,
            status=BurstStatus.RUNNING,
            started_at=_utcnow_iso(),
        )

        if self.dry_run:
            result.status = BurstStatus.COMPLETED
            result.completed_at = _utcnow_iso()
            result.output = f'[DRY RUN] Would spawn burst for {emp.full_name} on task {config.task_id}'

        # Save burst record
        self._active_bursts[burst_id] = result
        with open(self._burst_path(burst_id), 'w') as f:
            yaml.dump(result.to_dict(), f, default_flow_style=False)

        return result

    def complete_burst(
        self,
        burst_id: str,
        output: str = '',
        files: list[str] | None = None,
        error: str | None = None,
    ) -> BurstResult:
        """Mark a burst as completed and deactivate employee."""
        result = self.get_burst(burst_id)
        result.status = BurstStatus.COMPLETED if not error else BurstStatus.FAILED
        result.completed_at = _utcnow_iso()
        result.output = output
        result.error = error
        result.files_created = files or []

        # Deactivate employee
        from corp_collab.employee import Employee
        try:
            emp = Employee.load(result.employee_id, base_path=self._employees_path)
            if not error:
                emp.complete_task()
            emp.deactivate()
            emp.save(base_path=self._employees_path)
        except Exception:
            pass

        # Save burst record
        with open(self._burst_path(burst_id), 'w') as f:
            yaml.dump(result.to_dict(), f, default_flow_style=False)

        self._active_bursts.pop(burst_id, None)
        return result

    def get_burst(self, burst_id: str) -> BurstResult:
        """Load a burst by ID."""
        if burst_id in self._active_bursts:
            return self._active_bursts[burst_id]
        path = self._burst_path(burst_id)
        if not path.exists():
            raise FileNotFoundError(f'Burst {burst_id} not found')
        with open(path) as f:
            data = yaml.safe_load(f)
        return BurstResult.from_dict(data)

    def list_active(self) -> list[BurstResult]:
        """List currently running bursts."""
        active: list[BurstResult] = []
        for path in self._bursts_dir.glob('burst-*.yaml'):
            data = yaml.safe_load(path.read_text()) or {}
            if data.get('status') == 'running':
                active.append(BurstResult.from_dict(data))
        return active

    def list_history(self, employee_id: str | None = None, limit: int = 20) -> list[BurstResult]:
        """List burst history, optionally filtered by employee_id."""
        results: list[BurstResult] = []
        for path in self._bursts_dir.glob('burst-*.yaml'):
            data = yaml.safe_load(path.read_text()) or {}
            if employee_id and data.get('employee_id') != employee_id:
                continue
            results.append(BurstResult.from_dict(data))
        return sorted(results, key=lambda r: r.started_at, reverse=True)[:limit]
