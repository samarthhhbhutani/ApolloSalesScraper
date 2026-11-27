"""Minimal Apollo REST client (official API) with retry, rate-limit and pagination handling.

Credentials are read ONLY from the APOLLO_API_KEY environment variable; nothing is
ever written to disk or committed.

Note on this research run: the session used Apollo's official MCP integration
(OAuth) rather than an API key. On the connected Apollo *Free* plan the
endpoints /mixed_people/api_search, /people/match, /people/bulk_match and
/agents/task return API_INACCESSIBLE; /organizations (lookup) and
/organizations/enrich work. This client is provided so the same workflow can be
re-run unattended once a paid plan / API key is available.
"""
from __future__ import annotations

import os
import time
from typing import Iterator

import requests

BASE = "https://api.apollo.io/api/v1"


class ApolloError(RuntimeError):
    pass


class ApolloClient:
    def __init__(self, api_key: str | None = None, max_retries: int = 5, min_interval: float = 0.6):
        self.api_key = api_key or os.environ.get("APOLLO_API_KEY")
        if not self.api_key:
            raise ApolloError("Set APOLLO_API_KEY in the environment (never hard-code it).")
        self.max_retries = max_retries
        self.min_interval = min_interval
        self._last = 0.0
        self.s = requests.Session()
        self.s.headers.update({"X-Api-Key": self.api_key, "Content-Type": "application/json",
                               "Cache-Control": "no-cache"})

    def _post(self, path: str, payload: dict) -> dict:
        for attempt in range(self.max_retries):
            wait = self.min_interval - (time.time() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.time()
            try:
                r = self.s.post(f"{BASE}{path}", json=payload, timeout=60)
            except requests.RequestException:
                time.sleep(2 ** attempt)
                continue
            if r.status_code == 429:  # rate limited: honour Retry-After or back off
                time.sleep(float(r.headers.get("Retry-After", 2 ** (attempt + 1))))
                continue
            if r.status_code >= 500:
                time.sleep(2 ** attempt)
                continue
            data = r.json() if r.content else {}
            if r.status_code >= 400:
                raise ApolloError(f"{path} -> {r.status_code}: {data.get('error') or data}")
            return data
        raise ApolloError(f"{path}: retries exhausted")

    # --- free discovery -------------------------------------------------
    def org_lookup(self, **filters) -> Iterator[dict]:
        page = 1
        while True:
            data = self._post("/mixed_companies/search", {**filters, "page": page, "per_page": 100,
                                                          "display_mode": "fuzzy_select_mode"})
            orgs = data.get("organizations", []) + data.get("accounts", [])
            yield from orgs
            if len(orgs) < 100:
                return
            page += 1

    def people_search(self, **filters) -> Iterator[dict]:
        page = 1
        while True:
            data = self._post("/mixed_people/api_search", {**filters, "page": page, "per_page": 100})
            people = data.get("people", [])
            yield from people
            pg = data.get("pagination", {})
            if page >= pg.get("total_pages", page):
                return
            page += 1

    # --- credit-consuming ------------------------------------------------
    def org_enrich(self, domain: str) -> dict:
        return self._post("/organizations/enrich", {"domain": domain})

    def people_bulk_match(self, details: list[dict]) -> dict:
        assert len(details) <= 10
        return self._post("/people/bulk_match", {"details": details, "reveal_personal_emails": False})
