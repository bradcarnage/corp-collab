"""Tests for corp_collab.resource_lock."""

import pytest
import yaml

from corp_collab.resource_lock import ResourceConfig, ResourceLockManager


@pytest.fixture
def lock_mgr(tmp_path):
    return ResourceLockManager(base_path=tmp_path)


# ── Acquire exclusive ─────────────────────────────────────────────────────────


def test_acquire_exclusive(lock_mgr):
    result = lock_mgr.acquire('db', 'emp-01')
    assert result['acquired'] is True
    assert result['resource_id'] == 'db'


def test_acquire_exclusive_blocks_second(lock_mgr):
    lock_mgr.acquire('db', 'emp-01')
    result = lock_mgr.acquire('db', 'emp-02')
    assert result['acquired'] is False
    assert result['queued'] is True
    assert result['position'] == 1
    assert result['current_holder'] == 'emp-01'


# ── Queue and promote ────────────────────────────────────────────────────────


def test_release_promotes_next(lock_mgr):
    lock_mgr.acquire('db', 'emp-01')
    lock_mgr.acquire('db', 'emp-02', task_id='t-1')
    result = lock_mgr.release('db', 'emp-01', notify=False)
    assert result['released'] is True
    assert result['promoted'] == 'emp-02'
    # emp-02 should now be holding
    status = lock_mgr.status('db')
    assert len(status['holders']) == 1
    assert status['holders'][0]['employee_id'] == 'emp-02'


def test_release_no_queue(lock_mgr):
    lock_mgr.acquire('db', 'emp-01')
    result = lock_mgr.release('db', 'emp-01', notify=False)
    assert result['released'] is True
    assert result['promoted'] is None
    assert lock_mgr.status('db')['available'] is True


# ── Force release ────────────────────────────────────────────────────────────


def test_force_release_evicts_all(lock_mgr):
    lock_mgr.acquire('db', 'emp-01')
    lock_mgr.acquire('db', 'emp-02')
    result = lock_mgr.force_release('db', 'mgr-01', reason='deadlock fix')
    assert result['force_released'] is True
    assert 'emp-01' in result['evicted']
    assert result['reason'] == 'deadlock fix'
    assert result['by'] == 'mgr-01'


def test_force_release_promotes_from_queue(lock_mgr):
    lock_mgr.acquire('db', 'emp-01')
    lock_mgr.acquire('db', 'emp-02')
    lock_mgr.acquire('db', 'emp-03')
    result = lock_mgr.force_release('db', 'mgr-01')
    # emp-01 evicted, emp-02 was queued -> promoted
    assert 'emp-01' in result['evicted']
    assert 'emp-02' in result['promoted']
    status = lock_mgr.status('db')
    assert status['holders'][0]['employee_id'] == 'emp-02'


# ── Semaphore (multi-holder) ─────────────────────────────────────────────────


def test_semaphore_multi_holder(lock_mgr):
    lock_mgr.register_resource(ResourceConfig(
        resource_id='pool', lock_type='semaphore', max_holders=3,
    ))
    r1 = lock_mgr.acquire('pool', 'emp-01')
    r2 = lock_mgr.acquire('pool', 'emp-02')
    r3 = lock_mgr.acquire('pool', 'emp-03')
    assert r1['acquired'] is True
    assert r2['acquired'] is True
    assert r3['acquired'] is True

    # 4th should queue
    r4 = lock_mgr.acquire('pool', 'emp-04')
    assert r4['acquired'] is False
    assert r4['queued'] is True


# ── Status ───────────────────────────────────────────────────────────────────


def test_status_shows_correct_state(lock_mgr):
    lock_mgr.acquire('db', 'emp-01', task_id='t-1')
    lock_mgr.acquire('db', 'emp-02')
    s = lock_mgr.status('db')
    assert s['resource_id'] == 'db'
    assert s['lock_type'] == 'exclusive'
    assert s['max_holders'] == 1
    assert len(s['holders']) == 1
    assert len(s['queue']) == 1
    assert s['available'] is False


# ── held_by ──────────────────────────────────────────────────────────────────


def test_held_by_finds_resources(lock_mgr):
    lock_mgr.acquire('db', 'emp-01')
    lock_mgr.acquire('cache', 'emp-01')
    lock_mgr.acquire('queue', 'emp-02')
    held = lock_mgr.held_by('emp-01')
    assert set(held) == {'db', 'cache'}


# ── Idempotent behaviours ───────────────────────────────────────────────────


def test_already_holding_idempotent(lock_mgr):
    lock_mgr.acquire('db', 'emp-01')
    result = lock_mgr.acquire('db', 'emp-01')
    assert result['acquired'] is True
    assert result['already_held'] is True


def test_already_queued_idempotent(lock_mgr):
    lock_mgr.acquire('db', 'emp-01')
    lock_mgr.acquire('db', 'emp-02')
    result = lock_mgr.acquire('db', 'emp-02')
    assert result['acquired'] is False
    assert result['queued'] is True
    assert result['position'] == 1


# ── Error cases ──────────────────────────────────────────────────────────────


def test_release_when_not_holding(lock_mgr):
    result = lock_mgr.release('db', 'emp-99', notify=False)
    assert result['released'] is False
    assert result['error'] == 'not holding resource'


# ── Resource config registration ─────────────────────────────────────────────


def test_registered_config_applies(lock_mgr):
    lock_mgr.register_resource(ResourceConfig(
        resource_id='gpu', lock_type='semaphore', max_holders=2, description='GPU pool',
    ))
    lock_mgr.acquire('gpu', 'emp-01')
    lock_mgr.acquire('gpu', 'emp-02')
    r = lock_mgr.acquire('gpu', 'emp-03')
    assert r['acquired'] is False
    s = lock_mgr.status('gpu')
    assert s['max_holders'] == 2
