"""Tests for intercompany imbalance detection."""

import pytest
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.oracle.intercompany_queries import detect_intercompany_imbalances, TOLERANCE


class MockClient:
    def __init__(self, txns):
        self._txns = txns

    def get_intercompany_transactions(self, ledger_id, period_name):
        return self._txns


class TestDetectIntercompanyImbalances:

    def test_balanced_pair_not_flagged(self):
        txns = [
            {"TransactionId": "1", "InitiatorLedgerId": 1001, "RecipientLedgerId": 1002,
             "PartyType": "INITIATOR", "AccountedAmount": 10000.00,
             "TransactionCurrencyCode": "USD", "Description": "Test"},
            {"TransactionId": "1", "InitiatorLedgerId": 1001, "RecipientLedgerId": 1002,
             "PartyType": "RECIPIENT", "AccountedAmount": -10000.00,
             "TransactionCurrencyCode": "USD", "Description": "Test"},
        ]
        result = detect_intercompany_imbalances(MockClient(txns), 1001, "Jan-25")
        assert result["imbalanced_count"] == 0
        assert result["elimination_required"] is False

    def test_imbalanced_pair_flagged(self):
        txns = [
            {"TransactionId": "2", "InitiatorLedgerId": 1001, "RecipientLedgerId": 1002,
             "PartyType": "INITIATOR", "AccountedAmount": 15000.00,
             "TransactionCurrencyCode": "USD", "Description": "Mgmt fee"},
            {"TransactionId": "2", "InitiatorLedgerId": 1001, "RecipientLedgerId": 1002,
             "PartyType": "RECIPIENT", "AccountedAmount": -14150.00,  # $850 net
             "TransactionCurrencyCode": "USD", "Description": "Mgmt fee"},
        ]
        result = detect_intercompany_imbalances(MockClient(txns), 1001, "Jan-25")
        assert result["imbalanced_count"] == 1
        assert result["elimination_required"] is True
        assert result["imbalanced_pairs"][0]["net_imbalance"] == 850.00

    def test_within_tolerance_not_flagged(self):
        txns = [
            {"TransactionId": "3", "InitiatorLedgerId": 1001, "RecipientLedgerId": 1002,
             "PartyType": "INITIATOR", "AccountedAmount": 5000.00,
             "TransactionCurrencyCode": "USD", "Description": "Small"},
            {"TransactionId": "3", "InitiatorLedgerId": 1001, "RecipientLedgerId": 1002,
             "PartyType": "RECIPIENT", "AccountedAmount": -5000.005,   # within $0.01
             "TransactionCurrencyCode": "USD", "Description": "Small"},
        ]
        result = detect_intercompany_imbalances(MockClient(txns), 1001, "Jan-25")
        assert result["imbalanced_count"] == 0

    def test_no_transactions_returns_empty(self):
        result = detect_intercompany_imbalances(MockClient([]), 1001, "Jan-25")
        assert result["total_intercompany_transactions"] == 0
        assert result["imbalanced_count"] == 0
        assert result["elimination_required"] is False

    def test_large_imbalance_suggests_elimination(self):
        txns = [
            {"TransactionId": "4", "InitiatorLedgerId": 1001, "RecipientLedgerId": 1002,
             "PartyType": "INITIATOR", "AccountedAmount": 200000.00,
             "TransactionCurrencyCode": "USD", "Description": "Large"},
            {"TransactionId": "4", "InitiatorLedgerId": 1001, "RecipientLedgerId": 1002,
             "PartyType": "RECIPIENT", "AccountedAmount": -199000.00,  # $1000 net
             "TransactionCurrencyCode": "USD", "Description": "Large"},
        ]
        result = detect_intercompany_imbalances(MockClient(txns), 1001, "Jan-25")
        assert "Elimination entry required" in result["imbalanced_pairs"][0]["suggested_action"]

    def test_multiple_pairs_counted_correctly(self):
        txns = [
            {"TransactionId": "5", "InitiatorLedgerId": 1001, "RecipientLedgerId": 1002,
             "PartyType": "INITIATOR", "AccountedAmount": 1000.00,
             "TransactionCurrencyCode": "USD", "Description": "A"},
            {"TransactionId": "5", "InitiatorLedgerId": 1001, "RecipientLedgerId": 1002,
             "PartyType": "RECIPIENT", "AccountedAmount": -800.00,   # imbalanced
             "TransactionCurrencyCode": "USD", "Description": "A"},
            {"TransactionId": "6", "InitiatorLedgerId": 1001, "RecipientLedgerId": 1003,
             "PartyType": "INITIATOR", "AccountedAmount": 500.00,
             "TransactionCurrencyCode": "USD", "Description": "B"},
            {"TransactionId": "6", "InitiatorLedgerId": 1001, "RecipientLedgerId": 1003,
             "PartyType": "RECIPIENT", "AccountedAmount": -500.00,   # balanced
             "TransactionCurrencyCode": "USD", "Description": "B"},
        ]
        result = detect_intercompany_imbalances(MockClient(txns), 1001, "Jan-25")
        assert result["total_intercompany_transactions"] == 2
        assert result["imbalanced_count"] == 1
