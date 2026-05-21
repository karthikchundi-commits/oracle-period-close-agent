"""Period-over-period variance analysis against Oracle Fusion trial balance."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.oracle.fusion_client import FusionClient


def _prior_period(period_name: str) -> str:
    """Compute prior calendar month period name (e.g., Jan-25 -> Dec-24)."""
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    parts = period_name.split("-")
    if len(parts) != 2:
        return period_name
    mon, yr = parts[0], int(parts[1])
    idx = months.index(mon) if mon in months else -1
    if idx == -1:
        return period_name
    if idx == 0:
        return f"Dec-{yr - 1:02d}"
    return f"{months[idx - 1]}-{yr:02d}"


def run_variance_analysis(
    client: "FusionClient",
    ledger_id: int,
    period_name: str,
    threshold_pct: float = 10.0,
) -> dict:
    """
    Compares current period trial balance to prior period.
    Flags accounts with movement exceeding threshold_pct.

    Uses GL_BALANCES data via fscmRestApi generalLedgerTrialBalances
    for both the current and prior period.
    """
    prior = _prior_period(period_name)

    current_rows = client.get_trial_balance(ledger_id, period_name)
    prior_rows = client.get_trial_balance(ledger_id, prior)

    # Index by account code combination
    prior_index: dict[str, float] = {}
    for row in prior_rows:
        ccid = str(row.get("CodeCombinationId", row.get("Account", "")))
        net = float(row.get("PeriodDebit", 0)) - float(row.get("PeriodCredit", 0))
        prior_index[ccid] = net

    flagged = []
    for row in current_rows:
        ccid = str(row.get("CodeCombinationId", row.get("Account", "")))
        current_net = float(row.get("PeriodDebit", 0)) - float(row.get("PeriodCredit", 0))
        prior_net = prior_index.get(ccid, 0.0)

        if prior_net == 0:
            if abs(current_net) > 1000:
                flagged.append({
                    "account": ccid,
                    "account_description": row.get("AccountDescription", ""),
                    "current_period_net": round(current_net, 2),
                    "prior_period_net": 0.0,
                    "variance_pct": 100.0,
                    "variance_amount": round(current_net, 2),
                    "flag_reason": "New activity -- no prior period balance",
                })
            continue

        variance_pct = abs((current_net - prior_net) / prior_net) * 100
        if variance_pct >= threshold_pct:
            flagged.append({
                "account": ccid,
                "account_description": row.get("AccountDescription", ""),
                "current_period_net": round(current_net, 2),
                "prior_period_net": round(prior_net, 2),
                "variance_pct": round(variance_pct, 1),
                "variance_amount": round(current_net - prior_net, 2),
                "flag_reason": f"Movement of {variance_pct:.1f}% exceeds {threshold_pct}% threshold",
            })

    return {
        "ledger_id": ledger_id,
        "current_period": period_name,
        "prior_period": prior,
        "accounts_analyzed": len(current_rows),
        "accounts_flagged": len(flagged),
        "threshold_pct": threshold_pct,
        "flagged_accounts": sorted(flagged, key=lambda x: abs(x["variance_amount"]), reverse=True),
    }
