# Corp-Collab: Async Agent Orchestration with Employee Mental Model

## Overview

Corp-Collab is a framework for orchestrating AI agents using a corporate employment metaphor. Instead of synchronous parent-child delegation that blocks the manager, agents are modeled as **employees** with persistent identities, communication channels, and organizational hierarchy.

The key insight: real workplaces don't block a manager while an employee works. They use communication tools (IM, email, file shares), check-in policies, and organizational structure. Corp-Collab replicates this for AI agent orchestration.

## Core Principles

1. **Non-blocking** — Manager never deadlocks waiting for employees
2. **Persistent identity** — Employees accumulate knowledge across task bursts
3. **Hire/fire economics** — Adding/removing employees has cost; retain and reuse
4. **Hierarchical delegation** — Employees can request permission to sub-manage
5. **Communication-first** — IM, email, and file shares are primary collaboration tools
6. **Resource awareness** — Contended tools are locked, employees queue and do other work

## Architecture

### Runtime Model: Hybrid Burst (Option D)

Employees have **persistent identity** (mailbox, file share, memory, role spec) but actual agent sessions are **spawned on-demand** when there's work in inbox or a steer arrives. Between bursts, an employee is "idle" — just state on disk.

This avoids:
- Token waste from long-lived idle daemons
- High latency from pure cron polling
- Context loss from pure subprocess model

### Directory Structure

```
~/.claude-code/collab/
├── employees/
│   └── <employee-id>/
│       ├── profile.yaml        # role, skills, nickname, hired_at, manager, can_delegate
│       ├── mailbox.db          # SQLite inbox/outbox
│       ├── memory/
│       │   └── handoff.md      # matt-pocock style handoff doc from last burst
│       ├── file_share/         # private scratch workspace
│       └── performance.yaml    # tasks completed, avg time, warmth score
├── managers/
│   └── <manager-id>/
│       ├── profile.yaml        # nickname, custom_title, hired_by
│       └── roster.yaml         # current reports, idle employees
├── projects/
│   └── <project-id>/
│       ├── manifest.json       # who has access, file index
│       └── files/              # shared workspace
├── resources/
│   └── locks.db                # resource locking (exclusive/semaphore)
├── name_pools/                 # nickname dictionaries by role
└── config.yaml                 # global settings
```

### Source Code Structure

```
~/Developer/corp-collab/
├── corp_collab/
│   ├── __init__.py
│   ├── employee.py             # Employee identity, lifecycle, promotion
│   ├── manager.py              # Manager policies, check-ins, hiring decisions
│   ├── mailbox.py              # SQLite inbox/outbox per agent
│   ├── im.py                   # Instant message / steer channel (checkpoint injection)
│   ├── file_share.py           # Project shares, publish/read/list
│   ├── resource_lock.py        # Exclusive/semaphore resource management
│   ├── roster.py               # Employee registry, warmth scoring, retention
│   ├── complexity.py           # C1-C4 assessment, time estimation
│   ├── delegation.py           # Permission requests, hierarchy, authority grants
│   ├── nicknames.py            # Name pool, title generation, renaming rights
│   ├── handoff.py              # Burst-end handoff doc generation
│   ├── spawner.py              # Background agent session launcher (hybrid burst)
│   └── checkin.py              # Manager check-in policy, escalation ladder
├── tools/                      # Agent-callable tool wrappers
│   ├── hire.py
│   ├── fire.py
│   ├── im_send.py
│   ├── email_send.py
│   ├── check_reports.py
│   ├── share_file.py
│   ├── acquire_resource.py
│   ├── release_resource.py
│   ├── request_permission.py
│   ├── status_report.py
│   ├── escalate.py
│   └── request_tools.py
├── templates/                  # Job spec templates
│   ├── researcher.yaml
│   ├── engineer.yaml
│   ├── reviewer.yaml
│   └── analyst.yaml
├── docs/
│   ├── PRD.md                  # This document
│   ├── ADR/
│   │   └── 0001-hybrid-burst-model.md
│   └── ARCHITECTURE.md
├── tests/
├── pyproject.toml
├── README.md
└── LICENSE
```

---

## System Design

### 1. Employee Identity & Lifecycle

#### Profile Schema

