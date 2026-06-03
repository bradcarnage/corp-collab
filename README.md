# Corp-Collab 🏢

Async AI agent orchestration with a corporate employment metaphor.

Instead of synchronous parent-child delegation that deadlocks your manager agent, Corp-Collab models agents as **employees** with persistent identities, communication channels (IM, email), file shares, and organizational hierarchy.

[![Tests](https://img.shields.io/badge/tests-539%20passing-brightgreen)]()
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)]()
[![License](https://img.shields.io/badge/license-MIT-green)]()

## The Problem

Traditional agent orchestration (`delegate_task`, subagent spawning) **blocks the parent** until the child finishes. Your manager agent sits idle burning tokens while waiting. If the child gets stuck, the parent is deadlocked.

## The Solution

Corp-Collab treats agents like employees in a company:

```
CEO (Human)
  └── Manager Brandon
        ├── Intern Curie (researcher) ─── working on pricing analysis
        ├── Senior Lovelace (engineer) ── building auth module
        │     ├── Intern Turing (engineer) ── writing tests
        │     └── Intern Knuth (engineer) ── writing docs
        └── Intern Jenkins (reviewer) ─── idle, warm context from last review
```

- **Non-blocking** — Manager assigns work and moves on. Checks in later.
- **Persistent identity** — Employees accumulate knowledge across task bursts.
- **Communication** — IM (instant steer) and Email (async inbox) with checkpoint injection.
- **Economics** — Warmth scoring incentivizes retention over constant hire/fire churn.

## Features

| Feature | Description |
|---------|-------------|
| **Hire/Fire** | Create employees with role-flavored nicknames, terminate with resume archival |
| **IM & Email** | Push (IM steers) and pull (email inbox) communication channels |
| **File Sharing** | Project workspaces with publish/subscribe notifications |
| **Resource Locking** | Exclusive + semaphore locks with queue-based waiting |
| **Delegation** | Permission-based sub-hiring with hierarchy validation (max 3 levels) |
| **Check-ins** | 5-level escalation ladder when employees go silent |
| **Complexity Tiers** | C1-C4 classification with time estimation and counter-estimates |
| **Performance** | Historical calibration, per-tier accuracy tracking, overrun detection |
| **Promotions** | Auto-promotion engine with ceremony, title progression, renaming rights |
| **Retention** | Warmth-based retention, grace periods, manager approval flow |
| **Skill Grants** | Catalog-based skill system with level-gated auto-grants |
| **MCP Tools** | JSON-RPC tool definitions for any MCP-compatible agent framework |
| **Hermes Bridge** | Drop-in `delegate_task` replacement with async assign/check/collect |
| **CLI Dashboard** | roster, status, inbox, skills, org chart, locks, stats |

## Quick Start

```bash
# Install
pip install -e .

# CLI dashboard
corp-collab roster              # List all employees
corp-collab status <emp_id>     # Employee detail
corp-collab inbox <emp_id>      # Unread messages
corp-collab skills <emp_id>     # Granted skills
corp-collab org                 # Org chart
corp-collab locks               # Active resource locks
corp-collab stats               # Summary statistics
```

## Usage

### Hiring an Employee

```python
from tools.hire import hire

result = hire(role="engineer", manager_id="manager-1")
# {'employee_id': 'emp-a3f2', 'nickname': 'Curie', 'full_name': 'Intern Curie', ...}
```

### Assigning Work (Hermes Bridge)

```python
from corp_collab.hermes_bridge import CorpBridge

bridge = CorpBridge(manager_id="manager-1")

# Non-blocking assignment
handle = bridge.assign("Build the auth module", role="engineer", complexity="C3")
# Returns immediately — employee works in background

# Check progress later
status = bridge.check(handle.employee_id)

# Steer if needed (IM push — interrupts employee at next checkpoint)
bridge.steer(handle.employee_id, "Switch to OAuth2 instead of JWT")

# Collect results when done
result = bridge.collect(handle.employee_id)
# {'messages': [...], 'files': ['auth.py', 'test_auth.py'], 'handoff_doc': '...'}
```

### Batch Assignment

```python
handles = bridge.batch_assign([
    {"task": "Research competitor pricing", "role": "researcher"},
    {"task": "Build payment API", "role": "engineer", "complexity": "C3"},
    {"task": "Write integration tests", "role": "reviewer"},
])
# All three hired and assigned in parallel
```

### MCP Integration

```python
from corp_collab.mcp_tools import get_tool_definitions, dispatch

# Register with any MCP server
tools = get_tool_definitions()  # JSON-RPC compatible tool schemas

# Dispatch calls
result = dispatch("corp_hire", {"role": "engineer", "manager_id": "mgr-1"})
```

## Architecture

```
corp_collab/              # Core library (6,700 LOC)
├── employee.py           # Identity, lifecycle, promotion
├── manager.py            # Policies, check-ins, hiring decisions
├── mailbox.py            # SQLite inbox/outbox (IM + email)
├── im.py                 # Instant message / steer channel
├── roster.py             # Registry, warmth scoring, retention
├── complexity.py         # C1-C4 classification, NLP auto-classify
├── delegation.py         # Permission requests, hierarchy validation
├── resource_lock.py      # Exclusive/semaphore locks with queuing
├── file_share.py         # Project workspaces, publish/subscribe
├── nicknames.py          # Role-flavored name pools, title progression
├── handoff.py            # Burst-end handoff doc generation
├── spawner.py            # Background agent session launcher
├── checkin.py            # Check-in policy, 5-level escalation
├── performance.py        # Historical calibration tracker
├── promotion.py          # Auto-promotion engine with ceremony
├── retention.py          # Warmth-based retention, grace periods
├── skill_grants.py       # Catalog-based grantable skills
├── mcp_tools.py          # MCP JSON-RPC tool definitions
├── hermes_bridge.py      # Async delegate_task replacement
└── cli.py                # Dashboard/monitoring CLI

tools/                    # Agent-callable wrappers (12 tools)
├── hire.py, fire.py
├── im_send.py, email_send.py
├── check_reports.py, share_file.py, status_report.py
├── acquire_resource.py, release_resource.py
├── request_permission.py, escalate.py, request_tools.py

tests/                    # 539 tests (5,900 LOC)
```

### Runtime Model: Hybrid Burst

Employees have **persistent identity** on disk (profile, mailbox, memory) but agent sessions spawn **on-demand**. Between bursts, an employee is just YAML + SQLite. No idle token waste, no context loss.

```
[Manager assigns task]
    → Employee profile loaded from disk
    → Handoff doc injected as context
    → Agent session spawned (burst)
    → Employee works, checks mailbox between tool calls
    → Burst ends → handoff doc written
    → Employee returns to disk
[Manager collects results later]
```

### Warmth Scoring

```
warmth = (tasks_completed × 0.3) + (recency_days × -0.1) + (domain_overlap × 0.5)
```

Manager always checks idle roster before hiring new — warm employees get reused first.

### Escalation Ladder

When an employee exceeds 1.4× estimated time:

1. **L1** — IM "status update?"
2. **L2** — Urgent email (2min later)
3. **L3** — Investigate (poll session, read logs)
4. **L4** — Intervene (fix blockers, steer)
5. **L5** — Fire and re-hire with context from failed attempt

## Key Design Decisions

1. **Hybrid burst over long-lived daemons** — persistent identity, on-demand sessions
2. **Both checkpoint injection AND explicit poll** for comms
3. **Permission-based delegation** — employees ask, manager approves
4. **Hire/fire has cost** — warmth scoring incentivizes retention
5. **Fractal hierarchy** — same tools at every level (max 3 deep)
6. **Resource-aware** — contended tools queued, not blocked
7. **Handoff docs for memory** — not full transcripts, not just summaries

## Development

```bash
# Run tests
pip install -e ".[dev]"
pytest

# 539 tests, ~14s
```

## License

MIT
