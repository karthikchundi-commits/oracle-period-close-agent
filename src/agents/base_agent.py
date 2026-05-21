"""Abstract base class for the Period-Close Orchestration Agent."""

from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from src.agents.tools import CLAUDE_TOOLS, OPENAI_TOOLS, TOOL_NAMES
from src.oracle.fusion_client import FusionClient
from src.oracle.period_queries import (
    get_period_close_status,
    get_subledger_status,
    trigger_subledger_transfer,
    get_trial_balance,
)
from src.oracle.intercompany_queries import detect_intercompany_imbalances
from src.oracle.variance_analysis import run_variance_analysis
from src.reporting.close_report import generate_close_report, request_controller_signoff
from config.settings import AgentSettings, NotificationSettings

_SYSTEM_PROMPT = """\
You are an Oracle Fusion Cloud Period-Close Orchestration Agent. Your job is to drive the
complete month-end or quarter-end close sequence for a given ledger and period, reasoning
about the state of the close at each step and deciding what action to take next.

Close sequence (execute in this order — do not skip steps):
1. get_period_close_status — establish baseline: is GL period Open? Are there unbalanced journals?
2. get_subledger_status — confirm AP (200), AR (222), FA (140), Projects (275) are Closed and transferred.
   If any subledger transfer is Pending, call trigger_subledger_transfer for that application_id.
3. If unbalanced_journal_count > 0, call get_unbalanced_journals and reason about each imbalance:
   - FX rounding (< $500, source=Payables/Receivables): note it, flag for corrective entry
   - Timing difference (subledger still open): flag REQUIRES_INVESTIGATION, do not correct
   - Manual coding error (no XLA source): flag PENDING_APPROVAL, urgency HIGH
4. detect_intercompany_imbalances — check for unpaired IC transactions requiring elimination entries.
5. get_trial_balance — verify total DR = total CR. Only call after subledgers are transferred.
6. run_variance_analysis — flag accounts with > threshold% movement vs. prior period.
7. generate_close_report — produce the close package HTML.
8. request_controller_signoff — email the controller the report and a plain-text summary.

Reasoning rules:
- Never call get_trial_balance until all subledgers are Closed/Transferred.
- Never call generate_close_report until trial balance is confirmed balanced.
- If a subledger transfer fails (status=Error), flag it and continue; do not block on it.
- Urgency is HIGH if: close deadline within 24h, intercompany imbalances exist, or manual
  coding errors are unresolved.
- Reach end_turn only after request_controller_signoff has been called.

XLA application_id reference: AP=200, AR=222, FA=140, Projects=275.
"""


@dataclass
class CloseResult:
    ledger_id: int
    period_name: str
    gl_status: str = "Unknown"
    subledgers_closed: bool = False
    unbalanced_journals: int = 0
    intercompany_clear: bool = False
    trial_balance_balanced: bool = False
    variance_flags: int = 0
    report_path: str = ""
    signoff_sent: bool = False
    iterations: int = 0
    tool_calls: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    completed_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())


