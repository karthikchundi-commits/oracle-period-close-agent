"""OpenAI GPT-4o implementation of the Period-Close Orchestration Agent."""

from __future__ import annotations

import json
import os

from openai import OpenAI

from src.agents.base_agent import BasePeriodCloseAgent, _SYSTEM_PROMPT
from src.agents.tools import OPENAI_TOOLS


class OpenAIPeriodCloseAgent(BasePeriodCloseAgent):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._client = OpenAI(
            api_key=self.agent_settings.openai_api_key or os.environ.get("OPENAI_API_KEY", "")
        )

    def _get_tools(self) -> list[dict]:
        return OPENAI_TOOLS

    def _call_llm(self, messages: list[dict], tools: list[dict]) -> dict:
        oai_messages = [{"role": "system", "content": _SYSTEM_PROMPT}] + messages
        response = self._client.chat.completions.create(
            model=self.agent_settings.openai_model,
            tools=tools,
            parallel_tool_calls=True,
            messages=oai_messages,
        )
        choice = response.choices[0]
        return {
            "raw": response,
            "finish_reason": choice.finish_reason,
            "message": choice.message,
        }

    def _extract_tool_calls(self, response: dict) -> list[dict]:
        if response["finish_reason"] != "tool_calls":
            return []
        calls = []
        for tc in response["message"].tool_calls or []:
            calls.append({
                "id": tc.id,
                "name": tc.function.name,
                "args": json.loads(tc.function.arguments),
            })
        return calls

    def _append_turn(self, messages: list[dict], response: dict, results: list[dict]) -> list[dict]:
        # OpenAI: append assistant message, then one tool message per call
        messages = messages + [response["message"]]
        for r in results:
            messages = messages + [{
                "role": "tool",
                "tool_call_id": r["id"],
                "content": json.dumps(r["output"]),
            }]
        return messages
