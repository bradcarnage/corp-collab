"""Corp-Collab: manager orchestration — task assignment, employee selection, and roster management."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import yaml


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


@dataclass
class TaskAssignment:
    task_id: str
    description: str
    complexity_tier: str = 'C2'
    estimated_minutes: float = 30.0
    assigned_to: Optional[str] = None
    assigned_at: Optional[str] = None
    status: str = 'unassigned'  # unassigned | assigned | in_progress | completed | failed
    counter_estimate: Optional[float] = None

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}

    @classmethod
    def from_dict(cls, data: dict) -> TaskAssignment:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class ManagerAgent:
    """High-level manager orchestration."""

    def __init__(self, manager_id: str, base_path: Path | None = None) -> None:
        self.manager_id = manager_id
        self.base_path = base_path or Path.home() / '.claude-code' / 'collab'
        self._tasks_dir = self.base_path / 'managers' / manager_id / 'tasks'
        self._tasks_dir.mkdir(parents=True, exist_ok=True)

    @property
    def _employees_path(self) -> Path:
        return self.base_path / 'employees'

    def find_best_employee(self, role: str, skills: list[str] | None = None) -> Optional[dict]:
        """Find best available employee: prefer idle warm employees over new hires."""
        from corp_collab.roster import Roster
        roster = Roster(base_path=self.base_path)

        # 1. Check idle employees under this manager with matching role
        idle = roster.list_idle(manager_id=self.manager_id)
        role_matches = [e for e in idle if e.role == role]
        if role_matches:
            scored = [(roster.calculate_warmth(e), e) for e in role_matches]
            scored.sort(key=lambda x: x[0], reverse=True)
            best = scored[0]
            return {
                'employee': best[1],
                'warmth': best[0],
                'source': 'idle_roster',
                'needs_hire': False,
            }

        # 2. Check all idle employees for skill overlap
        if skills:
            all_idle = roster.list_idle(manager_id=self.manager_id)
            for emp in all_idle:
                emp_skills = set(emp.all_skills)
                overlap = emp_skills & set(skills)
                if overlap:
                    warmth = roster.calculate_warmth(emp)
                    return {
                        'employee': emp,
                        'warmth': warmth,
                        'source': 'skill_match',
                        'needs_hire': False,
                        'overlap': list(overlap),
                    }

        # 3. Check resumes of former employees
        resumes = roster.search_resumes(role=role, skills=skills)
        if resumes:
            return {'resume': resumes[0], 'source': 'resume', 'needs_hire': True, 'rehire': True}

        # 4. Need fresh hire
        return {'source': 'new_hire', 'needs_hire': True, 'rehire': False}

    def assign_task(self, task: TaskAssignment, employee_id: str) -> TaskAssignment:
        """Assign a task to an employee."""
        task.assigned_to = employee_id
        task.assigned_at = _utcnow_iso()
        task.status = 'assigned'

        # Save task
        path = self._tasks_dir / f'{task.task_id}.yaml'
        with open(path, 'w') as f:
            yaml.dump(task.to_dict(), f, default_flow_style=False)

        # Notify employee via email
        from corp_collab.mailbox import Mailbox
        db_path = self._employees_path / employee_id / 'mailbox.db'
        mailbox = Mailbox(employee_id, db_path=db_path)
        try:
            mailbox.send(
                to_id=employee_id,
                to_name=employee_id,
                channel='email',
                subject=f'Task Assignment: {task.task_id}',
                body=(
                    f'You have been assigned task {task.task_id}: {task.description}\n'
                    f'Complexity: {task.complexity_tier}, Estimated: {task.estimated_minutes}min'
                ),
                from_id=self.manager_id,
                from_name='Manager',
                priority='normal',
            )
        finally:
            mailbox.close()

        return task

    def accept_counter_estimate(self, task_id: str, counter_minutes: float) -> TaskAssignment:
        """Accept an employee's counter-estimate."""
        task = self.get_task(task_id)
        task.counter_estimate = counter_minutes
        task.estimated_minutes = counter_minutes
        path = self._tasks_dir / f'{task_id}.yaml'
        with open(path, 'w') as f:
            yaml.dump(task.to_dict(), f, default_flow_style=False)
        return task

    def get_task(self, task_id: str) -> TaskAssignment:
        path = self._tasks_dir / f'{task_id}.yaml'
        if not path.exists():
            raise FileNotFoundError(f'Task {task_id} not found')
        with open(path) as f:
            return TaskAssignment.from_dict(yaml.safe_load(f))

    def list_tasks(self, status: str | None = None) -> list[TaskAssignment]:
        tasks: list[TaskAssignment] = []
        for path in self._tasks_dir.glob('*.yaml'):
            data = yaml.safe_load(path.read_text()) or {}
            t = TaskAssignment.from_dict(data)
            if status and t.status != status:
                continue
            tasks.append(t)
        return tasks

    def complete_task(self, task_id: str) -> TaskAssignment:
        task = self.get_task(task_id)
        task.status = 'completed'
        path = self._tasks_dir / f'{task_id}.yaml'
        with open(path, 'w') as f:
            yaml.dump(task.to_dict(), f, default_flow_style=False)
        return task

    def roster_summary(self) -> dict:
        """Get summary of managed employees."""
        from corp_collab.roster import Roster
        roster = Roster(base_path=self.base_path)
        all_emps = roster.list_all(manager_id=self.manager_id)

        active = [e for e in all_emps if e.status == 'active']
        idle = [e for e in all_emps if e.status == 'idle']

        return {
            'total': len(all_emps),
            'active': len(active),
            'idle': len(idle),
            'active_employees': [
                {'id': e.id, 'name': e.full_name, 'task': e.current_task}
                for e in active
            ],
            'idle_employees': [
                {'id': e.id, 'name': e.full_name, 'warmth': roster.calculate_warmth(e)}
                for e in idle
            ],
        }
