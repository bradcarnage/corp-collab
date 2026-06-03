"""Corp-Collab: MCP (Model Context Protocol) tool wrappers.

Exposes corp-collab operations as MCP-compatible tool definitions.
These can be registered with any MCP server to let external agent
frameworks use corp-collab as a tool provider.

Two layers:
1. TOOL_DEFINITIONS — JSON-schema tool specs for MCP discovery
2. dispatch() — routes MCP tool calls to corp-collab tool functions
"""

from __future__ import annotations

from typing import Any

# ── MCP Tool Definitions ─────────────────────────────────────────────────────
# Each entry is an MCP-compatible tool definition with name, description,
# and inputSchema (JSON Schema).

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "corp_hire",
        "description": "Hire a new employee. Creates profile, assigns nickname, registers in roster, sends welcome IM.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "role": {
                    "type": "string",
                    "enum": ["engineer", "researcher", "reviewer", "analyst", "writer", "debugger", "manager"],
                    "description": "Employee role",
                },
                "manager_id": {"type": "string", "description": "ID of hiring manager"},
                "skills": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Extra skills to grant beyond role defaults",
                },
                "project_id": {"type": "string", "description": "Project to grant access to"},
            },
            "required": ["role", "manager_id"],
        },
    },
    {
        "name": "corp_fire",
        "description": "Fire an employee. Generates termination resume, archives state, removes from roster.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "employee_id": {"type": "string", "description": "Employee to fire"},
                "reason": {"type": "string", "description": "Termination reason"},
                "manager_id": {"type": "string", "description": "ID of firing manager"},
            },
            "required": ["employee_id", "manager_id"],
        },
    },
    {
        "name": "corp_im",
        "description": "Send instant message (push/steer). Delivered at next checkpoint — interrupts current work.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "to_id": {"type": "string", "description": "Recipient employee ID"},
                "from_id": {"type": "string", "description": "Sender ID"},
                "body": {"type": "string", "description": "Message body"},
                "priority": {
                    "type": "string",
                    "enum": ["normal", "urgent"],
                    "default": "normal",
                },
            },
            "required": ["to_id", "from_id", "body"],
        },
    },
    {
        "name": "corp_email",
        "description": "Send email (async/queued). Read at breakpoints or polled explicitly.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "to_id": {"type": "string", "description": "Recipient employee ID"},
                "from_id": {"type": "string", "description": "Sender ID"},
                "subject": {"type": "string", "description": "Email subject"},
                "body": {"type": "string", "description": "Email body"},
                "priority": {
                    "type": "string",
                    "enum": ["normal", "urgent", "fyi"],
                    "default": "normal",
                },
            },
            "required": ["to_id", "from_id", "body"],
        },
    },
    {
        "name": "corp_check_reports",
        "description": "Check status reports and emails from employees. Manager-only tool.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "manager_id": {"type": "string", "description": "Manager checking reports"},
                "employee_id": {"type": "string", "description": "Filter to specific employee"},
                "unread_only": {"type": "boolean", "default": True},
            },
            "required": ["manager_id"],
        },
    },
    {
        "name": "corp_status_report",
        "description": "Submit a status report to manager. Employee tool for check-in compliance.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "employee_id": {"type": "string", "description": "Reporting employee"},
                "manager_id": {"type": "string", "description": "Manager to report to"},
                "status": {
                    "type": "string",
                    "enum": ["on_track", "blocked", "completed", "needs_help"],
                },
                "body": {"type": "string", "description": "Status details"},
                "progress_pct": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 100,
                    "description": "Estimated completion percentage",
                },
            },
            "required": ["employee_id", "manager_id", "status", "body"],
        },
    },
    {
        "name": "corp_share_file",
        "description": "Share a file to a project share or directly to an employee.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "from_id": {"type": "string", "description": "Sharing employee ID"},
                "project_id": {"type": "string", "description": "Project to share to"},
                "to_id": {"type": "string", "description": "Direct recipient (instead of project)"},
                "filename": {"type": "string", "description": "File name"},
                "content": {"type": "string", "description": "File content"},
            },
            "required": ["from_id", "filename", "content"],
        },
    },
    {
        "name": "corp_acquire_resource",
        "description": "Acquire a resource lock (exclusive or semaphore). Non-blocking — queues if unavailable.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "resource_id": {"type": "string", "description": "Resource to lock (e.g. 'adb', 'browser-cdp')"},
                "employee_id": {"type": "string", "description": "Requesting employee"},
                "lock_type": {
                    "type": "string",
                    "enum": ["exclusive", "semaphore"],
                    "default": "exclusive",
                },
            },
            "required": ["resource_id", "employee_id"],
        },
    },
    {
        "name": "corp_release_resource",
        "description": "Release a resource lock. Notifies next queued employee via IM.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "resource_id": {"type": "string", "description": "Resource to release"},
                "employee_id": {"type": "string", "description": "Employee releasing lock"},
            },
            "required": ["resource_id", "employee_id"],
        },
    },
    {
        "name": "corp_request_permission",
        "description": "Request delegation permission to hire sub-employees.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "employee_id": {"type": "string", "description": "Requesting employee"},
                "manager_id": {"type": "string", "description": "Manager to approve"},
                "reason": {"type": "string", "description": "Why delegation is needed"},
                "headcount": {"type": "integer", "description": "How many sub-employees"},
                "proposed_roles": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Roles for proposed sub-employees",
                },
            },
            "required": ["employee_id", "manager_id", "reason"],
        },
    },
    {
        "name": "corp_escalate",
        "description": "Escalate an issue with an employee through the 5-level escalation ladder.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "employee_id": {"type": "string", "description": "Employee to escalate about"},
                "manager_id": {"type": "string", "description": "Escalating manager"},
                "level": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 5,
                    "description": "Escalation level (1=IM, 2=email, 3=investigate, 4=intervene, 5=fire+rehire)",
                },
                "reason": {"type": "string", "description": "Escalation reason"},
            },
            "required": ["employee_id", "manager_id", "level"],
        },
    },
    {
        "name": "corp_roster",
        "description": "Query the employee roster. List all, filter by role/status, get warmth scores.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "get", "idle", "warmth"],
                    "default": "list",
                },
                "employee_id": {"type": "string", "description": "For 'get' action"},
                "role": {"type": "string", "description": "Filter by role"},
                "status": {"type": "string", "description": "Filter by status"},
            },
        },
    },
    {
        "name": "corp_grant_skill",
        "description": "Grant a skill to an employee. Manager-only tool.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "skill_name": {"type": "string", "description": "Skill to grant"},
                "employee_id": {"type": "string", "description": "Employee to grant to"},
                "manager_id": {"type": "string", "description": "Granting manager"},
                "force": {"type": "boolean", "default": False, "description": "Bypass eligibility check"},
            },
            "required": ["skill_name", "employee_id", "manager_id"],
        },
    },
]

