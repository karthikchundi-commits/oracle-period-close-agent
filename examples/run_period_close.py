"""
Example: run the Period-Close Orchestration Agent with a mock Oracle environment.

Usage:
    python examples/run_period_close.py --dry-run --provider claude
    python examples/run_period_close.py --dry-run --provider openai
    python examples/run_period_close.py  # live Oracle instance via .env
"""

from __future__ import annotations

import argparse
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box

from config.settings import OracleSettings, AgentSettings, NotificationSettings
from src.agents.factory import AgentFactory

console = Console()

# ---------------------------------------------------------------------------
# Mock Oracle Fusion Client — realistic Q1 close scenario
# ---------------------------------------------------------------------------

class MockFusionClient:
    """Simulates Oracle Fusion REST responses for a Q1-2025 close scenario.

    Scenario:
      - Ledger 1001, Jan-25
      - AP subledger: Closed, transfer complete
      - AR subledger: Closed, transfer pending (triggers ESS job)
      - FA subledger: Closed, transfer complete
      - Projects subledger: Open (not yet closed)
      - 1 unbalanced journal: GL_MANUAL_ADJ_JAN25_001, $3,750 entity segment mismatch
      - 1 intercompany imbalance: IC txn 7001, $850 net (elimination needed)
      - Trial balance: balanced after journals resolved
      - Variance: 3 accounts flagged > 10%
    """

    def get_ledger_period_statuses(self, ledger_id, period_name):
        return [{"LedgerId": ledger_id, "PeriodName": period_name, "PeriodStatus": "Open"}]

    def get_subledger_period_close(self, ledger_id, period_name):
        return [
            {"application_id": 200, "application_name": "Payables",
             "period_name": period_name, "close_status": "Closed", "transfer_status": "Complete"},
            {"application_id": 222, "application_name": "Receivables",
             "period_name": period_name, "close_status": "Closed", "transfer_status": "Pending"},
            {"application_id": 140, "application_name": "Fixed Assets",
             "period_name": period_name, "close_status": "Closed", "transfer_status": "Complete"},
            {"application_id": 275, "application_name": "Projects",
             "period_name": period_name, "close_status": "Open", "transfer_status": "Not Started"},
        ]

    def trigger_subledger_transfer(self, ledger_id, period_name, application_id):
        return {"ReqstId": f"ESS-{application_id}-20250131", "Status": "Submitted"}

    def get_gl_journals(self, ledger_id, period_name):
        return [
            {
                "JournalBatchId": 100501,
                "JournalBatchName": "AP_ACCRUAL_JAN25_FINAL",
                "TotalAcctDebit": 845000.00,
                "TotalAcctCredit": 845000.00,
                "Status": "Posted",
                "Source": "Payables",
            },
            {
                "JournalBatchId": 100502,
                "JournalBatchName": "AR_RECEIPTS_JAN25_BATCH",
                "TotalAcctDebit": 212500.00,
                "TotalAcctCredit": 212500.00,
                "Status": "Posted",
                "Source": "Receivables",
            },
            {
                "JournalBatchId": 100503,
                "JournalBatchName": "GL_MANUAL_ADJ_JAN25_001",
                "TotalAcctDebit": 53750.00,
                "TotalAcctCredit": 50000.00,    # $3,750 imbalance — entity segment mismatch
                "Status": "Unposted",
                "Source": "Manual",
            },
        ]

    def get_trial_balance(self, ledger_id, period_name):
        return [
            {"CodeCombinationId": "01-1000-000-0000", "AccountDescription": "Cash",
             "PeriodDebit": 500000.00, "PeriodCredit": 0.00},
            {"CodeCombinationId": "01-1200-000-0000", "AccountDescription": "Accounts Receivable",
             "PeriodDebit": 212500.00, "PeriodCredit": 0.00},
            {"CodeCombinationId": "01-2100-000-0000", "AccountDescription": "AP Trade Payables",
             "PeriodDebit": 0.00, "PeriodCredit": 845000.00},
            {"CodeCombinationId": "01-4000-000-0000", "AccountDescription": "Revenue",
             "PeriodDebit": 0.00, "PeriodCredit": 180000.00},
            {"CodeCombinationId": "01-6000-000-0000", "AccountDescription": "Operating Expenses",
             "PeriodDebit": 312500.00, "PeriodCredit": 0.00},
        ]

    def get_intercompany_transactions(self, ledger_id, period_name):
        return [
            {"TransactionId": "7001", "BatchId": "IC-JAN25-001",
             "InitiatorLedgerId": 1001, "RecipientLedgerId": 1002,
             "PartyType": "INITIATOR", "AccountedAmount": 15000.00,
             "TransactionCurrencyCode": "USD", "Description": "Intercompany management fee"},
            {"TransactionId": "7001", "BatchId": "IC-JAN25-001",
             "InitiatorLedgerId": 1001, "RecipientLedgerId": 1002,
             "PartyType": "RECIPIENT", "AccountedAmount": -14150.00,   # $850 net imbalance
             "TransactionCurrencyCode": "USD", "Description": "Intercompany management fee"},
            {"TransactionId": "7002", "BatchId": "IC-JAN25-002",
             "InitiatorLedgerId": 1001, "RecipientLedgerId": 1003,
             "PartyType": "INITIATOR", "AccountedAmount": 8500.00,
             "TransactionCurrencyCode": "USD", "Description": "Shared services allocation"},
            {"TransactionId": "7002", "BatchId": "IC-JAN25-002",
             "InitiatorLedgerId": 1001, "RecipientLedgerId": 1003,
             "PartyType": "RECIPIENT", "AccountedAmount": -8500.00,    # balanced
             "TransactionCurrencyCode": "USD", "Description": "Shared services allocation"},
        ]

    def send_notification(self, to_email, subject, body_html):
        return {"Status": "Sent (mock)", "To": to_email}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(description="Oracle Period-Close Orchestration Agent")
    p.add_argument("--dry-run", action="store_true", help="Use MockFusionClient (no real Oracle calls)")
    p.add_argument("--provider", choices=["claude", "openai"], default="claude")
    p.add_argument("--ledger-id", type=int, default=1001)
    p.add_argument("--period", default="Jan-25")
    p.add_argument("--verbose", action="store_true")
    return p.parse_args()


