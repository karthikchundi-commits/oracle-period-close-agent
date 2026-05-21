"""Claude (Anthropic) implementation of the Period-Close Orchestration Agent."""

from __future__ import annotations

import json
import os
from typing import Any

import anthropic

from src.agents.base_agent import BasePeriodCloseAgent, _SYSTEM_PROMPT
from src.agents.tools import CLAUDE_TOOLS

_MODEL = "claude-opus-4-7"


class ClaudePeriodCloseAgent(BasePeriodCloseAgent):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._client = anthropic.Anthropic(
            api_key=self.agent_settings.anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        )

    def _get_tools(self) -> list[dict]:
        return CLAUDE_TOOLS

    def _call_llm(self, messages: list[dict], tools: list[dict]) -> dict:
        response = self._client.messages.create(
            model=_MODEL,
            max_tokens=8096,
            system=_SYSTEM_PROMPT,
            tools=tools,
            messages=messages,
        )
        return {"raw": response, "stop_reason": response.stop_reason, "content": response.content}

    def _extract_tool_calls(self, response: dict) -> list[dict]:
        if response["stop_reason"] != "tool_use":
            return []
        calls = []
        for block in response["content"]:
            if block.type == "tool_use":
                calls.append({"id": block.id, "name": block.name, "args": block.input})
        return calls

    def _append_turn(self, messages: list[dict], response: dict, results: list[dict]) -> list[dict]:
        # Anthropic: assistant message with all content blocks, then single user message
        # with all tool_result blocks packed together
        messages = messages + [{"role": "assistant", "content": response["content"]}]
        tool_result_blocks = [
            {
                "type": "tool_result",
                "tool_use_id": r["id"],
                "content": json.dumps(r["output"]),
            }
            for r in results
        ]
        messages = messages + [{"role": "user", "content": tool_result_blocks}]
        return messages
