"""
Tool definitions for the Period-Close Orchestration Agent.
Single canonical list exported in both Anthropic and OpenAI wire formats.
"""

from __future__ import annotations

_ALL_TOOLS: list[dict] = [
    {
        "name": "get_period_close_status",
        "description": (
            "Returns the current GL period status (Open/Closed) for the specified ledger and period, "
            "plus the count and total amount of any unbalanced journals. Call this first to establish "
            "the baseline state before proceeding with the close sequence."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "ledger_id": {"type": "integer", "description": "Oracle GL ledger ID (e.g., 1001)"},
                "period_name": {"type": "string", "description": "Period name in Oracle format, e.g. Jan-25"},
            },
            "required": ["ledger_id", "period_name"],
        },
    },
    {
        "name": "get_subledger_status",
        "description": (
            "Returns the close status of all four subledgers — Payables (AP, app_id=200), "
            "Receivables (AR, app_id=222), Fixed Assets (FA, app_id=140), and Projects (app_id=275) — "
            "for the given ledger and period. Subledgers must be closed and transferred to GL before "
            "the GL period can close. If transfer_status is Pending for any subledger, call "
            "trigger_subledger_transfer next."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "ledger_id": {"type": "integer", "description": "Oracle GL ledger ID"},
                "period_name": {"type": "string", "description": "Period name, e.g. Jan-25"},
            },
            "required": ["ledger_id", "period_name"],
        },
    },
    {
        "name": "trigger_subledger_transfer",
        "description": (
            "Submits an ESS job to run 'Transfer Journal Entries to GL' for a specific subledger. "
            "Use application_id=200 for Payables, 222 for Receivables, 140 for Fixed Assets, "
            "275 for Projects. Returns a job_request_id. Only call this if get_subledger_status "
            "shows transfer_status=Pending for that subledger."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "ledger_id": {"type": "integer", "description": "Oracle GL ledger ID"},
                "period_name": {"type": "string", "description": "Period name, e.g. Jan-25"},
                "application_id": {
                    "type": "integer",
                    "description": "XLA application ID: 200=AP, 222=AR, 140=FA, 275=Projects",
                    "enum": [200, 222, 140, 275],
                },
            },
            "required": ["ledger_id", "period_name", "application_id"],
        },
    },
    {
        "name": "detect_intercompany_imbalances",
        "description": (
            "Identifies intercompany payable/receivable pairs where initiator and recipient amounts "
            "do not net to zero. These require elimination entries before a consolidated trial balance "
            "can close. Returns each imbalanced pair with the net amount and a suggested action."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "ledger_id": {"type": "integer", "description": "Oracle GL ledger ID"},
                "period_name": {"type": "string", "description": "Period name, e.g. Jan-25"},
            },
            "required": ["ledger_id", "period_name"],
        },
    },
    {
        "name": "get_trial_balance",
        "description": (
            "Pulls the period trial balance and verifies that total debits equal total credits "
            "across all accounts in the ledger. Returns total_debit, total_credit, variance, "
            "and a boolean 'balanced'. Only call this after all subledgers are confirmed closed "
            "and transferred, and all unbalanced journals are resolved."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "ledger_id": {"type": "integer", "description": "Oracle GL ledger ID"},
                "period_name": {"type": "string", "description": "Period name, e.g. Jan-25"},
            },
            "required": ["ledger_id", "period_name"],
        },
    },
    {
        "name": "run_variance_analysis",
        "description": (
            "Compares the current period trial balance to the prior period. Flags accounts where "
            "the period-over-period movement exceeds threshold_pct (default 10%). Returns a list "
            "of flagged accounts sorted by absolute variance amount, with descriptions and "
            "flag reasons for controller review."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "ledger_id": {"type": "integer", "description": "Oracle GL ledger ID"},
                "period_name": {"type": "string", "description": "Period name, e.g. Jan-25"},
                "threshold_pct": {
                    "type": "number",
                    "description": "Variance threshold percentage (default 10.0)",
                    "default": 10.0,
                },
            },
            "required": ["ledger_id", "period_name"],
        },
    },
    {
        "name": "generate_close_report",
        "description": (
            "Generates an HTML period-close package summarizing the complete close sequence: "
            "subledger status, GL journal resolution, intercompany elimination status, trial balance "
            "tie-out, and variance analysis findings. This is the close package sent to the controller "
            "for sign-off. Call this only after all prior steps are complete."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "ledger_id": {"type": "integer", "description": "Oracle GL ledger ID"},
                "period_name": {"type": "string", "description": "Period name, e.g. Jan-25"},
                "close_summary": {
                    "type": "object",
                    "description": "Accumulated results from all prior tool calls in this close run",
                    "properties": {
                        "subledger_status": {"type": "array", "items": {"type": "object"}},
                        "unbalanced_journals_resolved": {"type": "boolean"},
                        "intercompany_clear": {"type": "boolean"},
                        "trial_balance_balanced": {"type": "boolean"},
                        "variance_flags": {"type": "array", "items": {"type": "object"}},
                    },
                    "required": [],
                },
            },
            "required": ["ledger_id", "period_name", "close_summary"],
        },
    },
    {
        "name": "request_controller_signoff",
        "description": (
            "Emails the GL controller the period-close package — the HTML report path, a plain-text "
            "summary of findings, and any open items requiring controller decision before the period "
            "can be marked Closed. Use urgency='HIGH' if the close deadline is within 24 hours or if "
            "there are unresolved intercompany imbalances."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "ledger_id": {"type": "integer", "description": "Oracle GL ledger ID"},
                "period_name": {"type": "string", "description": "Period name, e.g. Jan-25"},
                "report_path": {"type": "string", "description": "Path to the generated HTML close report"},
                "summary": {
                    "type": "string",
                    "description": "Plain-text summary of close status and open items for the controller",
                },
                "urgency": {
                    "type": "string",
                    "enum": ["NORMAL", "HIGH"],
                    "description": "NORMAL or HIGH — HIGH if deadline within 24h or open intercompany items exist",
                },
            },
            "required": ["ledger_id", "period_name", "report_path", "summary", "urgency"],
        },
    },
    {
        "name": "get_unbalanced_journals",
        "description": (
            "Returns GL journals where |TotalAcctDebit - TotalAcctCredit| > 0.01 for the given "
            "ledger and period. Provides journal batch name, imbalance amount, source, and status. "
            "Call this when get_period_close_status reports unbalanced_journal_count > 0 to get "
            "the detail needed to assess each imbalance."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "ledger_id": {"type": "integer", "description": "Oracle GL ledger ID"},
                "period_name": {"type": "string", "description": "Period name, e.g. Jan-25"},
            },
            "required": ["ledger_id", "period_name"],
        },
    },
]


def _to_claude_tool(t: dict) -> dict:
    return {
        "name": t["name"],
        "description": t["description"],
        "input_schema": t["parameters"],
    }


def _to_openai_tool(t: dict) -> dict:
    return {
        "type": "function",
        "function": {
            "name": t["name"],
            "description": t["description"],
            "parameters": t["parameters"],
            "strict": True,
        },
    }


CLAUDE_TOOLS: list[dict] = [_to_claude_tool(t) for t in _ALL_TOOLS]
OPENAI_TOOLS: list[dict] = [_to_openai_tool(t) for t in _ALL_TOOLS]
TOOL_NAMES: set[str] = {t["name"] for t in _ALL_TOOLS}
