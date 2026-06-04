import json
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterator, List, Optional

import requests


class ReportingClientError(Exception):
    """Raised for configuration, network, and server-errors from the Reporting client."""


@dataclass
class ReportingAPIConfig:
    """
    Minimal configuration for the Registration Reporting API.

    Assumes DRF router endpoints like:
      - /api/registration/report-columns/
      - /api/registration/report-columns/<key>/
      - /api/registration/report-rows/
    """
    base_url: str
    columns_list_path: str = "/api/registration/report-columns/"
    columns_detail_pattern: str = "/api/registration/report-columns/{key}/"
    rows_path: str = "/api/registration/report-rows/"
    timeout_s: int = 20

    @property
    def columns_url(self) -> str:
        return self.base_url.rstrip("/") + self.columns_list_path

    def column_url(self, key: str) -> str:
        return self.base_url.rstrip("/") + self.columns_detail_pattern.format(key=key)

    @property
    def rows_url(self) -> str:
        return self.base_url.rstrip("/") + self.rows_path


class ReportingClient:
    """
    Client for interacting with Registration Reporting endpoints.
    Patterned after WarehouseClient:
      - token_getter supplies OAuth token (no "Bearer " prefix required)
      - handles DRF pagination via `next` links
    """

    def __init__(self, config: ReportingAPIConfig, token_getter: Callable[[], str]):
        if not callable(token_getter):
            raise TypeError("token_getter must be callable and return a token string.")
        self.config = config
        self._token_getter = token_getter

    # ---------------------------------------------------------------------
    # Columns
    # ---------------------------------------------------------------------
    def list_columns(self) -> Dict[str, Any]:
        """
        GET columns metadata (list endpoint).
        Returns the JSON dict:
          {"report": ..., "defaults": [...], "system": [...], "columns": [...]}
        """
        return self._GET_json(self.config.columns_url)

    def get_column(self, *, key: str) -> Dict[str, Any]:
        """
        GET column metadata (detail endpoint).
        Returns the JSON dict:
          {"report": ..., "defaults": [...], "system": [...], "column": {...}}
        """
        return self._GET_json(self.config.column_url(key))

    # ---------------------------------------------------------------------
    # Rows
    # ---------------------------------------------------------------------
    def list_rows(
        self,
        *,
        params: Optional[Dict[str, Any]] = None,
        page_size: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Fetch ALL rows matching params, following pagination.
        """
        return list(self.iter_rows(params=params, page_size=page_size))

    def iter_rows(
        self,
        *,
        params: Optional[Dict[str, Any]] = None,
        page_size: Optional[int] = None,
    ) -> Iterator[Dict[str, Any]]:
        """
        Lazily iterate over matching rows. Follows DRF pagination via `next` links.

        Notes:
          - This assumes your report rows endpoint returns either:
              {"results": [...], "next": "..."}  (paginated)
            or:
              [...]                               (unpaginated)
        """
        q: Dict[str, Any] = {}
        if params:
            q.update(params)
        if page_size is not None:
            # DRF limit-offset pagination commonly supports limit/offset
            q.setdefault("limit", int(page_size))

        url = self.config.rows_url
        first = True

        while url:
            payload = self._GET_json(url, params=q if first else None)
            first = False

            if isinstance(payload, dict) and "results" in payload:
                items = payload.get("results") or []
                for item in items:
                    yield item
                url = payload.get("next")
            elif isinstance(payload, list):
                for item in payload:
                    yield item
                url = None
            else:
                raise ReportingClientError("Unexpected response from report rows endpoint.")

    # ---------------------------------------------------------------------
    # Internals
    # ---------------------------------------------------------------------
    def _bearer(self) -> str:
        token = self._token_getter()
        if not token:
            raise ReportingClientError("No access token available.")
        return token if token.lower().startswith("bearer ") else f"Bearer {token}"

    def _GET_json(self, url: str, params: Optional[Dict[str, Any]] = None) -> Any:
        headers = {"Authorization": self._bearer(), "Accept": "application/json"}
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=self.config.timeout_s)
        except requests.RequestException as e:
            raise ReportingClientError(f"GET {url} failed: {e}") from e

        if not resp.ok:
            try:
                err = resp.json()
                detail = err.get("detail") or err
            except ValueError:
                detail = resp.text or f"HTTP {resp.status_code}"
            raise ReportingClientError(f"GET {url} failed: {detail}")

        try:
            return resp.json()
        except ValueError as e:
            raise ReportingClientError("Response was not valid JSON.") from e
