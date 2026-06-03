"""Tests for corp_collab.spawner."""

import pytest
import yaml

from corp_collab.employee import Employee
from corp_collab.spawner import BurstConfig, BurstResult, BurstSpawner, BurstStatus
from corp_collab.handoff import HandoffGenerator


def _make_employee(tmp_path, emp_id='emp-01', role='engineer', status='idle', tasks=0, manager='mgr-01'):
    """Helper: create and save an employee profile."""
    emp_dir = tmp_path / 'employees' / emp_id
    emp_dir.mkdir(parents=True, exist_ok=True)
    profile = {
        'id': emp_id,
        'nickname': 'TestBot',
        'title': 'Engineer',
        'full_name': 'Engineer TestBot',
        'role': role,
        'skills': ['terminal', 'file', 'code_exec'],
        'granted_skills': [],
        'can_delegate': False,
        'max_subordinates': 0,
        'hired_by': manager,
        'hired_at': '2025-01-01T00:00:00Z',
        'last_active': '2025-01-01T00:00:00Z',
        'status': status,
        'current_task': None,
        'custom_manager_title': None,
        'tasks_completed_under_manager': tasks,
        'promotion_level': 'role',
    }
    with open(emp_dir / 'profile.yaml', 'w') as f:
        yaml.dump(profile, f, default_flow_style=False)
    return emp_id


@pytest.fixture
def spawner(tmp_path):
    return BurstSpawner(base_path=tmp_path, dry_run=True)


@pytest.fixture
def emp(tmp_path):
    return _make_employee(tmp_path)


# ── Dry-run spawn ────────────────────────────────────────────────────────────


def test_spawn_dry_run_completes(spawner, emp, tmp_path):
    config = BurstConfig(employee_id=emp, task_id='t-1', task_description='Fix the bug')
    result = spawner.spawn(config)
    assert result.status == BurstStatus.COMPLETED
    assert '[DRY RUN]' in result.output
    assert result.burst_id.startswith('burst-')


def test_spawn_activates_employee(spawner, emp, tmp_path):
    config = BurstConfig(employee_id=emp, task_id='t-1', task_description='Fix the bug')
    spawner.spawn(config)
    loaded = Employee.load(emp, base_path=tmp_path / 'employees')
    # dry_run completes instantly but employee was activated during spawn
    # (dry_run doesn't deactivate, only complete_burst does)
    assert loaded.status == 'active'
    assert loaded.current_task == 't-1'


# ── complete_burst ───────────────────────────────────────────────────────────


def test_complete_burst_deactivates(tmp_path):
    emp_id = _make_employee(tmp_path, status='idle')
    spawner = BurstSpawner(base_path=tmp_path, dry_run=False)
    config = BurstConfig(employee_id=emp_id, task_id='t-2', task_description='Deploy')
    result = spawner.spawn(config)
    assert result.status == BurstStatus.RUNNING

    completed = spawner.complete_burst(result.burst_id, output='Done!')
    assert completed.status == BurstStatus.COMPLETED
    loaded = Employee.load(emp_id, base_path=tmp_path / 'employees')
    assert loaded.status == 'idle'


def test_complete_burst_increments_task_count(tmp_path):
    emp_id = _make_employee(tmp_path, tasks=5)
    spawner = BurstSpawner(base_path=tmp_path, dry_run=False)
    config = BurstConfig(employee_id=emp_id, task_id='t-3', task_description='Test')
    result = spawner.spawn(config)
    spawner.complete_burst(result.burst_id, output='All good')
    loaded = Employee.load(emp_id, base_path=tmp_path / 'employees')
    assert loaded.tasks_completed_under_manager == 6


def test_complete_burst_with_error(tmp_path):
    emp_id = _make_employee(tmp_path)
    spawner = BurstSpawner(base_path=tmp_path, dry_run=False)
    config = BurstConfig(employee_id=emp_id, task_id='t-4', task_description='Crash')
    result = spawner.spawn(config)
    completed = spawner.complete_burst(result.burst_id, error='segfault')
    assert completed.status == BurstStatus.FAILED
    assert completed.error == 'segfault'


# ── prepare_context ──────────────────────────────────────────────────────────


