"""Corp-Collab: enhanced resource locking with exclusive, semaphore, and force-release support."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import fcntl
import yaml


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


@dataclass
class ResourceConfig:
    """Resource definition from config."""
    resource_id: str
    lock_type: str = 'exclusive'    # exclusive | semaphore
    max_holders: int = 1            # >1 for semaphore
    max_wait_seconds: int = 120
    max_hold_seconds: int = 600     # auto-release after this
    description: str = ''


@dataclass
class LockHolder:
    employee_id: str
    acquired_at: str
    task_id: Optional[str] = None


@dataclass
class QueueEntry:
    employee_id: str
    queued_at: str
    task_id: Optional[str] = None


class ResourceLockManager:
    """Manages resource locks with exclusive and semaphore support."""

    def __init__(self, base_path: Path | None = None) -> None:
        self.base_path = base_path or Path.home() / '.claude-code' / 'collab'
        self._locks_dir = self.base_path / 'locks'
        self._locks_dir.mkdir(parents=True, exist_ok=True)
        self._config: dict[str, ResourceConfig] = {}

    def register_resource(self, config: ResourceConfig) -> None:
        """Register a resource type."""
        self._config[config.resource_id] = config

    def _lock_path(self, resource_id: str) -> Path:
        return self._locks_dir / f'{resource_id}.yaml'

    def _load_lock(self, resource_id: str) -> dict:
        path = self._lock_path(resource_id)
        if path.exists():
            with open(path) as f:
                return yaml.safe_load(f) or {}
        config = self._config.get(resource_id)
        return {
            'resource_id': resource_id,
            'lock_type': config.lock_type if config else 'exclusive',
            'max_holders': config.max_holders if config else 1,
            'holders': [],
            'queue': [],
        }

    def _save_lock(self, resource_id: str, data: dict) -> None:
        path = self._lock_path(resource_id)
        with open(path, 'w') as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                yaml.dump(data, f, default_flow_style=False)
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)

    def acquire(self, resource_id: str, employee_id: str, task_id: str | None = None) -> dict:
        """Attempt to acquire a resource lock.

        Returns a dict with 'acquired' bool. If the resource is busy the caller
        is placed in a FIFO queue and the dict also contains 'queued' and 'position'.
        """
        data = self._load_lock(resource_id)
        holders = data.get('holders', [])
        queue = data.get('queue', [])
        max_h = data.get('max_holders', 1)
        lock_type = data.get('lock_type', 'exclusive')

        # Already holding?
        for h in holders:
            if h['employee_id'] == employee_id:
                return {'acquired': True, 'already_held': True, 'resource_id': resource_id}

        # Already in queue?
        for i, q in enumerate(queue):
            if q['employee_id'] == employee_id:
                return {'acquired': False, 'queued': True, 'position': i + 1, 'resource_id': resource_id}

        if len(holders) < max_h:
            holders.append({
                'employee_id': employee_id,
                'acquired_at': _utcnow_iso(),
                'task_id': task_id,
            })
            data['holders'] = holders
            self._save_lock(resource_id, data)
            return {'acquired': True, 'resource_id': resource_id, 'lock_type': lock_type}
        else:
            queue.append({
                'employee_id': employee_id,
                'queued_at': _utcnow_iso(),
                'task_id': task_id,
            })
            data['queue'] = queue
            self._save_lock(resource_id, data)
            current_holder = holders[0]['employee_id'] if holders else None
            return {
                'acquired': False, 'queued': True, 'position': len(queue),
                'resource_id': resource_id, 'current_holder': current_holder,
            }

    def release(self, resource_id: str, employee_id: str, notify: bool = True) -> dict:
        """Release a resource lock. Promotes next in queue if any."""
        data = self._load_lock(resource_id)
        holders = data.get('holders', [])
        queue = data.get('queue', [])

        new_holders = [h for h in holders if h['employee_id'] != employee_id]
        if len(new_holders) == len(holders):
            return {'released': False, 'error': 'not holding resource', 'resource_id': resource_id}

        promoted = None
        if queue:
            next_entry = queue.pop(0)
            promoted = next_entry['employee_id']
            new_holders.append({
                'employee_id': promoted,
                'acquired_at': _utcnow_iso(),
                'task_id': next_entry.get('task_id'),
            })

            if notify and promoted:
                try:
                    from corp_collab.mailbox import Mailbox
                    db_path = self.base_path / 'employees' / promoted / 'mailbox.db'
                    mailbox = Mailbox(promoted, db_path=db_path)
                    mailbox.send(
                        to_id=promoted, to_name=promoted, channel='im',
                        body=f'Resource "{resource_id}" is now available. You have been promoted from queue.',
                        from_id='system', from_name='Resource Manager',
                    )
                    mailbox.close()
                except Exception:
                    pass  # best-effort notification

        data['holders'] = new_holders
        data['queue'] = queue
        self._save_lock(resource_id, data)

        return {'released': True, 'resource_id': resource_id, 'promoted': promoted}

    def force_release(self, resource_id: str, manager_id: str, reason: str = 'manager override') -> dict:
        """Manager force-releases all holders on a resource."""
        data = self._load_lock(resource_id)
        old_holders = data.get('holders', [])[:]
        queue = data.get('queue', [])

        new_holders: list[dict] = []
        promoted: list[str] = []
        max_h = data.get('max_holders', 1)
        while queue and len(new_holders) < max_h:
            entry = queue.pop(0)
            new_holders.append({
                'employee_id': entry['employee_id'],
                'acquired_at': _utcnow_iso(),
                'task_id': entry.get('task_id'),
            })
            promoted.append(entry['employee_id'])

        data['holders'] = new_holders
        data['queue'] = queue
        self._save_lock(resource_id, data)

        return {
            'force_released': True,
            'resource_id': resource_id,
            'evicted': [h['employee_id'] for h in old_holders],
            'promoted': promoted,
            'reason': reason,
            'by': manager_id,
        }

    def status(self, resource_id: str) -> dict:
        """Get current lock status."""
        data = self._load_lock(resource_id)
        return {
            'resource_id': resource_id,
            'lock_type': data.get('lock_type', 'exclusive'),
            'max_holders': data.get('max_holders', 1),
            'holders': data.get('holders', []),
            'queue': data.get('queue', []),
            'available': len(data.get('holders', [])) < data.get('max_holders', 1),
        }

    def held_by(self, employee_id: str) -> list[str]:
        """List all resources held by an employee."""
        held: list[str] = []
        for path in self._locks_dir.glob('*.yaml'):
            data = yaml.safe_load(path.read_text()) or {}
            for h in data.get('holders', []):
                if h.get('employee_id') == employee_id:
                    held.append(data.get('resource_id', path.stem))
        return held