```yaml
id: emp-a7f3
nickname: "Curie"
title: "Intern"                    # Intern → role-name → Senior → Lead → Director
full_name: "Intern Curie"          # title + nickname, used in all attribution
role: researcher
skills: [web, browser]             # base toolset for role
granted_skills: []                 # additional skills granted per-task
can_delegate: false                # can this employee hire sub-employees?
max_subordinates: 0                # hiring budget (0 = can't hire)
hired_by: mgr-001                  # manager ID
hired_at: 2026-06-03T13:30:00Z
last_active: 2026-06-03T14:15:00Z
status: idle                       # idle | active | terminated
current_task: null
```

#### Lifecycle States

```
[HIRING] → [ONBOARDING] → [ACTIVE] → [IDLE] ←→ [ACTIVE]
                                         ↓
                                    [TERMINATED]
```

- **Hiring**: Manager creates employee, assigns role + nickname
- **Onboarding**: First burst — cold start, read role spec, orient to project
- **Active**: Working on a task burst
- **Idle**: Between bursts, state persists on disk
- **Terminated**: Fired — memory archived, identity freed

#### Promotion Track

```
Intern → [role-name] → Senior → Lead (can_delegate=true) → Director
```

Promotion triggers:
- Consistent task completion at current complexity tier
- High warmth score
- Manager explicit promotion decision

### 2. Nickname System

#### Name Pools (role-flavored)

```yaml
researcher:
  - Curie, Volta, Darwin, Kepler, Mendel, Goodall, Hawking, Sagan
  - Tesla, Faraday, Bohr, Planck, Fermi, Pauling, Hopper, Babbage

engineer:
  - Lovelace, Turing, Knuth, Torvalds, Wozniak, Carmack, Hopper
  - Dijkstra, Ritchie, Thompson, Stallman, Berners-Lee, Gosling

reviewer:
  - Jenkins, Crawford, Sterling, Monroe, Bishop, Fletcher, Marlowe
  - Barrett, Sinclair, Whitfield, Ashworth, Pemberton, Blackwood

analyst:
  - Nash, Bayes, Gauss, Euler, Fourier, Markov, Bernoulli
  - Laplace, Poisson, Fisher, Wald, Tukey, Benford, Shannon

manager:
  - Brandon, Patel, Chen, Rodriguez, Davis, Margaret, Thompson
  - Nakamura, Singh, Mueller, Petrov, Santos, Kim, O'Brien
```

#### Title Evolution

Initial hire: `"Intern [Name]"` (e.g., "Intern Curie")

After promotion: `"Researcher Curie"` → `"Senior Curie"` → `"Lead Curie"`

#### Manager Renaming Rights

After 10 completed tasks under the same manager:
1. Employee earns "renaming rights"
2. Employee chooses a custom seniority title for their manager
3. Title must be unique across all active managers
4. Basic blocklist prevents offensive titles
5. Manager gets notified but **cannot reject**
6. Title replaces "Manager" in all future attribution

Example: `"Manager Brandon"` → `"Spreadsheet King Brandon"`

#### Attribution Format

All communications and git commits use full attribution:

```
[Intern Curie → Manager Brandon] Status report: pricing research 60% complete
[Manager Brandon → Intern Curie] Good progress. Deadline extended 15min.
[Senior Lovelace → Micromanager Brandon] Requesting 2 juniors for test coverage
```

Git:
```
Author: Intern Curie <curie@corp-collab.local>
Reviewed-by: Senior Jenkins <jenkins@corp-collab.local>
Managed-by: Deadline Dragon Brandon <brandon@corp-collab.local>
```

### 3. Communication System

#### Two Channels: IM and Email

| Property | IM | Email |
|----------|-----|-------|
| Delivery | Push — checkpoint injection at next tool boundary | Queue — read at next natural breakpoint |
| Persistence | Last 50 messages (ring buffer) | Permanent until archived |
| Priority | Always urgent | normal / urgent / fyi |
| Response expected | Immediately | Within check-in window |
| Use case | Steers, blockers, "stop and redirect" | Status reports, file shares, questions, handoffs |

#### Checkpoint Injection (Both IM and Email)

The runtime wraps agent tool calls with a mailbox check:

