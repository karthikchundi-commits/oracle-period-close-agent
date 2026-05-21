"""AgentFactory — returns the correct agent implementation by provider name."""

from __future__ import annotations

from typing import Any


class AgentFactory:

    @staticmethod
    def create(
        provider: str,
        fusion_client: Any,
        oracle_settings: Any,
        agent_settings: Any,
        notification_settings: Any,
    ):
        p = provider.lower().strip()
        if p == "claude":
            from src.agents.claude_agent import ClaudePeriodCloseAgent
            return ClaudePeriodCloseAgent(
                fusion_client, oracle_settings, agent_settings, notification_settings
            )
        if p in ("openai", "gpt", "gpt-4o"):
            from src.agents.openai_agent import OpenAIPeriodCloseAgent
            return OpenAIPeriodCloseAgent(
                fusion_client, oracle_settings, agent_settings, notification_settings
            )
        raise ValueError(f"Unknown provider '{provider}'. Use 'claude' or 'openai'.")