class BasePeriodCloseAgent(ABC):

    def __init__(
        self,
        fusion_client: FusionClient,
        oracle_settings: Any,
        agent_settings: AgentSettings,
        notification_settings: NotificationSettings,
    ):
        self.client = fusion_client
        self.oracle_settings = oracle_settings
        self.agent_settings = agent_settings
        self.notification_settings = notification_settings
        self.result = CloseResult(
            ledger_id=oracle_settings.ledger_id,
            period_name=oracle_settings.period_name,
        )

    @abstractmethod
    def _call_llm(self, messages: list[dict], tools: list[dict]) -> dict:
        """Call LLM provider. Returns raw provider response."""
        ...

    # ------------------------------------------------------------------
    # Tool dispatcher
    # ------------------------------------------------------------------

    def _execute_tool(self, name: str, args: dict) -> Any:
        if name not in TOOL_NAMES:
            return {"error": f"Unknown tool: {name}"}

        self.result.tool_calls.append(name)

        try:
            if name == "get_period_close_status":
                return get_period_close_status(self.client, args["ledger_id"], args["period_name"])

            if name == "get_subledger_status":
                return get_subledger_status(self.client, args["ledger_id"], args["period_name"])

            if name == "trigger_subledger_transfer":
                return trigger_subledger_transfer(
                    self.client, args["ledger_id"], args["period_name"], args["application_id"]
                )

            if name == "detect_intercompany_imbalances":
                result = detect_intercompany_imbalances(
                    self.client, args["ledger_id"], args["period_name"]
                )
                self.result.intercompany_clear = not result["elimination_required"]
                return result

            if name == "get_trial_balance":
                tb = get_trial_balance(self.client, args["ledger_id"], args["period_name"])
                self.result.trial_balance_balanced = tb["balanced"]
                return tb

            if name == "run_variance_analysis":
                va = run_variance_analysis(
                    self.client,
                    args["ledger_id"],
                    args["period_name"],
                    args.get("threshold_pct", self.agent_settings.variance_threshold_pct),
                )
                self.result.variance_flags = va["accounts_flagged"]
                return va

            if name == "generate_close_report":
                path = generate_close_report(
                    args["ledger_id"],
                    args["period_name"],
                    args.get("close_summary", {}),
                )
                self.result.report_path = path
                return {"report_path": path, "status": "Generated"}

            if name == "request_controller_signoff":
                sent = request_controller_signoff(
                    self.notification_settings,
                    args["ledger_id"],
                    args["period_name"],
                    args["report_path"],
                    args["summary"],
                    args.get("urgency", "NORMAL"),
                )
                self.result.signoff_sent = sent
                return {"status": "Sent" if sent else "Failed", "urgency": args.get("urgency")}

            if name == "get_unbalanced_journals":
                journals = self.client.get_gl_journals(args["ledger_id"], args["period_name"])
                unbalanced = [
                    {
                        "JournalBatchName": j.get("JournalBatchName"),
                        "Imbalance": round(
                            abs(float(j.get("TotalAcctDebit", 0)) - float(j.get("TotalAcctCredit", 0))), 2
                        ),
                        "Status": j.get("Status"),
                    }
                    for j in journals
                    if abs(float(j.get("TotalAcctDebit", 0)) - float(j.get("TotalAcctCredit", 0))) > 0.01
                ]
                self.result.unbalanced_journals = len(unbalanced)
                return {"unbalanced_journals": unbalanced, "count": len(unbalanced)}

        except Exception as exc:
            error_msg = f"{name} failed: {exc}"
            self.result.errors.append(error_msg)
            return {"error": error_msg}

    # ------------------------------------------------------------------
    # Agentic loop
    # ------------------------------------------------------------------

    def run(self, ledger_id: int | None = None, period_name: str | None = None) -> CloseResult:
        lid = ledger_id or self.oracle_settings.ledger_id
        pname = period_name or self.oracle_settings.period_name

        messages = [
            {
                "role": "user",
                "content": (
                    f"Run the complete period-close sequence for ledger_id={lid}, "
                    f"period_name={pname}. Follow the close sequence in your instructions. "
                    f"End only after request_controller_signoff has been called."
                ),
            }
        ]

        for iteration in range(self.agent_settings.max_iterations):
            self.result.iterations = iteration + 1
            response = self._call_llm(messages, self._get_tools())
            tool_calls = self._extract_tool_calls(response)

            if not tool_calls:
                break

            tool_results = []
            for call in tool_calls:
                output = self._execute_tool(call["name"], call["args"])
                tool_results.append({"id": call.get("id"), "name": call["name"], "output": output})

            messages = self._append_turn(messages, response, tool_results)

        return self.result

    # ------------------------------------------------------------------
    # Provider-agnostic helpers (overridden if needed)
    # ------------------------------------------------------------------

    def _get_tools(self) -> list[dict]:
        raise NotImplementedError

    def _extract_tool_calls(self, response: dict) -> list[dict]:
        raise NotImplementedError

    def _append_turn(self, messages: list[dict], response: dict, results: list[dict]) -> list[dict]:
        raise NotImplementedError
