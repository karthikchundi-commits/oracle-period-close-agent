"""Tests for period-over-period variance analysis."""

import pytest
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.oracle.variance_analysis import run_variance_analysis, _prior_period


class MockClient:
    def __init__(self, current_rows, prior_rows):
        self._current = current_rows
        self._prior = prior_rows

    def get_trial_balance(self, ledger_id, period_name):
        if period_name == "Jan-25":
            return self._current
        return self._prior


_CURRENT = [
    {"CodeCombinationId": "01-4000", "AccountDescription": "Revenue",
     "PeriodDebit": 0.0, "PeriodCredit": 300000.0},
    {"CodeCombinationId": "01-6000", "AccountDescription": "OpEx",
     "PeriodDebit": 120000.0, "PeriodCredit": 0.0},
    {"CodeCombinationId": "01-7000", "AccountDescription": "Interest",
     "PeriodDebit": 5000.0, "PeriodCredit": 0.0},
]

_PRIOR = [
    {"CodeCombinationId": "01-4000", "AccountDescription": "Revenue",
     "PeriodDebit": 0.0, "PeriodCredit": 200000.0},   # 50% increase -> flagged
    {"CodeCombinationId": "01-6000", "AccountDescription": "OpEx",
     "PeriodDebit": 115000.0, "PeriodCredit": 0.0},   # 4.3% -> not flagged at 10%
    {"CodeCombinationId": "01-7000", "AccountDescription": "Interest",
     "PeriodDebit": 4500.0, "PeriodCredit": 0.0},     # 11.1% -> flagged at 10%
]


class TestRunVarianceAnalysis:

    def test_flags_large_movement(self):
        result = run_variance_analysis(MockClient(_CURRENT, _PRIOR), 1001, "Jan-25", 10.0)
        accounts = {f["account"] for f in result["flagged_accounts"]}
        assert "01-4000" in accounts  # 50% revenue increase

    def test_does_not_flag_small_movement(self):
        result = run_variance_analysis(MockClient(_CURRENT, _PRIOR), 1001, "Jan-25", 10.0)
        accounts = {f["account"] for f in result["flagged_accounts"]}
        assert "01-6000" not in accounts  # 4.3% -- within threshold

    def test_flags_at_threshold_boundary(self):
        result = run_variance_analysis(MockClient(_CURRENT, _PRIOR), 1001, "Jan-25", 10.0)
        accounts = {f["account"] for f in result["flagged_accounts"]}
        assert "01-7000" in accounts  # 11.1% > 10%

    def test_custom_threshold(self):
        result = run_variance_analysis(MockClient(_CURRENT, _PRIOR), 1001, "Jan-25", 60.0)
        assert result["accounts_flagged"] == 0  # Nothing exceeds 60%

    def test_sorted_by_absolute_variance(self):
        result = run_variance_analysis(MockClient(_CURRENT, _PRIOR), 1001, "Jan-25", 10.0)
        amounts = [abs(f["variance_amount"]) for f in result["flagged_accounts"]]
        assert amounts == sorted(amounts, reverse=True)

    def test_new_activity_flagged_if_large(self):
        current = [{"CodeCombinationId": "01-9999", "AccountDescription": "New Account",
                    "PeriodDebit": 50000.0, "PeriodCredit": 0.0}]
        prior = []
        result = run_variance_analysis(MockClient(current, prior), 1001, "Jan-25", 10.0)
        accounts = {f["account"] for f in result["flagged_accounts"]}
        assert "01-9999" in accounts
        assert result["flagged_accounts"][0]["flag_reason"] == "New activity -- no prior period balance"

    def test_result_metadata(self):
        result = run_variance_analysis(MockClient(_CURRENT, _PRIOR), 1001, "Jan-25", 10.0)
        assert result["current_period"] == "Jan-25"
        assert result["prior_period"] == "Dec-24"
        assert result["accounts_analyzed"] == 3
        assert result["threshold_pct"] == 10.0
