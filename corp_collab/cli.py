"""Corp-Collab: CLI dashboard and monitoring.

Usage:
    python -m corp_collab.cli roster          # List all employees
    python -m corp_collab.cli roster --idle    # Idle employees only
    python -m corp_collab.cli status <emp_id>  # Employee detail
    python -m corp_collab.cli inbox <emp_id>   # Unread messages
    python -m corp_collab.cli skills <emp_id>  # Granted skills
    python -m corp_collab.cli org              # Org chart
    python -m corp_collab.cli locks            # Active resource locks
    python -m corp_collab.cli stats            # Summary statistics
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_BASE = Path.home() / ".claude-code" / "collab"


def _base_path(args: argparse.Namespace) -> Path:
    return Path(args.base) if hasattr(args, "base") and args.base else DEFAULT_BASE


# ── Commands ─────────────────────────────────────────────────────────────────


def cmd_roster(args: argparse.Namespace) -> int:
    """List employees in the roster."""
    from corp_collab.roster import Roster

    base = _base_path(args)
    roster = Roster(base_path=base)
    employees = roster.list_all()

    if args.idle:
        employees = roster.list_idle()

    if args.role:
        employees = [e for e in employees if e.role == args.role]

    if not employees:
        print("No employees found.")
        return 0

    # Header
    print(f"{'ID':<20} {'Name':<25} {'Role':<12} {'Level':<10} {'Status':<10} {'Warmth':<8}")
    print("─" * 85)

    for emp in employees:
        warmth = roster.calculate_warmth(emp)
        level = getattr(emp, "promotion_level", "intern")
        status = getattr(emp, "status", "unknown")
        name = getattr(emp, "full_name", getattr(emp, "nickname", "?"))
        print(f"{emp.id:<20} {name:<25} {emp.role:<12} {level:<10} {status:<10} {warmth:<8.2f}")

    print(f"\nTotal: {len(employees)}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    """Show detailed status for one employee."""
    from corp_collab.roster import Roster

    base = _base_path(args)
    roster = Roster(base_path=base)
    try:
        emp = roster.get(args.employee_id)
    except (FileNotFoundError, KeyError):
        print(f"Employee '{args.employee_id}' not found.")
        return 1

    name = getattr(emp, "full_name", getattr(emp, "nickname", "?"))
    level = getattr(emp, "promotion_level", "intern")
    status = getattr(emp, "status", "unknown")
    hired_by = getattr(emp, "hired_by", "unknown")
    tasks = getattr(emp, "tasks_completed_under_manager", 0)

    print(f"Employee: {name}")
    print(f"  ID:       {emp.id}")
    print(f"  Role:     {emp.role}")
    print(f"  Level:    {level}")
    print(f"  Status:   {status}")
    print(f"  Hired by: {hired_by}")
    print(f"  Tasks:    {tasks}")
    print(f"  Warmth:   {roster.calculate_warmth(emp):.2f}")

    # Skills
    skills = getattr(emp, "all_skills", [])
    if skills:
        print(f"  Skills:   {', '.join(skills)}")

    # Check for handoff doc
    handoff = base / "employees" / emp.id / "handoff.md"
    if handoff.exists():
        print(f"  Handoff:  {handoff}")

    return 0


def cmd_inbox(args: argparse.Namespace) -> int:
    """Show inbox for an employee."""
    from corp_collab.mailbox import Mailbox

    base = _base_path(args)
    db_path = base / "employees" / args.employee_id / "mailbox.db"

    if not db_path.exists():
        print(f"No mailbox for '{args.employee_id}'.")
        return 1

    mbox = Mailbox(employee_id=args.employee_id, db_path=db_path)

    if args.all:
        emails = mbox.get_all(channel="email")
        ims = mbox.get_all(channel="im")
    else:
        emails = mbox.get_unread(channel="email")
        ims = mbox.get_unread(channel="im")

    label = "All" if args.all else "Unread"

    if ims:
        print(f"\n📱 {label} IMs ({len(ims)}):")
        for m in ims:
            from_name = m.get("from_name", m.get("from_id", "?"))
            print(f"  [{from_name}] {m.get('body', '')[:80]}")

    if emails:
        print(f"\n📧 {label} Emails ({len(emails)}):")
        for m in emails:
            from_name = m.get("from_name", m.get("from_id", "?"))
            subj = m.get("subject", "(no subject)")
            print(f"  [{from_name}] {subj}: {m.get('body', '')[:60]}")

    if not ims and not emails:
        print(f"No {label.lower()} messages.")

    mbox.close()
    return 0


def cmd_skills(args: argparse.Namespace) -> int:
    """Show granted skills for an employee."""
    from corp_collab.roster import Roster
    from corp_collab.skill_grants import SkillGrantManager, DEFAULT_CATALOG

    base = _base_path(args)
    roster = Roster(base_path=base)
    try:
        emp = roster.get(args.employee_id)
    except (FileNotFoundError, KeyError):
        print(f"Employee '{args.employee_id}' not found.")
        return 1

    name = getattr(emp, "full_name", args.employee_id)
    role = getattr(emp, "role", "engineer")
    level = getattr(emp, "promotion_level", "intern")

    print(f"Skills for {name} ({role}, {level}):")

    # Show currently granted skills
    granted = getattr(emp, "all_skills", [])
    if granted:
        print(f"\n  Granted: {', '.join(granted)}")

    # Show eligible but not granted
    mgr = SkillGrantManager()
    eligible = []
    for skill_name in DEFAULT_CATALOG:
        ok, _ = mgr.check_eligibility(skill_name, role, level)
        if ok and skill_name not in granted:
            eligible.append(skill_name)

    if eligible:
        print(f"  Available: {', '.join(eligible)}")

    return 0


def cmd_org(args: argparse.Namespace) -> int:
    """Show org chart."""
    from corp_collab.roster import Roster

    base = _base_path(args)
    roster = Roster(base_path=base)
    employees = roster.list_all()

    if not employees:
        print("No employees.")
        return 0

    # Group by hired_by (manager)
    by_manager: dict[str, list] = {}
    for emp in employees:
        mgr = getattr(emp, "hired_by", "unknown")
        by_manager.setdefault(mgr, []).append(emp)

    # Print tree
    print("🏢 Organization Chart")
    print("─" * 40)

    for mgr_id, emps in sorted(by_manager.items()):
        print(f"\n  👔 {mgr_id}")
        for emp in emps:
            name = getattr(emp, "full_name", emp.id)
            level = getattr(emp, "promotion_level", "intern")
            status = getattr(emp, "status", "?")
            icon = "🟢" if status == "active" else "⚪"
            print(f"    {icon} {name} ({level} {emp.role})")

    return 0


def cmd_locks(args: argparse.Namespace) -> int:
    """Show active resource locks."""
    from corp_collab.resource_lock import ResourceLockManager

    base = _base_path(args)
    lock_mgr = ResourceLockManager(base_path=base)

    # Scan lock files in the locks directory
    locks_dir = base / "locks"
    if not locks_dir.exists():
        print("No active locks.")
        return 0

    active = []
    for lock_file in locks_dir.glob("*.yaml"):
        res_id = lock_file.stem
        try:
            info = lock_mgr.status(res_id)
            if info.get("holders"):
                active.append((res_id, info))
        except Exception:
            pass

    if not active:
        print("No active locks.")
        return 0

    print(f"{'Resource':<20} {'Holder':<20} {'Type':<12} {'Queue':<8}")
    print("─" * 60)

    for res_id, info in active:
        holders = info.get("holders", [])
        queue_len = len(info.get("queue", []))
        for holder in holders:
            print(f"{res_id:<20} {holder:<20} {'active':<12} {queue_len:<8}")

    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    """Show summary statistics."""
    from corp_collab.roster import Roster

    base = _base_path(args)
    roster = Roster(base_path=base)
    employees = roster.list_all()

    total = len(employees)
    active = sum(1 for e in employees if getattr(e, "status", "") == "active")
    idle = sum(1 for e in employees if getattr(e, "status", "") == "idle")

    roles: dict[str, int] = {}
    levels: dict[str, int] = {}
    total_tasks = 0

    for emp in employees:
        roles[emp.role] = roles.get(emp.role, 0) + 1
        level = getattr(emp, "promotion_level", "intern")
        levels[level] = levels.get(level, 0) + 1
        total_tasks += getattr(emp, "tasks_completed_under_manager", 0)

    print("📊 Corp-Collab Statistics")
    print("─" * 30)
    print(f"  Total employees: {total}")
    print(f"  Active:          {active}")
    print(f"  Idle:            {idle}")
    print(f"  Total tasks:     {total_tasks}")

    if roles:
        print(f"\n  Roles:")
        for role, count in sorted(roles.items()):
            print(f"    {role}: {count}")

    if levels:
        print(f"\n  Levels:")
        for level, count in sorted(levels.items()):
            print(f"    {level}: {count}")

    return 0


# ── Parser ───────────────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="corp-collab",
        description="Corp-Collab: corporate-style agent orchestration dashboard",
    )
    parser.add_argument("--base", help="Override collab base directory")

    sub = parser.add_subparsers(dest="command")

    # roster
    p_roster = sub.add_parser("roster", help="List employees")
    p_roster.add_argument("--idle", action="store_true", help="Show idle only")
    p_roster.add_argument("--role", help="Filter by role")

    # status
    p_status = sub.add_parser("status", help="Employee detail")
    p_status.add_argument("employee_id", help="Employee ID")

    # inbox
    p_inbox = sub.add_parser("inbox", help="Employee inbox")
    p_inbox.add_argument("employee_id", help="Employee ID")
    p_inbox.add_argument("--all", action="store_true", help="Show all messages (not just unread)")

    # skills
    p_skills = sub.add_parser("skills", help="Employee skills")
    p_skills.add_argument("employee_id", help="Employee ID")

    # org
    sub.add_parser("org", help="Organization chart")

    # locks
    sub.add_parser("locks", help="Active resource locks")

    # stats
    sub.add_parser("stats", help="Summary statistics")

    return parser


COMMANDS = {
    "roster": cmd_roster,
    "status": cmd_status,
    "inbox": cmd_inbox,
    "skills": cmd_skills,
    "org": cmd_org,
    "locks": cmd_locks,
    "stats": cmd_stats,
}


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 0

    handler = COMMANDS.get(args.command)
    if handler:
        return handler(args)

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