# Name → definition lookup
TOOL_MAP: dict[str, dict[str, Any]] = {t["name"]: t for t in TOOL_DEFINITIONS}


# ── Dispatcher ───────────────────────────────────────────────────────────────

def dispatch(tool_name: str, arguments: dict[str, Any], base_path: str | None = None) -> dict[str, Any]:
    """Dispatch an MCP tool call to the appropriate corp-collab function.

    Args:
        tool_name: MCP tool name (e.g. 'corp_hire')
        arguments: Tool arguments from MCP call
        base_path: Override collab base directory

    Returns:
        Result dict from the tool function.
    """
    kwargs = dict(arguments)
    if base_path:
        kwargs["base_path"] = base_path

    try:
        if tool_name == "corp_hire":
            from tools.hire import hire
            return hire(**kwargs)

        elif tool_name == "corp_fire":
            from tools.fire import fire
            return fire(**kwargs)

        elif tool_name == "corp_im":
            from tools.im_send import im_send
            return im_send(**kwargs)

        elif tool_name == "corp_email":
            from tools.email_send import email_send
            return email_send(**kwargs)

        elif tool_name == "corp_check_reports":
            from tools.check_reports import check_reports
            return check_reports(**kwargs)

        elif tool_name == "corp_status_report":
            from tools.status_report import status_report
            return status_report(**kwargs)

        elif tool_name == "corp_share_file":
            from tools.share_file import share_file
            return share_file(**kwargs)

        elif tool_name == "corp_acquire_resource":
            from tools.acquire_resource import acquire_resource
            return acquire_resource(**kwargs)

        elif tool_name == "corp_release_resource":
            from tools.release_resource import release_resource
            return release_resource(**kwargs)

        elif tool_name == "corp_request_permission":
            from tools.request_permission import request_permission
            return request_permission(**kwargs)

        elif tool_name == "corp_escalate":
            from tools.escalate import escalate
            return escalate(**kwargs)

        elif tool_name == "corp_roster":
            return _roster_dispatch(kwargs)

        elif tool_name == "corp_grant_skill":
            return _grant_skill_dispatch(kwargs)

        else:
            return {"error": f"Unknown tool: {tool_name}"}

    except Exception as exc:
        return {"error": str(exc)}


