"""Tests for tool schema correctness and agent tool dispatch."""

import json
import pytest
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.agents.tools import CLAUDE_TOOLS, OPENAI_TOOLS, TOOL_NAMES, _ALL_TOOLS


class TestToolSchemas:

    def test_all_tools_have_name_and_description(self):
        for t in _ALL_TOOLS:
            assert "name" in t, f"Tool missing name: {t}"
            assert "description" in t, f"Tool {t['name']} missing description"
            assert len(t["description"]) > 20, f"Tool {t['name']} description too short"

    def test_all_tools_have_parameters(self):
        for t in _ALL_TOOLS:
            assert "parameters" in t
            assert t["parameters"]["type"] == "object"
            assert "properties" in t["parameters"]

    def test_required_fields_are_subset_of_properties(self):
        for t in _ALL_TOOLS:
            props = set(t["parameters"].get("properties", {}).keys())
            required = set(t["parameters"].get("required", []))
            assert required <= props, (
                f"Tool {t['name']}: required fields {required - props} not in properties"
            )

    def test_claude_tools_use_input_schema(self):
        for ct in CLAUDE_TOOLS:
            assert "input_schema" in ct
            assert "parameters" not in ct
            assert ct["input_schema"]["type"] == "object"

    def test_openai_tools_use_function_wrapper(self):
        for ot in OPENAI_TOOLS:
            assert ot["type"] == "function"
            assert "function" in ot
            assert "parameters" in ot["function"]
            assert ot["function"].get("strict") is True

    def test_same_tool_count(self):
        assert len(CLAUDE_TOOLS) == len(OPENAI_TOOLS) == len(_ALL_TOOLS)

    def test_tool_names_match(self):
        claude_names = {t["name"] for t in CLAUDE_TOOLS}
        openai_names = {t["function"]["name"] for t in OPENAI_TOOLS}
        assert claude_names == openai_names

    def test_nine_tools_defined(self):
        assert len(_ALL_TOOLS) == 9

    def test_trigger_subledger_enum_values(self):
        trigger_tool = next(t for t in _ALL_TOOLS if t["name"] == "trigger_subledger_transfer")
        app_id_prop = trigger_tool["parameters"]["properties"]["application_id"]
        assert "enum" in app_id_prop
        assert set(app_id_prop["enum"]) == {200, 222, 140, 275}

    def test_request_signoff_urgency_enum(self):
        signoff_tool = next(t for t in _ALL_TOOLS if t["name"] == "request_controller_signoff")
        urgency_prop = signoff_tool["parameters"]["properties"]["urgency"]
        assert set(urgency_prop["enum"]) == {"NORMAL", "HIGH"}

    def test_tool_names_set_matches(self):
        assert TOOL_NAMES == {t["name"] for t in _ALL_TOOLS}


class TestToolDispatch:
    """Verify the base agent tool dispatcher routes correctly using mock client."""

    def _make_agent(self, mock_client):
        from config.settings import AgentSettings, NotificationSettings, OracleSettings
        from src.agents.base_agent import BasePeriodCloseAgent
        from src.agents.tools import CLAUDE_TOOLS

        class _ConcreteAgent(BasePeriodCloseAgent):
            def _call_llm(self, messages, tools):
                return {}
            def _get_tools(self):
                return CLAUDE_TOOLS
            def _extract_tool_calls(self, response):
                return []
            def _append_turn(self, messages, response, results):
                return messages

        oracle = OracleSettings()
        agent_cfg = AgentSettings()
        notif_cfg = NotificationSettings()
        return _ConcreteAgent(mock_client, oracle, agent_cfg, notif_cfg)

    def test_dispatch_get_period_close_status(self):
        class MC:
            def get_ledger_period_statuses(self, l, p):
                return [{"PeriodStatus": "Open"}]
            def get_gl_journals(self, l, p):
                return []

        agent = self._make_agent(MC())
        result = agent._execute_tool("get_period_close_status", {"ledger_id": 1001, "period_name": "Jan-25"})
        assert result["gl_status"] == "Open"

    def test_dispatch_unknown_tool_returns_error(self):
        agent = self._make_agent(object())
        result = agent._execute_tool("nonexistent_tool", {})
        assert "error" in result

    def test_dispatch_detect_intercompany(self):
        class MC:
            def get_intercompany_transactions(self, l, p):
                return []

        agent = self._make_agent(MC())
        result = agent._execute_tool("detect_intercompany_imbalances", {"ledger_id": 1001, "period_name": "Jan-25"})
        assert result["imbalanced_count"] == 0
        assert agent.result.intercompany_clear is True

    def test_dispatch_trial_balance_updates_result(self):
        class MC:
            def get_trial_balance(self, l, p):
                return [
                    {"PeriodDebit": 50000.0, "PeriodCredit": 0.0},
                    {"PeriodDebit": 0.0, "PeriodCredit": 50000.0},
                ]

        agent = self._make_agent(MC())
        result = agent._execute_tool("get_trial_balance", {"ledger_id": 1001, "period_name": "Jan-25"})
        assert result["balanced"] is True
        assert agent.result.trial_balance_balanced is True
