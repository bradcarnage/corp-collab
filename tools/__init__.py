"""Corp-Collab tools registry.

Exposes all tool functions and role-based access sets.
"""

from tools.hire import hire
from tools.fire import fire
from tools.im_send import im_send
from tools.email_send import email_send
from tools.check_reports import check_reports
from tools.share_file import share_file
from tools.status_report import status_report
from tools.escalate import escalate
from tools.request_permission import request_permission
from tools.acquire_resource import acquire_resource
from tools.release_resource import release_resource
from tools.request_tools import request_tools

TOOL_REGISTRY = {
    "hire": hire,
    "fire": fire,
    "im_send": im_send,
    "email_send": email_send,
    "check_reports": check_reports,
    "share_file": share_file,
    "status_report": status_report,
    "escalate": escalate,
    "request_permission": request_permission,
    "acquire_resource": acquire_resource,
    "release_resource": release_resource,
    "request_tools": request_tools,
}

# Role-based tool access
MANAGER_TOOLS = {
    "hire",
    "fire",
    "check_reports",
    "escalate",
    "im_send",
    "email_send",
    "share_file",
}

EMPLOYEE_TOOLS = {
    "im_send",
    "email_send",
    "status_report",
    "share_file",
    "request_permission",
    "request_tools",
    "acquire_resource",
    "release_resource",
}

SENIOR_TOOLS = EMPLOYEE_TOOLS | {"check_reports"}

__all__ = [
    "TOOL_REGISTRY",
    "MANAGER_TOOLS",
    "EMPLOYEE_TOOLS",
    "SENIOR_TOOLS",
    "hire",
    "fire",
    "im_send",
    "email_send",
    "check_reports",
    "share_file",
    "status_report",
    "escalate",
    "request_permission",
    "acquire_resource",
    "release_resource",
    "request_tools",
]
