# Corp-Collab 🏢

Async AI agent orchestration with a corporate employment metaphor.

Instead of synchronous parent-child delegation that deadlocks your manager agent, Corp-Collab models agents as **employees** with persistent identities, communication channels (IM, email), file shares, and organizational hierarchy.

## Key Features

- **Non-blocking orchestration** — Manager never waits; employees work asynchronously
- **Persistent employee identity** — Agents accumulate knowledge across task bursts
- **Hire/fire economics** — Retention incentives prevent employee churn
- **Hierarchical delegation** — Employees can request permission to sub-manage
- **Communication tools** — IM (instant steer) and Email (async inbox) with checkpoint injection
- **File sharing** — Project workspaces with publish/subscribe notifications
- **Resource locking** — Contended tools (ADB, browser) managed with queuing
- **Unique nicknames** — Role-flavored names with manager renaming rights after 10 tasks
- **Check-in policy** — Time-based escalation when employees go silent

## Mental Model

```
CEO (Human)
  └── Manager Brandon
        ├── Intern Curie (researcher) ─── working on pricing analysis
        ├── Senior Lovelace (engineer) ── building auth module
        │     ├── Intern Turing (engineer) ── writing tests
        │     └── Intern Knuth (engineer) ── writing docs
        └── Intern Jenkins (reviewer) ─── idle, warm context from last review
```

Employees communicate via IM and email. Files shared through project workspaces. Manager checks in when 1.4x estimated time passes. Employees earn the right to rename their manager after 10 tasks: `"Manager Brandon"` → `"Deadline Dragon Brandon"`.

## Status

🚧 **Phase 1 — Core Primitives** (in progress)

See [docs/PRD.md](docs/PRD.md) for the full specification.

## License

MIT