```python
# Pseudocode — inside the agent execution loop
def execute_tool_call(employee, tool_call):
    result = tool_call.execute()
    
    # Check for IMs (high priority — always inject)
    ims = employee.mailbox.get_unread(channel="im")
    if ims:
        result = inject_messages(result, ims, priority="urgent")
    
    # Check for emails (lower priority — inject every N calls or on urgent)
    emails = employee.mailbox.get_unread(channel="email")
    urgent_emails = [e for e in emails if e.priority == "urgent"]
    if urgent_emails or employee.tool_call_count % 10 == 0:
        result = inject_messages(result, emails, priority="normal")
    
    return result
```

Employees can also explicitly poll:
```python
# Employee can manually check
mailbox.check()         # read all unread
mailbox.check("im")     # read only IMs
mailbox.check("email")  # read only emails
```

#### Mailbox Schema (SQLite)

```sql
CREATE TABLE messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel TEXT NOT NULL,          -- 'im' or 'email'
    from_id TEXT NOT NULL,
    from_name TEXT NOT NULL,        -- "Intern Curie"
    to_id TEXT NOT NULL,
    to_name TEXT NOT NULL,
    subject TEXT,                   -- email only
    body TEXT NOT NULL,
    priority TEXT DEFAULT 'normal', -- normal, urgent, fyi
    read BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    read_at TIMESTAMP
);
```

### 4. File Share System

#### Two Types

1. **Project shares** — scoped to a project, multiple employees access
2. **Employee scratch** — private per-employee workspace

#### Project Share Structure

```
~/.claude-code/collab/projects/<project-id>/
├── manifest.json
│   {
│     "project": "auth-refactor",
│     "created_by": "mgr-001",
│     "access": ["emp-a7f3", "emp-b2c1", "mgr-001"],
│     "files": {
│       "pricing.md": {"author": "emp-a7f3", "shared_at": "...", "message": "Key findings..."},
│       "spec.yaml": {"author": "mgr-001", "shared_at": "...", "message": "Requirements doc"}
│     }
│   }
└── files/
    ├── pricing.md
    └── spec.yaml
```

#### File Operations

```python
# Publish file to project share + notify team
share_file(file="scratch/pricing.md", project="auth-refactor", 
           message="Pricing research complete. Key finding: X uses usage-based model.")

# Read from project share
content = read_shared(project="auth-refactor", file="pricing.md")

# List shared files
files = list_shared(project="auth-refactor")

# Direct peer share (copies to recipient's scratch + IM notification)
share_direct(file="scratch/draft.md", to="emp-b2c1",
             message="Draft for your review")
```

When a file is shared, the system automatically sends an IM/email to relevant parties. Not a silent file drop.

### 5. Complexity & Time Estimation

#### Complexity Tiers

| Tier | Description | Who handles | Can delegate? | Default estimate |
|------|-------------|-------------|---------------|-----------------|
| C1 | Single-step, no ambiguity | Any employee | No | 5 min |
| C2 | Multi-step, clear spec | Employee | No | 30 min |
| C3 | Ambiguous, needs decomposition | Senior+ | With permission | 60 min |
| C4 | Cross-domain, architectural | Manager | Yes | 120 min |

#### Time Estimation

```yaml
task:
  id: task-x1y2
  title: "Research competitor pricing"
  complexity: C2
  estimated_minutes: 30
  escalation_multiplier: 1.4       # investigate at 42min
  deadline: null                    # optional hard deadline
  assigned_to: emp-a7f3
  assigned_at: 2026-06-03T13:30:00Z
```

**Estimation flow:**
1. Manager sets initial estimate at assignment
2. Employee can counter-estimate: "Looks more like 45min"
3. Manager accepts or holds firm
4. Historical data from `performance.yaml` calibrates future estimates

**1.4x escalation trigger:**
- Check last status report timestamp
- If recent + shows progress → extend estimate, note slip
- If no recent report → escalation ladder (see §6)

### 6. Manager Check-in Policy

#### Escalation Ladder