def _roster_dispatch(kwargs: dict[str, Any]) -> dict[str, Any]:
    """Handle roster queries."""
    from pathlib import Path
    from corp_collab.roster import Roster

    base = Path(kwargs.pop("base_path", Path.home() / ".claude-code" / "collab"))
    roster = Roster(base_path=base)
    action = kwargs.get("action", "list")

    if action == "get":
        emp_id = kwargs.get("employee_id")
        if not emp_id:
            return {"error": "employee_id required for 'get' action"}
        emp = roster.get(emp_id)
        if emp:
            return {"employee": emp.to_dict()}
        return {"error": f"Employee {emp_id} not found"}

    elif action == "idle":
        idle = roster.list_idle()
        return {"idle_employees": [e.to_dict() for e in idle]}

    elif action == "warmth":
        emp_id = kwargs.get("employee_id")
        if emp_id:
            emp = roster.get(emp_id)
            if emp:
                return {"employee_id": emp_id, "warmth": roster.warmth_score(emp)}
            return {"error": f"Employee {emp_id} not found"}
        # All warmth scores
        all_emp = roster.list_all()
        return {"warmth_scores": {e.id: roster.warmth_score(e) for e in all_emp}}

    else:  # list
        role_filter = kwargs.get("role")
        status_filter = kwargs.get("status")
        employees = roster.list_all()
        if role_filter:
            employees = [e for e in employees if e.role == role_filter]
        if status_filter:
            employees = [e for e in employees if e.status == status_filter]
        return {"employees": [e.to_dict() for e in employees]}


def _grant_skill_dispatch(kwargs: dict[str, Any]) -> dict[str, Any]:
    """Handle skill grants."""
    from pathlib import Path
    from corp_collab.roster import Roster
    from corp_collab.skill_grants import SkillGrantManager

    base = Path(kwargs.pop("base_path", Path.home() / ".claude-code" / "collab"))
    roster = Roster(base_path=base)

    emp_id = kwargs["employee_id"]
    emp = roster.get(emp_id)
    if not emp:
        return {"error": f"Employee {emp_id} not found"}

    mgr = SkillGrantManager()
    ok, msg = mgr.grant(
        skill_name=kwargs["skill_name"],
        employee=emp,
        granted_by=kwargs["manager_id"],
        force=kwargs.get("force", False),
    )
    return {"success": ok, "message": msg}


# ── MCP Server Helpers ───────────────────────────────────────────────────────

def get_tool_definitions() -> list[dict[str, Any]]:
    """Return all MCP tool definitions for server registration."""
    return list(TOOL_DEFINITIONS)


def get_tool_names() -> list[str]:
    """Return all available tool names."""
    return [t["name"] for t in TOOL_DEFINITIONS]
