"""Intercompany imbalance detection across Oracle Fusion ledgers."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.oracle.fusion_client import FusionClient

TOLERANCE = 0.01


def detect_intercompany_imbalances(
    client: "FusionClient",
    ledger_id: int,
    period_name: str,
) -> dict:
    """
    Fetches intercompany transactions where the initiator and recipient
    amounts do not net to zero. These require elimination entries before
    consolidated trial balance can close.

    Returns a list of imbalanced pairs with amounts and suggested action.
    """
    txns = client.get_intercompany_transactions(ledger_id, period_name)

    # Group by transaction ID; sum initiator vs recipient accounted amounts
    pairs: dict[str, dict] = {}
    for txn in txns:
        txn_id = str(txn.get("TransactionId", txn.get("BatchId", "unknown")))
        if txn_id not in pairs:
            pairs[txn_id] = {
                "transaction_id": txn_id,
                "initiator_ledger": txn.get("InitiatorLedgerId"),
                "recipient_ledger": txn.get("RecipientLedgerId"),
                "initiator_amount": 0.0,
                "recipient_amount": 0.0,
                "currency": txn.get("TransactionCurrencyCode", "USD"),
                "description": txn.get("Description", ""),
            }
        role = txn.get("PartyType", "INITIATOR")
        amount = float(txn.get("AccountedAmount", 0))
        if role == "INITIATOR":
            pairs[txn_id]["initiator_amount"] += amount
        else:
            pairs[txn_id]["recipient_amount"] += amount

    imbalanced = []
    for pair in pairs.values():
        net = round(pair["initiator_amount"] + pair["recipient_amount"], 2)
        if abs(net) > TOLERANCE:
            pair["net_imbalance"] = net
            pair["suggested_action"] = (
                "Elimination entry required before consolidated close"
                if abs(net) > 100
                else "Rounding difference — review elimination entries"
            )
            imbalanced.append(pair)

    return {
        "ledger_id": ledger_id,
        "period_name": period_name,
        "total_intercompany_transactions": len(pairs),
        "imbalanced_count": len(imbalanced),
        "imbalanced_pairs": imbalanced,
        "elimination_required": len(imbalanced) > 0,
    }
