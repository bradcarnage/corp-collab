"""Corp-Collab: Hermes agent bridge.

Replaces/complements delegate_task with corp-collab's async employee model.
Instead of blocking on a subagent, the bridge:
1. Finds or hires an employee for the task
2. Assigns work via email/IM
3. Returns immediately with employee_id + tracking handle
4. Manager polls or gets checkpoint-injected updates

Usage from Hermes agent:
    from corp_collab.hermes_bridge import CorpBridge
    bridge = CorpBridge()
    handle = bridge.assign("Build the auth module", role="engineer")
    # ... do other work ...
    status = bridge.check(handle.employee_id)
    results = bridge.collect(handle.employee_id)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_BASE = Path.home() / ".claude-code" / "collab"


@dataclass
class TaskHandle:
    """Returned from assign() — lightweight handle for tracking."""
    employee_id: str
    employee_name: str
    task_summary: str
    assigned_at: str
    complexity: str = "C2"
    status: str = "assigned"

    def to_dict(self) -> dict[str, Any]:
        return {
            "employee_id": self.employee_id,
            "employee_name": self.employee_name,
            "task_summary": self.task_summary,
            "assigned_at": self.assigned_at,
            "complexity": self.complexity,
            "status": self.status,
        }


@dataclass
class CollectResult:
    """Result of collecting work from an employee."""
    employee_id: str
    employee_name: str
    status: str
    messages: list[dict[str, Any]] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    handoff_doc: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "employee_id": self.employee_id,
            "employee_name": self.employee_name,
            "status": self.status,
            "message_count": len(self.messages),
            "messages": self.messages,
            "files": self.files,
            "handoff_doc": self.handoff_doc,
        }


class CorpBridge:
    """Bridge between Hermes agent and corp-collab employee model.

    Drop-in complement for delegate_task — non-blocking task assignment
    with async status checking.
    """

    def __init__(self, base_path: str | Path | None = None, manager_id: str = "hermes"):
        self.base = Path(base_path) if base_path else DEFAULT_BASE
        self.manager_id = manager_id
        self._active_tasks: dict[str, TaskHandle] = {}

    def assign(
        self,
        task: str,
        role: str = "engineer",
        skills: list[str] | None = None,
        project_id: str | None = None,
        complexity: str = "C2",
        prefer_idle: bool = True,
        employee_id: str | None = None,
    ) -> TaskHandle:
        """Assign a task to an employee (hire or reuse idle).

        Non-blocking — returns immediately with tracking handle.

        Args:
            task: Task description
            role: Required role
            skills: Extra skills needed
            project_id: Project context
            complexity: C1-C4 tier
            prefer_idle: Try reusing idle employee first
            employee_id: Assign to specific employee (skip hire)

        Returns:
            TaskHandle for tracking
        """
        from corp_collab.roster import Roster
        from corp_collab.mailbox import Mailbox

        roster = Roster(base_path=self.base)
        emp = None
        emp_name = ""

        # Try specific employee
        if employee_id:
            emp = roster.get(employee_id)
            if emp:
                emp_name = getattr(emp, "full_name", employee_id)

        # Try idle employee with matching role
        if emp is None and prefer_idle:
            idle = roster.list_idle()
            for candidate in idle:
                if getattr(candidate, "role", "") == role:
                    emp = candidate
                    emp_name = getattr(emp, "full_name", emp.id)
                    break

        # Hire new
        if emp is None:
            from tools.hire import hire
            result = hire(
                role=role,
                manager_id=self.manager_id,
                skills=skills,
                project_id=project_id,
                base_path=str(self.base),
            )
            if "error" in result:
                raise RuntimeError(f"Failed to hire: {result['error']}")
            employee_id = result["employee_id"]
            emp_name = result.get("full_name", result.get("nickname", employee_id))
            emp = roster.get(employee_id)

        if emp is None:
            raise RuntimeError("Could not find or hire employee")

        now = datetime.now(timezone.utc).isoformat()

        # Send task assignment via email
        try:
            db_path = self.base / "employees" / emp.id / "mailbox.db"
            mbox = Mailbox(employee_id=emp.id, db_path=db_path)
            mbox.send(
                channel="email",
                to_id=emp.id,
                to_name=emp_name,
                from_id=self.manager_id,
                from_name=self.manager_id,
                subject=f"Task Assignment [{complexity}]",
                body=task,
                priority="normal",
            )
            mbox.close()
        except Exception:
            pass  # Assignment recorded even if email fails

        handle = TaskHandle(
            employee_id=emp.id,
            employee_name=emp_name,
            task_summary=task[:200],
            assigned_at=now,
            complexity=complexity,
            status="assigned",
        )
        self._active_tasks[emp.id] = handle
        return handle

    def check(self, employee_id: str) -> dict[str, Any]:
        """Check status of an assigned task. Non-blocking.

        Returns latest status reports and unread messages.
        """
        from corp_collab.mailbox import Mailbox

        result: dict[str, Any] = {"employee_id": employee_id, "status": "unknown"}

        # Check tracking
        handle = self._active_tasks.get(employee_id)
        if handle:
            result["task_summary"] = handle.task_summary
            result["assigned_at"] = handle.assigned_at
            result["status"] = handle.status

        # Read emails from employee
        try:
            # Manager's mailbox — look for emails FROM this employee
            mgr_mbox_path = self.base / "employees" / self.manager_id / "mailbox.db"
            if mgr_mbox_path.exists():
                mbox = Mailbox(employee_id=self.manager_id, db_path=mgr_mbox_path)
                messages = mbox.read_unread(channel="email")
                from_emp = [m for m in messages if m.get("from_id") == employee_id]
                result["unread_messages"] = from_emp
                result["unread_count"] = len(from_emp)
                mbox.close()
            else:
                result["unread_messages"] = []
                result["unread_count"] = 0
        except Exception:
            result["unread_messages"] = []
            result["unread_count"] = 0

        return result

    def steer(self, employee_id: str, message: str) -> bool:
        """Send an IM steer to redirect an employee. Non-blocking.

        The employee will receive this at their next checkpoint.
        """
        try:
            from tools.im_send import im_send
            result = im_send(
                to_id=employee_id,
                from_id=self.manager_id,
                body=message,
                base_path=str(self.base),
            )
            return "error" not in result
        except Exception:
            return False

    def collect(self, employee_id: str) -> CollectResult:
        """Collect all work product from an employee.

        Gathers: status reports, shared files, handoff doc.
        """
        from corp_collab.roster import Roster

        roster = Roster(base_path=self.base)
        emp = roster.get(employee_id)
        emp_name = getattr(emp, "full_name", employee_id) if emp else employee_id

        result = CollectResult(
            employee_id=employee_id,
            employee_name=emp_name,
            status="collected",
        )

        # Collect emails
        try:
            from corp_collab.mailbox import Mailbox
            mgr_mbox_path = self.base / "employees" / self.manager_id / "mailbox.db"
            if mgr_mbox_path.exists():
                mbox = Mailbox(employee_id=self.manager_id, db_path=mgr_mbox_path)
                all_msgs = mbox.read_all(channel="email")
                result.messages = [m for m in all_msgs if m.get("from_id") == employee_id]
                mbox.close()
        except Exception:
            pass

        # Collect files from employee scratch space
        scratch = self.base / "employees" / employee_id / "scratch"
        if scratch.exists():
            result.files = [str(f.relative_to(scratch)) for f in scratch.rglob("*") if f.is_file()]

        # Check for handoff doc
        handoff_path = self.base / "employees" / employee_id / "handoff.md"
        if handoff_path.exists():
            result.handoff_doc = handoff_path.read_text()

        # Update tracking
        if employee_id in self._active_tasks:
            self._active_tasks[employee_id].status = "collected"

        return result

    def reassign(self, employee_id: str, new_task: str, complexity: str = "C2") -> TaskHandle:
        """Reassign an employee to a new task without firing/rehiring."""
        handle = self.assign(
            task=new_task,
            employee_id=employee_id,
            complexity=complexity,
            prefer_idle=False,
        )
        return handle

    def dismiss(self, employee_id: str, reason: str = "Task complete") -> dict[str, Any]:
        """Dismiss an employee after task completion."""
        from tools.fire import fire
        result = fire(
            employee_id=employee_id,
            manager_id=self.manager_id,
            reason=reason,
            base_path=str(self.base),
        )
        if employee_id in self._active_tasks:
            self._active_tasks[employee_id].status = "dismissed"
            del self._active_tasks[employee_id]
        return result

    def active_tasks(self) -> list[TaskHandle]:
        """List all active task handles."""
        return list(self._active_tasks.values())

    def batch_assign(
        self,
        tasks: list[dict[str, Any]],
    ) -> list[TaskHandle]:
        """Assign multiple tasks at once. Each dict needs 'task' + optional 'role', 'complexity'.

        All assignments are non-blocking — returns immediately.
        """
        handles = []
        for t in tasks:
            try:
                handle = self.assign(
                    task=t["task"],
                    role=t.get("role", "engineer"),
                    skills=t.get("skills"),
                    complexity=t.get("complexity", "C2"),
                )
                handles.append(handle)
            except Exception as exc:
                # Create error handle so caller knows which task failed
                handles.append(TaskHandle(
                    employee_id="FAILED",
                    employee_name="FAILED",
                    task_summary=f"FAILED: {exc}",
                    assigned_at=datetime.now(timezone.utc).isoformat(),
                    status="error",
                ))
        return handles

    def check_all(self) -> list[dict[str, Any]]:
        """Check status of all active tasks."""
        return [self.check(emp_id) for emp_id in self._active_tasks]
