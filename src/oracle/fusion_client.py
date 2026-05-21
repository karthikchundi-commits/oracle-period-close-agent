"""Oracle Fusion Cloud REST client with OAuth2 token caching and retry."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


@dataclass
class _TokenCache:
    access_token: str = ""
    expires_at: float = 0.0

    def is_valid(self) -> bool:
        return bool(self.access_token) and time.time() < self.expires_at - 30


def _build_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    return session


class FusionClient:
    """Thin Oracle Fusion Cloud REST client."""

    def __init__(self, host: str, client_id: str, client_secret: str, token_url: str):
        self.host = host.rstrip("/")
        self.client_id = client_id
        self.client_secret = client_secret
        self.token_url = token_url
        self._cache = _TokenCache()
        self._session = _build_session()

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    def _get_token(self) -> str:
        if self._cache.is_valid():
            return self._cache.access_token
        resp = self._session.post(
            self.token_url,
            data={"grant_type": "client_credentials"},
            auth=(self.client_id, self.client_secret),
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        self._cache.access_token = data["access_token"]
        self._cache.expires_at = time.time() + int(data.get("expires_in", 3600))
        return self._cache.access_token

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._get_token()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    # ------------------------------------------------------------------
    # Generic REST helpers
    # ------------------------------------------------------------------

    def get(self, path: str, params: dict | None = None) -> dict:
        url = f"{self.host}{path}"
        resp = self._session.get(url, headers=self._headers(), params=params, timeout=60)
        resp.raise_for_status()
        return resp.json()

    def post(self, path: str, payload: dict) -> dict:
        url = f"{self.host}{path}"
        resp = self._session.post(url, headers=self._headers(), json=payload, timeout=60)
        resp.raise_for_status()
        return resp.json()

    def patch(self, path: str, payload: dict) -> dict:
        url = f"{self.host}{path}"
        resp = self._session.patch(url, headers=self._headers(), json=payload, timeout=60)
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    # Oracle-specific endpoints
    # ------------------------------------------------------------------

    def get_ledger_period_statuses(self, ledger_id: int, period_name: str) -> list[dict]:
        data = self.get(
            f"/fscmRestApi/resources/11.13.18.05/ledgerPeriodStatuses",
            params={
                "q": f"LedgerId={ledger_id};PeriodName={period_name}",
                "limit": 100,
            },
        )
        return data.get("items", [])

    def get_subledger_period_close(self, ledger_id: int, period_name: str) -> list[dict]:
        """OTBI query for subledger period close status."""
        report_path = (
            "/analytics/saw.dll?Go&NQUser=dummy&NQPassword=dummy"
            "&path=/shared/Custom/ERP/SubledgerCloseStatus&Action=prompt"
        )
        data = self.get(
            report_path,
            params={"ledger_id": ledger_id, "period_name": period_name},
        )
        return data.get("items", [])

    def trigger_subledger_transfer(self, ledger_id: int, period_name: str, application_id: int) -> dict:
        return self.post(
            "/fscmRestApi/resources/11.13.18.05/erpintegrations",
            {
                "OperationName": "submitESSJobRequest",
                "JobPackageName": "/oracle/apps/ess/financials/xla",
                "JobDefinitionName": "TransferJournalEntriesToGL",
                "Parameters": f"{ledger_id},{period_name},{application_id}",
            },
        )

    def get_gl_journals(self, ledger_id: int, period_name: str) -> list[dict]:
        data = self.get(
            "/fscmRestApi/resources/11.13.18.05/generalLedgerJournals",
            params={
                "q": f"LedgerId={ledger_id};PeriodName={period_name}",
                "fields": "JournalBatchId,JournalBatchName,TotalAcctDebit,TotalAcctCredit,Status",
                "limit": 500,
            },
        )
        return data.get("items", [])

    def get_trial_balance(self, ledger_id: int, period_name: str) -> list[dict]:
        data = self.get(
            "/fscmRestApi/resources/11.13.18.05/generalLedgerTrialBalances",
            params={
                "q": f"LedgerId={ledger_id};PeriodName={period_name}",
                "limit": 1000,
            },
        )
        return data.get("items", [])

    def get_intercompany_transactions(self, ledger_id: int, period_name: str) -> list[dict]:
        data = self.get(
            "/fscmRestApi/resources/11.13.18.05/intercompanyTransactions",
            params={
                "q": f"InitiatorLedgerId={ledger_id};PeriodName={period_name}",
                "limit": 500,
            },
        )
        return data.get("items", [])

    def send_notification(self, to_email: str, subject: str, body_html: str) -> dict:
        return self.post(
            "/fscmRestApi/resources/11.13.18.05/workflowNotifications",
            {"ToEmail": to_email, "Subject": subject, "BodyHTML": body_html},
        )
