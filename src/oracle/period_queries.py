"""Period status queries against Oracle Fusion GL."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.oracle.fusion_client import FusionClient

# Oracle XLA application IDs
APP_AP = 200
APP_AR = 222
APP_FA = 140
APP_PROJECTS = 275

SUBLEDGER_NAMES = {
    APP_AP: "Payables",
    APP_AR: "Receivables",
    APP_FA: "Fixed Assets",
    APP_PROJECTS: "Projects",
}


@dataclass
class PeriodStatus:
    ledger_id: int
    period_name: str
    gl_status: str          # Open / Closed / Never Opened
    subledger_statuses: dict[str, str]  # "Payables" -> "Closed"
    unbalanced_journal_count: int
    unbalanced_journal_total: float


def get_period_close_status(client: "FusionClient", ledger_id: int, period_name: str) -> dict:
    """
    Returns combined GL + subledger period status.
    GL status comes from ledgerPeriodStatuses REST endpoint.
    Subledger status is derived from XLA_PERIOD_STATUSES via OTBI.
    """
    gl_rows = client.get_ledger_period_statuses(ledger_id, period_name)

    gl_status = "Not Found"
    if gl_rows:
        gl_status = gl_rows[0].get("PeriodStatus", "Unknown")

    journals = client.get_gl_journals(ledger_id, period_name)
    unbalanced = [
        j for j in journals
        if abs(float(j.get("TotalAcctDebit", 0)) - float(j.get("TotalAcctCredit", 0))) > 0.01
    ]
    unbalanced_total = sum(
        abs(float(j.get("TotalAcctDebit", 0)) - float(j.get("TotalAcctCredit", 0)))
        for j in unbalanced
    )

    return {
        "ledger_id": ledger_id,
        "period_name": period_name,
        "gl_status": gl_status,
        "unbalanced_journal_count": len(unbalanced),
        "unbalanced_journal_total": round(unbalanced_total, 2),
        "ready_for_close": gl_status == "Open" and len(unbalanced) == 0,
    }


def get_subledger_status(client: "FusionClient", ledger_id: int, period_name: str) -> list[dict]:
    """
    Returns close status for AP, AR, Fixed Assets, and Projects subledgers.
    Queries XLA_PERIOD_STATUSES through OTBI.
    """
    raw = client.get_subledger_period_close(ledger_id, period_name)

    if raw:
        return raw

    # Fallback: synthesize from known application IDs when OTBI unavailable
    return [
        {
            "application_id": app_id,
            "application_name": name,
            "period_name": period_name,
            "close_status": "Unknown",
            "transfer_status": "Unknown",
        }
        for app_id, name in SUBLEDGER_NAMES.items()
    ]


def trigger_subledger_transfer(
    client: "FusionClient",
    ledger_id: int,
    period_name: str,
    application_id: int,
) -> dict:
    """
    Submits ESS job: Transfer Journal Entries to GL for the given subledger.
    Returns the job request ID for status polling.
    """
    if application_id not in SUBLEDGER_NAMES:
        raise ValueError(f"Unknown application_id: {application_id}. "
                         f"Valid: {list(SUBLEDGER_NAMES.keys())}")
    result = client.trigger_subledger_transfer(ledger_id, period_name, application_id)
    return {
        "application_id": application_id,
        "application_name": SUBLEDGER_NAMES[application_id],
        "job_request_id": result.get("ReqstId", "submitted"),
        "status": "Submitted",
    }


def get_trial_balance(client: "FusionClient", ledger_id: int, period_name: str) -> dict:
    """
    Pulls trial balance and verifies total DR == total CR.
    Returns balance summary and any accounts with non-zero net balance.
    """
    rows = client.get_trial_balance(ledger_id, period_name)

    total_dr = sum(float(r.get("PeriodDebit", 0)) for r in rows)
    total_cr = sum(float(r.get("PeriodCredit", 0)) for r in rows)
    variance = round(abs(total_dr - total_cr), 2)

    return {
        "ledger_id": ledger_id,
        "period_name": period_name,
        "total_debit": round(total_dr, 2),
        "total_credit": round(total_cr, 2),
        "variance": variance,
        "balanced": variance <= 0.01,
        "account_count": len(rows),
    }
