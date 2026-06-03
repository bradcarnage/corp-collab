#!/usr/bin/env python3
"""Corp-Collab Dashboard — web UI + API server.

Serves a single-page dark-themed dashboard with live data from the corp-collab system.
Reads from ~/.claude-code/collab/ data dirs.

Usage:
    python3 dashboard.py [--port 8090] [--host 0.0.0.0]
"""

import argparse
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import yaml

BASE_PATH = Path.home() / ".claude-code" / "collab"


def _load_registry() -> dict:
    reg_file = BASE_PATH / "registry.yaml"
    if not reg_file.exists():
        return {}
    with open(reg_file) as f:
        return yaml.safe_load(f) or {}


def _load_employee(emp_id: str) -> dict | None:
    profile = BASE_PATH / "employees" / emp_id / "profile.yaml"
    if not profile.exists():
        return None
    with open(profile) as f:
        data = yaml.safe_load(f) or {}
    data["id"] = emp_id
    return data


def _load_mailbox_stats(emp_id: str) -> dict:
    db_path = BASE_PATH / "mailboxes" / f"{emp_id}.db"
    if not db_path.exists():
        return {"total": 0, "unread": 0, "emails": 0, "ims": 0}
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        total = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        unread = conn.execute("SELECT COUNT(*) FROM messages WHERE read = 0").fetchone()[0]
        emails = conn.execute("SELECT COUNT(*) FROM messages WHERE channel = 'email'").fetchone()[0]
        ims = conn.execute("SELECT COUNT(*) FROM messages WHERE channel = 'im'").fetchone()[0]
        conn.close()
        return {"total": total, "unread": unread, "emails": emails, "ims": ims}
    except Exception:
        return {"total": 0, "unread": 0, "emails": 0, "ims": 0}


def _load_recent_messages(emp_id: str, limit: int = 20) -> list:
    db_path = BASE_PATH / "mailboxes" / f"{emp_id}.db"
    if not db_path.exists():
        return []
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM messages ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def _load_locks() -> list:
    locks_dir = BASE_PATH / "locks"
    if not locks_dir.exists():
        return []
    results = []
    for f in locks_dir.glob("*.yaml"):
        with open(f) as fh:
            data = yaml.safe_load(fh) or {}
        data["resource_id"] = f.stem
        results.append(data)
    return results


def _load_resumes() -> list:
    resumes_dir = BASE_PATH / "resumes"
    if not resumes_dir.exists():
        return []
    results = []
    for f in sorted(resumes_dir.glob("*.yaml"), key=lambda p: p.stat().st_mtime, reverse=True):
        with open(f) as fh:
            data = yaml.safe_load(fh) or {}
        data["file"] = f.name
        results.append(data)
    return results


def _load_shares() -> list:
    shares_dir = BASE_PATH / "shares"
    if not shares_dir.exists():
        return []
    results = []
    for d in shares_dir.iterdir():
        if d.is_dir():
            files = list(d.rglob("*"))
            file_count = sum(1 for f in files if f.is_file())
            results.append({
                "project": d.name,
                "file_count": file_count,
                "modified": datetime.fromtimestamp(d.stat().st_mtime).isoformat(),
            })
    return results


def _calculate_warmth(emp: dict) -> float:
    tasks = emp.get("tasks_completed_under_manager", 0)
    hired = emp.get("hired_at", "")
    domain_overlap = 0.5
    recency_days = 0
    if hired:
        try:
            hired_dt = datetime.fromisoformat(hired.replace("Z", "+00:00"))
            recency_days = (datetime.now(timezone.utc) - hired_dt).days
        except Exception:
            pass
    return (tasks * 0.3) + (recency_days * -0.1) + (domain_overlap * 0.5)