def test_prepare_context_includes_task(spawner, emp):
    config = BurstConfig(employee_id=emp, task_id='t-5', task_description='Write unit tests')
    ctx = spawner.prepare_context(config)
    assert 'Write unit tests' in ctx
    assert 't-5' in ctx


def test_prepare_context_includes_identity(spawner, emp):
    config = BurstConfig(employee_id=emp, task_id='t-6', task_description='Something')
    ctx = spawner.prepare_context(config)
    assert 'TestBot' in ctx
    assert emp in ctx


def test_prepare_context_loads_handoff(tmp_path):
    emp_id = _make_employee(tmp_path)
    # Write a handoff file
    handoff_content = '# Previous work\nCompleted step 1.'
    emp_employees = tmp_path / 'employees'
    HandoffGenerator.save_burst_handoff(emp_id, handoff_content, base_path=emp_employees)

    spawner = BurstSpawner(base_path=tmp_path, dry_run=True)
    config = BurstConfig(employee_id=emp_id, task_id='t-7', task_description='Continue')
    ctx = spawner.prepare_context(config)
    assert 'Previous Handoff' in ctx
    assert 'Completed step 1' in ctx


def test_prepare_context_includes_additional(spawner, emp):
    config = BurstConfig(employee_id=emp, task_id='t-8', task_description='X', context='Extra info here')
    ctx = spawner.prepare_context(config)
    assert 'Extra info here' in ctx


# ── get_burst ────────────────────────────────────────────────────────────────


def test_get_burst_not_found(spawner):
    with pytest.raises(FileNotFoundError):
        spawner.get_burst('burst-nonexistent')


# ── list_active ──────────────────────────────────────────────────────────────


def test_list_active_filters_running(tmp_path):
    emp1 = _make_employee(tmp_path, emp_id='emp-a1')
    emp2 = _make_employee(tmp_path, emp_id='emp-a2')
    spawner = BurstSpawner(base_path=tmp_path, dry_run=False)
    r1 = spawner.spawn(BurstConfig(employee_id=emp1, task_id='t-10', task_description='A'))
    r2 = spawner.spawn(BurstConfig(employee_id=emp2, task_id='t-11', task_description='B'))
    spawner.complete_burst(r2.burst_id, output='done')

    active = spawner.list_active()
    assert len(active) == 1
    assert active[0].employee_id == emp1


# ── list_history ─────────────────────────────────────────────────────────────


def test_list_history_filters_by_employee(tmp_path):
    emp1 = _make_employee(tmp_path, emp_id='emp-h1')
    emp2 = _make_employee(tmp_path, emp_id='emp-h2')
    spawner = BurstSpawner(base_path=tmp_path, dry_run=True)
    spawner.spawn(BurstConfig(employee_id=emp1, task_id='t-20', task_description='X'))
    spawner.spawn(BurstConfig(employee_id=emp2, task_id='t-21', task_description='Y'))
    spawner.spawn(BurstConfig(employee_id=emp1, task_id='t-22', task_description='Z'))

    history = spawner.list_history(employee_id=emp1)
    assert len(history) == 2
    assert all(r.employee_id == emp1 for r in history)


# ── Invalid employee ─────────────────────────────────────────────────────────


def test_spawn_invalid_employee_fails_gracefully(tmp_path):
    spawner = BurstSpawner(base_path=tmp_path, dry_run=True)
    config = BurstConfig(employee_id='emp-ghost', task_id='t-99', task_description='Will fail')
    result = spawner.spawn(config)
    assert result.status == BurstStatus.FAILED
    assert 'Failed to activate' in result.error


# ── BurstResult serialization ────────────────────────────────────────────────


def test_burst_result_roundtrip():
    r = BurstResult(
        burst_id='burst-abc', employee_id='emp-01', task_id='t-1',
        status=BurstStatus.COMPLETED, started_at='2025-01-01T00:00:00Z',
        completed_at='2025-01-01T00:01:00Z', output='ok',
    )
    d = r.to_dict()
    r2 = BurstResult.from_dict(d)
    assert r2.burst_id == r.burst_id
    assert r2.status == BurstStatus.COMPLETED