```
Task assigned with time estimate T
  │
  ├── T * 1.4 elapsed, no completion
  │   └── Check last status report
  │       ├── Recent + shows progress → extend, note slip
  │       └── No recent report → LEVEL 1
  │
  ├── LEVEL 1: IM — "Hey [name], status update on [task]?"
  │   └── Wait 2 minutes
  │       ├── Response received → de-escalate
  │       └── No response → LEVEL 2
  │
  ├── LEVEL 2: Email (urgent) — formal status request
  │   └── Wait 5 minutes
  │       ├── Response received → de-escalate
  │       └── No response → LEVEL 3
  │
  ├── LEVEL 3: Investigate
  │   ├── Check process status (poll background session)
  │   ├── Read last N lines of employee output
  │   ├── Check if stuck in retry loop / hitting errors
  │   ├── Check resource locks (holding something? waiting on something?)
  │   └── Check if employee sent something that got lost
  │       ├── Found fixable issue → LEVEL 4
  │       └── Employee gone/crashed → LEVEL 5
  │
  ├── LEVEL 4: Intervene
  │   ├── Answer unanswered question
  │   ├── Fix environment issue (install dep, fix permissions)
  │   ├── Steer via IM ("skip that approach, try this")
  │   └── Restart burst with accumulated context + guidance
  │
  └── LEVEL 5: Fire and re-hire
      ├── Terminate employee session
      ├── Archive memory + handoff doc
      ├── Spawn fresh employee with context from failed attempt
      └── Note in performance.yaml (affects warmth score)
```

### 7. Retention & Hire/Fire Economics

#### Costs

| Action | Cost | Consequence |
|--------|------|-------------|
| **Hire** | Cold start penalty (onboarding time) | New employee must orient, no institutional knowledge |
| **Fire** | Knowledge loss | memory.md archived, context evaporates. Re-hiring same role = cold start |
| **Idle** | Disk only | Minimal, but manager tracks headcount and must justify |
| **Reuse** | Bonus — warm context | Returning employee gets handoff.md injected, remembers past work |

#### Warmth Score

```python
warmth = (tasks_completed * 0.3) + (recency_days * -0.1) + (domain_overlap * 0.5)
```

- High warmth → keep idle, likely useful again soon
- Low warmth → candidate for termination
- Manager checks warmth before hiring new — existing warm employee may fit

#### Retention Policy

- Max idle headcount: configurable (default 5)
- Manager reviews idle roster when hiring — always prefer reuse over new hire
- Idle employees with warmth < threshold after N days → auto-termination candidate
- Manager must explicitly approve termination (no silent culling)

#### Adjacent Task Routing

When new task arrives, manager:
1. Check idle roster for domain overlap
2. Check active employees for capacity
3. Check if an existing employee's skills match (even if different role)
4. Only hire new if no match found

### 8. Delegation & Hierarchy

#### Permission Protocol

```yaml
# Employee → Manager request
type: delegation_request
from: emp-a7f3
from_name: "Senior Curie"
to: mgr-001
reason: "Task requires parallel web research + data analysis, different skill sets"
requested_headcount: 2
proposed_roles:
  - { role: web-researcher, tasks: ["gather pricing data", "find competitor features"] }
  - { role: data-analyst, tasks: ["build comparison matrix"] }
estimated_complexity: C3
```

**Manager responses:**
- `approved` — full grant as requested
- `partial` — "hire 1, do the rest yourself"
- `denied` — "handle it solo"
- `redirect` — "don't hire, I'm assigning existing idle employee Bob to help"

**Redirect is key** — manager has roster visibility employee doesn't. Prevents duplicate hires.

#### Hierarchy Limits

- Max depth: 3 levels (Manager → Senior → Junior)
- Each delegator's hiring budget granted by their manager
- Sub-managers use identical collab tools (mailbox, IM, file share) — fractal structure

#### Tool Requests Mid-Task

Employees can request additional skills/tools:

```yaml
type: tool_request
from: emp-a7f3
from_name: "Intern Curie"
to: mgr-001
tool: browser-cdp
reason: "Need to verify API endpoint returns expected data"
```

Manager approves/denies. Some tools conflict or are single-instance — resource locking applies.

### 9. Resource Locking

#### Resource Types

```yaml
resources:
  adb-phone:
    type: exclusive
    queue: fifo
    max_wait: 300s
    
  browser-cdp:
    type: exclusive
    queue: fifo
    max_wait: 120s
    
  git-repo-flowchat:
    type: exclusive
    queue: fifo
    max_wait: 60s

  homeassistant-api:
    type: semaphore
    max_concurrent: 3
    max_wait: 30s
```

#### Locking Flow

```
Employee needs resource →
  acquire_resource("browser-cdp") →
  If available: lock acquired, proceed →
  If locked: 
    Employee queued (FIFO) →
    Employee works on other subtasks meanwhile →
    Resource freed: IM notification "browser available" →
    Employee proceeds →
  Release on task completion or timeout
```