def api_overview() -> dict:
    registry = _load_registry()
    employees = []
    total_tasks = 0
    active = 0
    idle = 0

    for emp_id, meta in registry.items():
        emp = _load_employee(emp_id)
        if not emp:
            continue
        status = emp.get("status", meta.get("status", "unknown"))
        mail = _load_mailbox_stats(emp_id)
        warmth = _calculate_warmth(emp)
        tasks = emp.get("tasks_completed_under_manager", 0)
        total_tasks += tasks

        if status == "active":
            active += 1
        elif status in ("idle", "registered"):
            idle += 1

        employees.append({
            "id": emp_id,
            "nickname": emp.get("nickname", emp_id),
            "full_name": emp.get("full_name", emp.get("nickname", emp_id)),
            "role": emp.get("role", meta.get("role", "unknown")),
            "title": emp.get("title", "Intern"),
            "status": status,
            "manager_id": emp.get("manager_id", "") or emp.get("hired_by", ""),
            "tasks_completed": tasks,
            "warmth": round(warmth, 2),
            "mail": mail,
            "hired_at": emp.get("hired_at", ""),
            "current_task": emp.get("current_task", ""),
            "complexity_tier": emp.get("complexity_tier", ""),
            "can_delegate": emp.get("can_delegate", False),
        })

    locks = _load_locks()
    active_locks = [l for l in locks if l.get("held_by")]
    resumes = _load_resumes()
    shares = _load_shares()

    return {
        "summary": {
            "total_employees": len(employees),
            "active": active,
            "idle": idle,
            "total_tasks": total_tasks,
            "active_locks": len(active_locks),
            "total_locks": len(locks),
            "resumes": len(resumes),
            "shares": len(shares),
        },
        "employees": sorted(employees, key=lambda e: (-e["warmth"], e["nickname"])),
        "locks": locks,
        "resumes": resumes[:10],
        "shares": shares,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def api_employee(emp_id: str) -> dict | None:
    emp = _load_employee(emp_id)
    if not emp:
        return None
    mail = _load_mailbox_stats(emp_id)
    messages = _load_recent_messages(emp_id)
    warmth = _calculate_warmth(emp)
    return {
        "employee": emp,
        "warmth": round(warmth, 2),
        "mail": mail,
        "recent_messages": messages,
    }


DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Corp-Collab Dashboard</title>
<style>
  :root {
    --bg: #0d1117;
    --surface: #161b22;
    --surface2: #1c2129;
    --border: #30363d;
    --text: #e6edf3;
    --text-muted: #8b949e;
    --accent: #58a6ff;
    --green: #3fb950;
    --yellow: #d29922;
    --red: #f85149;
    --purple: #bc8cff;
    --orange: #f0883e;
    --radius: 8px;
    --font: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif;
    --mono: 'SF Mono', 'Cascadia Code', 'Fira Code', monospace;
  }

  * { margin: 0; padding: 0; box-sizing: border-box; }

  body {
    font-family: var(--font);
    background: var(--bg);
    color: var(--text);
    line-height: 1.5;
    min-height: 100vh;
  }

  .header {
    background: var(--surface);
    border-bottom: 1px solid var(--border);
    padding: 16px 24px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    position: sticky;
    top: 0;
    z-index: 100;
  }

  .header h1 {
    font-size: 20px;
    font-weight: 600;
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .header .refresh-info {
    color: var(--text-muted);
    font-size: 13px;
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .header .refresh-btn {
    background: var(--surface2);
    border: 1px solid var(--border);
    color: var(--text);
    padding: 4px 12px;
    border-radius: var(--radius);
    cursor: pointer;
    font-size: 13px;
    transition: background 0.15s;
  }
  .header .refresh-btn:hover { background: var(--border); }

  .container {
    max-width: 1400px;
    margin: 0 auto;
    padding: 24px;
  }

  /* Stats bar */
  .stats-bar {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
    gap: 12px;
    margin-bottom: 24px;
  }

  .stat-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 16px;
    text-align: center;
  }

  .stat-card .value {
    font-size: 32px;
    font-weight: 700;
    font-family: var(--mono);
    line-height: 1.2;
  }

  .stat-card .label {
    font-size: 12px;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.5px;
    margin-top: 4px;
  }

  .stat-card.active .value { color: var(--green); }
  .stat-card.idle .value { color: var(--yellow); }
  .stat-card.locks .value { color: var(--orange); }
  .stat-card.tasks .value { color: var(--accent); }
  .stat-card.resumes .value { color: var(--purple); }

  /* Sections */
  .section {
    margin-bottom: 24px;
  }

  .section-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 12px;
  }

  .section-header h2 {
    font-size: 16px;
    font-weight: 600;
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .section-header .badge {
    background: var(--surface2);
    color: var(--text-muted);
    font-size: 12px;
    padding: 2px 8px;
    border-radius: 10px;
    font-family: var(--mono);
  }

  /* Employee cards */
  .employee-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
    gap: 12px;
  }

  .emp-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 16px;
    cursor: pointer;
    transition: border-color 0.15s, transform 0.1s;
  }
  .emp-card:hover {
    border-color: var(--accent);
    transform: translateY(-1px);
  }

  .emp-card .top-row {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    margin-bottom: 8px;
  }

  .emp-card .name {
    font-weight: 600;
    font-size: 15px;
  }

  .emp-card .role-badge {
    font-size: 11px;
    padding: 2px 8px;
    border-radius: 10px;
    font-weight: 500;
    text-transform: uppercase;
    letter-spacing: 0.3px;
  }

  .role-engineer { background: #1f3a5f; color: #58a6ff; }
  .role-researcher { background: #2d1f4e; color: #bc8cff; }
  .role-reviewer { background: #3b2f1a; color: #f0883e; }
  .role-manager { background: #1a3b2f; color: #3fb950; }
  .role-default { background: var(--surface2); color: var(--text-muted); }

  .emp-card .meta {
    font-size: 13px;
    color: var(--text-muted);
    margin-bottom: 6px;
  }

  .emp-card .task-line {
    font-size: 13px;
    color: var(--text);
    background: var(--surface2);
    padding: 6px 10px;
    border-radius: 4px;
    margin-top: 8px;
    font-family: var(--mono);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .emp-card .bottom-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-top: 10px;
    font-size: 12px;
    color: var(--text-muted);
  }

  .emp-card .mail-indicator {
    display: flex;
    align-items: center;
    gap: 4px;
  }

  .emp-card .mail-indicator.has-unread { color: var(--accent); font-weight: 600; }

  .status-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    display: inline-block;
    margin-right: 6px;
  }
  .status-dot.active { background: var(--green); box-shadow: 0 0 6px var(--green); }
  .status-dot.idle { background: var(--yellow); }
  .status-dot.terminated { background: var(--red); }
  .status-dot.registered { background: var(--text-muted); }

  .warmth-bar {
    width: 60px;
    height: 4px;
    background: var(--surface2);
    border-radius: 2px;
    overflow: hidden;
    display: inline-block;
    vertical-align: middle;
    margin-left: 4px;
  }

  .warmth-bar .fill {
    height: 100%;
    border-radius: 2px;
    transition: width 0.3s;
  }

  /* Locks table */
  .table-wrap {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    overflow-x: auto;
  }

  table {
    width: 100%;
    border-collapse: collapse;
    font-size: 13px;
  }

  th {
    text-align: left;
    padding: 10px 14px;
    background: var(--surface2);
    color: var(--text-muted);
    font-weight: 600;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    border-bottom: 1px solid var(--border);
  }

  td {
    padding: 10px 14px;
    border-bottom: 1px solid var(--border);
  }

  tr:last-child td { border-bottom: none; }
  tr:hover td { background: var(--surface2); }

  /* Empty states */
  .empty-state {
    text-align: center;
    padding: 48px 24px;
    color: var(--text-muted);
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
  }

  .empty-state .icon { font-size: 36px; margin-bottom: 8px; }
  .empty-state .msg { font-size: 14px; }

  /* Detail modal */
  .modal-overlay {
    display: none;
    position: fixed;
    inset: 0;
    background: rgba(0,0,0,0.7);
    z-index: 200;
    justify-content: center;
    align-items: flex-start;
    padding: 48px 24px;
    overflow-y: auto;
  }
  .modal-overlay.open { display: flex; }

  .modal {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 12px;
    width: 100%;
    max-width: 640px;
    padding: 24px;
  }

  .modal .close-btn {
    float: right;
    background: none;
    border: none;
    color: var(--text-muted);
    font-size: 20px;
    cursor: pointer;
    padding: 4px 8px;
    border-radius: 4px;
  }
  .modal .close-btn:hover { background: var(--surface2); color: var(--text); }

  .modal h3 {
    font-size: 18px;
    margin-bottom: 16px;
  }

  .modal .detail-grid {
    display: grid;
    grid-template-columns: 120px 1fr;
    gap: 8px 12px;
    font-size: 13px;
    margin-bottom: 16px;
  }

  .modal .detail-grid .key {
    color: var(--text-muted);
    text-transform: uppercase;
    font-size: 11px;
    letter-spacing: 0.3px;
    padding-top: 2px;
  }

  .modal .msg-list {
    max-height: 300px;
    overflow-y: auto;
    border: 1px solid var(--border);
    border-radius: var(--radius);
  }

  .modal .msg-item {
    padding: 10px 14px;
    border-bottom: 1px solid var(--border);
    font-size: 13px;
  }
  .modal .msg-item:last-child { border-bottom: none; }

  .modal .msg-item .msg-meta {
    color: var(--text-muted);
    font-size: 11px;
    margin-bottom: 4px;
    display: flex;
    justify-content: space-between;
  }

  .modal .msg-item .msg-body {
    font-family: var(--mono);
    font-size: 12px;
    white-space: pre-wrap;
    word-break: break-word;
  }

  .channel-im { color: var(--orange); }
  .channel-email { color: var(--accent); }

  /* Org chart */
  .org-tree {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 20px;
    font-family: var(--mono);
    font-size: 13px;
    line-height: 1.8;
    overflow-x: auto;
    white-space: pre;
  }

  .tabs {
    display: flex;
    gap: 4px;
    margin-bottom: 16px;
  }

  .tab {
    padding: 6px 16px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    color: var(--text-muted);
    cursor: pointer;
    font-size: 13px;
    transition: all 0.15s;
  }
  .tab:hover { color: var(--text); border-color: var(--text-muted); }
  .tab.active {
    color: var(--accent);
    border-color: var(--accent);
    background: rgba(88, 166, 255, 0.1);
  }

  @media (max-width: 768px) {
    .container { padding: 12px; }
    .stats-bar { grid-template-columns: repeat(3, 1fr); }
    .employee-grid { grid-template-columns: 1fr; }
  }
</style>
</head>
<body>

<div class="header">
  <h1>🏢 Corp-Collab</h1>
  <div class="refresh-info">
    <span id="last-refresh">—</span>
    <button class="refresh-btn" onclick="refresh()">↻ Refresh</button>
    <label style="font-size:12px;display:flex;align-items:center;gap:4px;">
      <input type="checkbox" id="auto-refresh" checked> Auto 10s
    </label>
  </div>
</div>

<div class="container">
  <!-- Stats -->
  <div class="stats-bar" id="stats-bar"></div>

  <!-- Tabs -->
  <div class="tabs">
    <div class="tab active" data-tab="roster" onclick="switchTab('roster')">👥 Roster</div>
    <div class="tab" data-tab="org" onclick="switchTab('org')">🏗 Org Chart</div>
    <div class="tab" data-tab="locks" onclick="switchTab('locks')">🔒 Locks</div>
    <div class="tab" data-tab="shares" onclick="switchTab('shares')">📁 Shares</div>
    <div class="tab" data-tab="resumes" onclick="switchTab('resumes')">📄 Resumes</div>
  </div>

  <!-- Tab content -->
  <div class="section" id="tab-roster"></div>
  <div class="section" id="tab-org" style="display:none"></div>
  <div class="section" id="tab-locks" style="display:none"></div>
  <div class="section" id="tab-shares" style="display:none"></div>
  <div class="section" id="tab-resumes" style="display:none"></div>
</div>

<!-- Detail Modal -->
<div class="modal-overlay" id="modal" onclick="if(event.target===this)closeModal()">
  <div class="modal">
    <button class="close-btn" onclick="closeModal()">✕</button>
    <div id="modal-content"></div>
  </div>
</div>

<script>
let data = null;
let currentTab = 'roster';
let autoTimer = null;

function switchTab(tab) {
  currentTab = tab;
  document.querySelectorAll('.tab').forEach(t => {
    t.classList.toggle('active', t.dataset.tab === tab);
  });
  ['roster','org','locks','shares','resumes'].forEach(t => {
    document.getElementById('tab-' + t).style.display = t === tab ? '' : 'none';
  });
}

function roleClass(role) {
  if (['engineer','developer','coder'].some(r => (role||'').toLowerCase().includes(r))) return 'role-engineer';
  if (['research','analyst','data'].some(r => (role||'').toLowerCase().includes(r))) return 'role-researcher';
  if (['review','qa','test'].some(r => (role||'').toLowerCase().includes(r))) return 'role-reviewer';
  if (['manager','lead','director'].some(r => (role||'').toLowerCase().includes(r))) return 'role-manager';
  return 'role-default';
}

function warmthColor(w) {
  if (w >= 2) return 'var(--green)';
  if (w >= 0.5) return 'var(--yellow)';
  return 'var(--red)';
}

function timeAgo(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  const s = Math.floor((Date.now() - d.getTime()) / 1000);
  if (s < 60) return s + 's ago';
  if (s < 3600) return Math.floor(s/60) + 'm ago';
  if (s < 86400) return Math.floor(s/3600) + 'h ago';
  return Math.floor(s/86400) + 'd ago';
}

function renderStats(s) {
  document.getElementById('stats-bar').innerHTML = `
    <div class="stat-card"><div class="value">${s.total_employees}</div><div class="label">Employees</div></div>
    <div class="stat-card active"><div class="value">${s.active}</div><div class="label">Active</div></div>
    <div class="stat-card idle"><div class="value">${s.idle}</div><div class="label">Idle</div></div>
    <div class="stat-card tasks"><div class="value">${s.total_tasks}</div><div class="label">Tasks Done</div></div>
    <div class="stat-card locks"><div class="value">${s.active_locks}</div><div class="label">Active Locks</div></div>
    <div class="stat-card resumes"><div class="value">${s.resumes}</div><div class="label">Resumes</div></div>
  `;
}

function renderRoster(employees) {
  const el = document.getElementById('tab-roster');
  if (!employees.length) {
    el.innerHTML = `<div class="empty-state"><div class="icon">🏢</div><div class="msg">No employees hired yet.<br>Use the Hermes bridge to hire your first employee.</div></div>`;
    return;
  }
  el.innerHTML = `
    <div class="section-header">
      <h2>👥 Employee Roster <span class="badge">${employees.length}</span></h2>
    </div>
    <div class="employee-grid">
      ${employees.map(e => `
        <div class="emp-card" onclick="showEmployee('${e.id}')">
          <div class="top-row">
            <div>
              <span class="status-dot ${e.status}"></span>
              <span class="name">${esc(e.full_name)}</span>
            </div>
            <span class="role-badge ${roleClass(e.role)}">${esc(e.role)}</span>
          </div>
          <div class="meta">
            ${esc(e.title)} · ${e.tasks_completed} tasks · hired ${timeAgo(e.hired_at)}
            ${e.can_delegate ? ' · 🔀 can delegate' : ''}
          </div>
          ${e.current_task ? `<div class="task-line">▶ ${esc(e.current_task)}</div>` : ''}
          <div class="bottom-row">
            <div>
              Warmth: ${e.warmth}
              <div class="warmth-bar">
                <div class="fill" style="width:${Math.min(100, Math.max(0, (e.warmth+1)*25))}%;background:${warmthColor(e.warmth)}"></div>
              </div>
            </div>
            <div class="mail-indicator ${e.mail.unread > 0 ? 'has-unread' : ''}">
              ✉ ${e.mail.unread > 0 ? e.mail.unread + ' unread' : e.mail.total + ' msgs'}
            </div>
          </div>
        </div>
      `).join('')}
    </div>
  `;
}

function renderOrg(employees) {
  const el = document.getElementById('tab-org');
  if (!employees.length) {
    el.innerHTML = `<div class="empty-state"><div class="icon">🏗</div><div class="msg">No org structure yet.</div></div>`;
    return;
  }

  // Build tree
  const byManager = {};
  const roots = [];
  const empIds = new Set(employees.map(e => e.id));
  employees.forEach(e => {
    const mgr = e.manager_id || '__root__';
    if (!byManager[mgr]) byManager[mgr] = [];
    byManager[mgr].push(e);
    // Root = no manager, or manager is __ceo__, or manager not in employee list
    if (!e.manager_id || e.manager_id === '__ceo__' || !empIds.has(e.manager_id)) {
      roots.push(e);
    }
  });

  function renderNode(e, depth) {
    const statusIcon = e.status === 'active' ? '🟢' : e.status === 'idle' ? '🟡' : '⚫';
    let line = `${statusIcon} ${e.full_name} (${e.role}, ${e.title})`;
    if (e.current_task) line += ` — ${e.current_task}`;
    line += '\\n';
    const children = byManager[e.id] || [];
    children.forEach((c, i) => {
      const isLast = i === children.length - 1;
      const connector = isLast ? '└── ' : '├── ';
      const padding = '    '.repeat(depth);
      line += padding + connector + renderNode(c, depth + 1);
    });
    return line;
  }

  let tree = '👤 CEO (Brad)\n';
  // Render root employees (report to CEO or have no manager)
  roots.forEach((r, i) => {
    const isLast = i === roots.length - 1;
    tree += (isLast ? '└── ' : '├── ') + renderNode(r, 1);
  });

  el.innerHTML = `
    <div class="section-header"><h2>🏗 Organization Chart</h2></div>
    <div class="org-tree">${esc(tree)}</div>
  `;
}

function renderLocks(locks) {
  const el = document.getElementById('tab-locks');
  if (!locks.length) {
    el.innerHTML = `<div class="empty-state"><div class="icon">🔓</div><div class="msg">No resource locks registered.</div></div>`;
    return;
  }
  el.innerHTML = `
    <div class="section-header"><h2>🔒 Resource Locks <span class="badge">${locks.length}</span></h2></div>
    <div class="table-wrap"><table>
      <tr><th>Resource</th><th>Type</th><th>Held By</th><th>Queue</th><th>Since</th></tr>
      ${locks.map(l => `
        <tr>
          <td><strong>${esc(l.resource_id)}</strong></td>
          <td>${esc(l.type || l.lock_type || 'exclusive')}</td>
          <td>${l.held_by ? `<span style="color:var(--green)">${esc(typeof l.held_by === 'string' ? l.held_by : JSON.stringify(l.held_by))}</span>` : '<span style="color:var(--text-muted)">free</span>'}</td>
          <td>${(l.queue || []).length} waiting</td>
          <td>${timeAgo(l.acquired_at || l.locked_at)}</td>
        </tr>
      `).join('')}
    </table></div>
  `;
}

function renderShares(shares) {
  const el = document.getElementById('tab-shares');
  if (!shares.length) {
    el.innerHTML = `<div class="empty-state"><div class="icon">📁</div><div class="msg">No shared workspaces yet.</div></div>`;
    return;
  }
  el.innerHTML = `
    <div class="section-header"><h2>📁 File Shares <span class="badge">${shares.length}</span></h2></div>
    <div class="table-wrap"><table>
      <tr><th>Project</th><th>Files</th><th>Last Modified</th></tr>
      ${shares.map(s => `
        <tr>
          <td><strong>${esc(s.project)}</strong></td>
          <td>${s.file_count}</td>
          <td>${timeAgo(s.modified)}</td>
        </tr>
      `).join('')}
    </table></div>
  `;
}

function renderResumes(resumes) {
  const el = document.getElementById('tab-resumes');
  if (!resumes.length) {
    el.innerHTML = `<div class="empty-state"><div class="icon">📄</div><div class="msg">No termination resumes on file.</div></div>`;
    return;
  }
  el.innerHTML = `
    <div class="section-header"><h2>📄 Resumes <span class="badge">${resumes.length}</span></h2></div>
    <div class="table-wrap"><table>
      <tr><th>Employee</th><th>Role</th><th>Tasks</th><th>File</th></tr>
      ${resumes.map(r => `
        <tr>
          <td>${esc(r.nickname || r.employee_id || r.file)}</td>
          <td>${esc(r.role || '—')}</td>
          <td>${r.tasks_completed || r.tasks || 0}</td>
          <td style="font-family:var(--mono);font-size:12px">${esc(r.file)}</td>
        </tr>
      `).join('')}
    </table></div>
  `;
}

function showEmployee(empId) {
  fetch('/api/employee/' + empId)
    .then(r => r.json())
    .then(d => {
      if (!d.employee) return;
      const e = d.employee;
      const mc = document.getElementById('modal-content');
      mc.innerHTML = `
        <h3>${esc(e.full_name || e.nickname || empId)}</h3>
        <div class="detail-grid">
          <div class="key">ID</div><div style="font-family:var(--mono)">${esc(empId)}</div>
          <div class="key">Role</div><div>${esc(e.role || '—')}</div>
          <div class="key">Title</div><div>${esc(e.title || 'Intern')}</div>
          <div class="key">Status</div><div><span class="status-dot ${e.status || 'registered'}"></span>${esc(e.status || 'unknown')}</div>
          <div class="key">Manager</div><div>${esc(e.manager_id || '—')}</div>
          <div class="key">Warmth</div><div>${d.warmth}</div>
          <div class="key">Tasks Done</div><div>${e.tasks_completed_under_manager || 0}</div>
          <div class="key">Hired</div><div>${timeAgo(e.hired_at)}</div>
          <div class="key">Can Delegate</div><div>${e.can_delegate ? '✅ Yes' : '❌ No'}</div>
          <div class="key">Complexity</div><div>${esc(e.complexity_tier || '—')}</div>
          <div class="key">Mail</div><div>✉ ${d.mail.total} total, ${d.mail.unread} unread (${d.mail.emails} email, ${d.mail.ims} IM)</div>
        </div>
        ${e.current_task ? `<div style="margin-bottom:16px"><strong>Current task:</strong><div class="task-line" style="margin-top:4px">▶ ${esc(e.current_task)}</div></div>` : ''}
        <h4 style="margin-bottom:8px;font-size:14px">Recent Messages</h4>
        ${d.recent_messages.length ? `
          <div class="msg-list">
            ${d.recent_messages.map(m => `
              <div class="msg-item">
                <div class="msg-meta">
                  <span><span class="channel-${m.channel || 'email'}">[${(m.channel||'email').toUpperCase()}]</span> ${esc(m.from_name || m.from_id || '?')} → ${esc(m.to_name || m.to_id || '?')}</span>
                  <span>${timeAgo(m.created_at)}</span>
                </div>
                <div class="msg-body">${esc(m.body || '')}</div>
              </div>
            `).join('')}
          </div>
        ` : '<div style="color:var(--text-muted);font-size:13px">No messages yet.</div>'}
      `;
      document.getElementById('modal').classList.add('open');
    });
}

function closeModal() {
  document.getElementById('modal').classList.remove('open');
}

function esc(s) {
  if (s == null) return '';
  const d = document.createElement('div');
  d.textContent = String(s);
  return d.innerHTML;
}

function render(d) {
  data = d;
  renderStats(d.summary);
  renderRoster(d.employees);
  renderOrg(d.employees);
  renderLocks(d.locks);
  renderShares(d.shares);
  renderResumes(d.resumes);
  document.getElementById('last-refresh').textContent = new Date().toLocaleTimeString();
}

function refresh() {
  fetch('/api/overview')
    .then(r => r.json())
    .then(render)
    .catch(e => console.error('Refresh failed:', e));
}

// Auto-refresh
function startAutoRefresh() {
  if (autoTimer) clearInterval(autoTimer);
  autoTimer = setInterval(() => {
    if (document.getElementById('auto-refresh').checked) refresh();
  }, 10000);
}

document.getElementById('auto-refresh').addEventListener('change', () => {
  if (!document.getElementById('auto-refresh').checked && autoTimer) {
    clearInterval(autoTimer);
    autoTimer = null;
  } else {
    startAutoRefresh();
  }
});

// Keyboard
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') closeModal();
  if (e.key === 'r' && !e.ctrlKey && !e.metaKey && document.activeElement === document.body) refresh();
});

// Initial load
refresh();
startAutoRefresh();
</script>
</body>
</html>"""


class DashboardHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        if path == "" or path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(DASHBOARD_HTML.encode())
            return

        if path == "/api/overview":
            self._json_response(api_overview())
            return

        if path.startswith("/api/employee/"):
            emp_id = path.split("/api/employee/", 1)[1]
            result = api_employee(emp_id)
            if result:
                self._json_response(result)
            else:
                self._json_response({"error": "not found"}, 404)
            return

        self.send_error(404)

    def _json_response(self, data, code=200):
        body = json.dumps(data, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        # Quiet logging
        pass


def main():
    parser = argparse.ArgumentParser(description="Corp-Collab Dashboard")
    parser.add_argument("--port", type=int, default=8090)
    parser.add_argument("--host", default="0.0.0.0")
    args = parser.parse_args()

    server = HTTPServer((args.host, args.port), DashboardHandler)
    print(f"🏢 Corp-Collab Dashboard: http://{args.host}:{args.port}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.shutdown()


if __name__ == "__main__":
    main()
