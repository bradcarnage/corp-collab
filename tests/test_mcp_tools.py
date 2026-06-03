"""Tests for corp_collab.mcp_tools — MCP-compatible tool wrappers."""

import pytest

from corp_collab.mcp_tools import (
    TOOL_DEFINITIONS,
    TOOL_MAP,
    dispatch,
    get_tool_definitions,
    get_tool_names,
)


# ── Tool Definitions ─────────────────────────────────────────────────────────


class TestToolDefinitions:
    def test_has_definitions(self):
        assert len(TOOL_DEFINITIONS) >= 10

    def test_all_have_required_fields(self):
        for tool in TOOL_DEFINITIONS:
            assert "name" in tool
            assert "description" in tool
            assert "inputSchema" in tool
            assert tool["inputSchema"]["type"] == "object"

    def test_all_names_prefixed(self):
        for tool in TOOL_DEFINITIONS:
            assert tool["name"].startswith("corp_"), f"{tool['name']} missing corp_ prefix"

    def test_tool_map_matches(self):
        assert len(TOOL_MAP) == len(TOOL_DEFINITIONS)
        for tool in TOOL_DEFINITIONS:
            assert tool["name"] in TOOL_MAP

    def test_get_tool_definitions(self):
        defs = get_tool_definitions()
        assert len(defs) == len(TOOL_DEFINITIONS)
        # Should be a copy
        assert defs is not TOOL_DEFINITIONS

    def test_get_tool_names(self):
        names = get_tool_names()
        assert "corp_hire" in names
        assert "corp_fire" in names
        assert "corp_im" in names

    def test_hire_schema_has_required(self):
        schema = TOOL_MAP["corp_hire"]["inputSchema"]
        assert "role" in schema["required"]
        assert "manager_id" in schema["required"]

    def test_im_schema_has_priority(self):
        schema = TOOL_MAP["corp_im"]["inputSchema"]
        assert "priority" in schema["properties"]
        assert schema["properties"]["priority"]["enum"] == ["normal", "urgent"]

    def test_escalate_level_range(self):
        schema = TOOL_MAP["corp_escalate"]["inputSchema"]
        level_prop = schema["properties"]["level"]
        assert level_prop["minimum"] == 1
        assert level_prop["maximum"] == 5

    def test_roster_actions(self):
        schema = TOOL_MAP["corp_roster"]["inputSchema"]
        assert "list" in schema["properties"]["action"]["enum"]
        assert "warmth" in schema["properties"]["action"]["enum"]


# ── Dispatch ─────────────────────────────────────────────────────────────────


class TestDispatch:
    def test_unknown_tool(self):
        result = dispatch("nonexistent", {})
        assert "error" in result
        assert "Unknown tool" in result["error"]

    def test_dispatch_hire_missing_args(self):
        """Hire without required args should return error, not crash."""
        result = dispatch("corp_hire", {})
        assert "error" in result

    def test_dispatch_routes_correctly(self, tmp_path):
        """Dispatch to corp_hire routes to tools.hire.hire."""
        result = dispatch("corp_hire", {
            "role": "engineer",
            "manager_id": "mgr-test",
        }, base_path=str(tmp_path))
        # Should either succeed or give a structured error — not crash
        assert isinstance(result, dict)

    def test_dispatch_fire_routes(self, tmp_path):
        result = dispatch("corp_fire", {
            "employee_id": "emp-nonexistent",
            "manager_id": "mgr-test",
        }, base_path=str(tmp_path))
        assert isinstance(result, dict)

    def test_dispatch_roster_list(self, tmp_path):
        result = dispatch("corp_roster", {
            "action": "list",
        }, base_path=str(tmp_path))
        assert isinstance(result, dict)
        # Empty roster
        assert "employees" in result or "error" in result

    def test_dispatch_grant_skill_missing_employee(self, tmp_path):
        result = dispatch("corp_grant_skill", {
            "skill_name": "tdd",
            "employee_id": "emp-none",
            "manager_id": "mgr-1",
        }, base_path=str(tmp_path))
        assert isinstance(result, dict)