#### Dead-Lock Prevention

- Manager can force-release if holder crashed/silent
- Ties into check-in policy — Level 3 investigation checks resource locks
- Max hold time per resource type (configurable)

### 10. Employee Memory & Context Continuity

#### Handoff Documents (matt-pocock style)

At end of each burst, employee auto-generates:

```markdown
# Handoff — Intern Curie (emp-a7f3) — 2026-06-03T14:15:00Z

## What I did
- Researched competitor pricing for X, Y, Z
- Found pricing data in file_share/project-auth/pricing.md

## What I learned
- Company X uses usage-based pricing, not seat-based
- API rate limits are undocumented, had to reverse-engineer

## Open threads
- Still need Company Z data — site behind Cloudflare
- Asked manager about browser access, awaiting approval

## Key files
- file_share/project-auth/pricing.md
- file_share/project-auth/raw-data/company-x.json

## Blockers
- None currently (browser request pending)
```

Next burst, handoff.md injected as context. Employee picks up seamlessly.

### 11. Matt-Pocock Skills Integration

Skills from the matt-pocock collection available as grantable employee tools:

| Skill | Use as employee tool |
|-------|---------------------|
| `grill-me` | Reviewer employees interrogate designs/implementations |
| `diagnose` | Debug employees use disciplined diagnosis loop |
| `tdd` | Engineer employees follow red-green-refactor |
| `review` | Reviewer employees audit against spec + standards |
| `handoff` | All employees generate handoff docs at burst end |
| `prototype` | Engineer employees build throwaway prototypes |
| `teach` | Senior employees can teach juniors |

Manager grants skills at hire time or on-demand via tool request approval.

---

## Implementation Phases

### Phase 1 — Core Primitives (MVP)

- Employee identity (profile.yaml, lifecycle, nicknames)
- Mailbox (SQLite, send/receive, IM + email)
- Roster (register, query, warmth scoring)
- Hire/fire with cost model
- File share (project shares, publish/read)
- Manager check-in policy (time-based escalation with 1.4x trigger)
- Background agent spawner (hybrid burst model)
- Forgejo repo + GitHub mirror + CI

### Phase 2 — Communication & Permissions

- Checkpoint injection (IM and email into agent loop)
- Email priority levels (normal, urgent, fyi)
- Delegation permission protocol
- Tool request mid-task
- Resource locking (exclusive + semaphore)

### Phase 3 — Intelligence & Hierarchy

- Complexity assessment (C1-C4 auto-classification)
- Time estimation + counter-estimates + historical calibration
- Employee promotion (Intern → Role → Senior → Lead)
- Delegation hierarchy (max depth 3)
- Handoff docs for context continuity
- Performance tracking + warmth-based retention
- Manager renaming rights (after 10 tasks)

### Phase 4 — Integration & Polish

- Matt-pocock skills as grantable tools
- MCP tool wrappers for agent framework integration
- Hook into hermes agent (delegate_task replacement / complement)
- Dashboard / monitoring CLI
- Name pool expansion + role-flavored generation

---

## Configuration

```yaml
# ~/.claude-code/collab/config.yaml
corp_collab:
  max_idle_employees: 5
  max_hierarchy_depth: 3
  default_escalation_multiplier: 1.4
  
  check_in:
    im_wait: 120          # seconds before Level 2
    email_wait: 300        # seconds before Level 3
    
  retention:
    warmth_threshold: 0.3  # below this = termination candidate
    idle_max_days: 7       # max days idle before review
    
  resources:
    lock_timeout_default: 120
    force_release_on_crash: true
    
  nicknames:
    blocklist_path: "name_pools/blocklist.txt"
    allow_manager_rename: true
    rename_threshold: 10   # tasks before earning renaming rights
```

---

## Open Questions for Future Phases

1. **Cross-manager employee sharing** — Can Manager A borrow an employee from Manager B?
2. **Employee self-improvement** — Can employees request training (new skills) proactively?
3. **Performance reviews** — Periodic warmth recalculation with manager commentary?
4. **Union rules** — Should employees be able to refuse tasks outside their role spec? 😄
5. **Onboarding buddy** — Pair new hires with experienced employees for first task?
