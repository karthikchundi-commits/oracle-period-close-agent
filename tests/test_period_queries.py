"""Tests for period status queries."""

import pytest
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.oracle.period_queries import (
    get_period_close_status,
    get_subledger_status,
    trigger_subledger_transfer,
    get_trial_balance,
    APP_AP, APP_AR, APP_FA, APP_PROJECTS,
)
from src.oracle.variance_analysis import _prior_period


class MockClient:
    def get_ledger_period_statuses(self, ledger_id, period_name):
        return [{"LedgerId": ledger_id, "PeriodName": period_name, "PeriodStatus": "Open"}]

    def get_subledger_period_close(self, ledger_id, period_name):
        return [
            {"application_id": APP_AP, "application_name": "Payables",
             "period_name": period_name, "close_status": "Closed", "transfer_status": "Complete"},
            {"application_id": APP_AR, "application_name": "Receivables",
             "period_name": period_name, "close_status": "Open", "transfer_status": "Pending"},
        ]

    def get_gl_journals(self, ledger_id, period_name):
        return [
            {"JournalBatchId": 1, "TotalAcctDebit": 1000.00, "TotalAcctCredit": 1000.00},
            {"JournalBatchId": 2, "TotalAcctDebit": 500.00, "TotalAcctCredit": 450.00},  # $50 imbalance
        ]

    def get_trial_balance(self, ledger_id, period_name):
        return [
            {"CodeCombinationId": "01-1000", "PeriodDebit": 100000.00, "PeriodCredit": 0.00},
            {"CodeCombinationId": "01-2000", "PeriodDebit": 0.00, "PeriodCredit": 100000.00},
        ]

    def trigger_subledger_transfer(self, ledger_id, period_name, application_id):
        return {"ReqstId": "ESS-9999"}


class TestPriorPeriod:
    def test_mid_year(self):
        assert _prior_period("Mar-25") == "Feb-25"

    def test_january_crosses_year(self):
        assert _prior_period("Jan-25") == "Dec-24"

    def test_december(self):
        assert _prior_period("Dec-24") == "Nov-24"

    def test_invalid_format(self):
        result = _prior_period("Q1-2025")
        assert result == "Q1-2025"


class TestGetPeriodCloseStatus:
    def test_returns_gl_status(self):
        client = MockClient()
        result = get_period_close_status(client, 1001, "Jan-25")
        assert result["gl_status"] == "Open"
        assert result["ledger_id"] == 1001
        assert result["period_name"] == "Jan-25"

    def test_detects_unbalanced_journal(self):
        client = MockClient()
        result = get_period_close_status(client, 1001, "Jan-25")
        assert result["unbalanced_journal_count"] == 1
        assert result["unbalanced_journal_total"] == 50.00

    def test_not_ready_with_imbalance(self):
        client = MockClient()
        result = get_period_close_status(client, 1001, "Jan-25")
        assert result["ready_for_close"] is False

    def test_ready_when_balanced_and_open(self):
        class BalancedClient(MockClient):
            def get_gl_journals(self, l, p):
                return [{"JournalBatchId": 1, "TotalAcctDebit": 1000.00, "TotalAcctCredit": 1000.00}]
        result = get_period_close_status(BalancedClient(), 1001, "Jan-25")
        assert result["ready_for_close"] is True


class TestGetSubledgerStatus:
    def test_returns_two_subledgers(self):
        client = MockClient()
        result = get_subledger_status(client, 1001, "Jan-25")
        assert len(result) == 2

    def test_ap_closed(self):
        client = MockClient()
        result = get_subledger_status(client, 1001, "Jan-25")
        ap = next(s for s in result if s["application_id"] == APP_AP)
        assert ap["close_status"] == "Closed"

    def test_ar_pending_transfer(self):
        client = MockClient()
        result = get_subledger_status(client, 1001, "Jan-25")
        ar = next(s for s in result if s["application_id"] == APP_AR)
        assert ar["transfer_status"] == "Pending"

    def test_fallback_when_no_otbi_data(self):
        class EmptyClient(MockClient):
            def get_subledger_period_close(self, l, p):
                return []
        result = get_subledger_status(EmptyClient(), 1001, "Jan-25")
        assert len(result) == 4
        assert all(s["close_status"] == "Unknown" for s in result)


class TestTriggerSubledgerTransfer:
    def test_submits_ap_job(self):
        result = trigger_subledger_transfer(MockClient(), 1001, "Jan-25", APP_AP)
        assert result["status"] == "Submitted"
        assert result["application_name"] == "Payables"

    def test_invalid_application_id_raises(self):
        with pytest.raises(ValueError, match="Unknown application_id"):
            trigger_subledger_transfer(MockClient(), 1001, "Jan-25", 999)


class TestGetTrialBalance:
    def test_balanced_ledger(self):
        result = get_trial_balance(MockClient(), 1001, "Jan-25")
        assert result["balanced"] is True
        assert result["variance"] == 0.0
        assert result["total_debit"] == 100000.00
        assert result["total_credit"] == 100000.00

    def test_unbalanced_ledger(self):
        class UnbalancedClient(MockClient):
            def get_trial_balance(self, l, p):
                return [
                    {"PeriodDebit": 100000.00, "PeriodCredit": 0.00},
                    {"PeriodDebit": 0.00, "PeriodCredit": 99500.00},
                ]
        result = get_trial_balance(UnbalancedClient(), 1001, "Jan-25")
        assert result["balanced"] is False
        assert result["variance"] == 500.00