def print_result(result, verbose: bool):
    console.print()
    console.print(Panel.fit(
        f"[bold]Period-Close Orchestration Complete[/bold]\n"
        f"Ledger: {result.ledger_id}  |  Period: {result.period_name}\n"
        f"Iterations: {result.iterations}  |  Tool calls: {len(result.tool_calls)}",
        style="bold blue",
    ))

    t = Table(box=box.SIMPLE_HEAVY)
    t.add_column("Check", style="cyan")
    t.add_column("Status", style="white")

    t.add_row("Subledgers closed", "[green]Yes[/green]" if result.subledgers_closed else "[yellow]Partial[/yellow]")
    t.add_row("Unbalanced journals", str(result.unbalanced_journals))
    t.add_row("Intercompany clear", "[green]Yes[/green]" if result.intercompany_clear else "[red]No — elimination needed[/red]")
    t.add_row("Trial balance balanced", "[green]Yes[/green]" if result.trial_balance_balanced else "[yellow]Unverified[/yellow]")
    t.add_row("Variance flags", str(result.variance_flags))
    t.add_row("Report generated", "[green]Yes[/green]" if result.report_path else "[red]No[/red]")
    t.add_row("Controller notified", "[green]Yes[/green]" if result.signoff_sent else "[yellow]Pending[/yellow]")

    console.print(t)

    if result.errors:
        console.print("[red]Errors:[/red]")
        for e in result.errors:
            console.print(f"  - {e}")

    if verbose:
        console.print("\n[dim]Tool call sequence:[/dim]")
        for i, tc in enumerate(result.tool_calls, 1):
            console.print(f"  {i:2}. {tc}")

    if result.report_path:
        console.print(f"\n[bold]Close report:[/bold] {result.report_path}")


def main():
    args = parse_args()

    oracle_cfg = OracleSettings()
    oracle_cfg.ledger_id = args.ledger_id
    oracle_cfg.period_name = args.period

    agent_cfg = AgentSettings()
    agent_cfg.provider = args.provider

    notif_cfg = NotificationSettings()

    client = MockFusionClient() if args.dry_run else None

    if client is None:
        from dotenv import load_dotenv
        load_dotenv()
        from src.oracle.fusion_client import FusionClient
        client = FusionClient(
            host=oracle_cfg.host,
            client_id=oracle_cfg.client_id,
            client_secret=oracle_cfg.client_secret,
            token_url=oracle_cfg.token_url,
        )

    console.print(Panel.fit(
        f"[bold]Oracle Period-Close Orchestration Agent[/bold]\n"
        f"Provider: {args.provider.upper()}  |  "
        f"{'DRY RUN (mock Oracle)' if args.dry_run else 'LIVE'}",
        style="bold green" if args.dry_run else "bold red",
    ))

    agent = AgentFactory.create(
        provider=args.provider,
        fusion_client=client,
        oracle_settings=oracle_cfg,
        agent_settings=agent_cfg,
        notification_settings=notif_cfg,
    )

    result = agent.run(ledger_id=args.ledger_id, period_name=args.period)
    print_result(result, args.verbose)


if __name__ == "__main__":
    main()
