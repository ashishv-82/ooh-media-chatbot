"""PriceProvider interface + MarketstackProvider + AlphaVantageProvider.

This is the ONLY module in the project that makes HTTP calls for market data.
Every API response is cached as JSON in data/cache/ keyed by:
  {provider}_{symbol}_{function}_{start}_{end}.json

Marketstack v2 (HTTPS, OML.AX) is primary. Alpha Vantage is kept as a
scaffold but its free tier does not cover ASX listings — it returns {} for
OML.AX. See DECISIONS.md for the empirical rationale.
"""

from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import httpx

SYMBOL = "OML.AX"
_CACHE_DIR = Path("data/cache")


# ---------- cache helpers ----------

def _cache_path(provider: str, symbol: str, function: str, start: str, end: str) -> Path:
    safe_symbol = symbol.replace(".", "_")
    return _CACHE_DIR / f"{provider}_{safe_symbol}_{function}_{start}_{end}.json"


def _read_cache(path: Path) -> Any | None:
    try:
        if path.exists():
            return json.loads(path.read_text())
    except Exception:
        pass
    return None


def _write_cache(path: Path, data: Any) -> None:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


# ---------- shared result shape ----------

def _ok(data: list[dict[str, Any]], source: str) -> dict[str, Any]:
    return {"available": True, "data": data, "source": source, "symbol": SYMBOL}


def _unavailable(error: str, source: str) -> dict[str, Any]:
    return {"available": False, "error": error, "source": source, "symbol": SYMBOL}


# ---------- abstract interface ----------

class PriceProvider(ABC):
    """Uniform interface for market data providers.

    get_price_history always returns a dict with at minimum:
      {"available": True/False, "source": str, "symbol": str}
    On success:  {"available": True,  "data": list[dict], ...}
    On failure:  {"available": False, "error": str, ...}

    Each item in "data" has at minimum: {"date": str, "close": float}.
    """

    @abstractmethod
    def get_price_history(self, start: str, end: str) -> dict[str, Any]:
        """Return EOD price history for OML.AX between start and end (YYYY-MM-DD)."""
        ...


# ---------- Marketstack v2 (primary) ----------

class MarketstackProvider(PriceProvider):
    """Marketstack v2 EOD endpoint over HTTPS with symbol OML.AX.

    Free tier on v2/HTTPS covers ASX listings. v1/HTTP returns 406.
    """

    _BASE_URL = "https://api.marketstack.com/v2/eod"
    NAME = "marketstack"

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    def get_price_history(self, start: str, end: str) -> dict[str, Any]:
        path = _cache_path(self.NAME, SYMBOL, "eod", start, end)
        cached = _read_cache(path)
        if cached is not None:
            return _ok(cached.get("data", []), self.NAME)

        params: dict[str, Any] = {
            "access_key": self._api_key,
            "symbols": SYMBOL,
            "date_from": start,
            "date_to": end,
            "limit": 1000,
        }
        try:
            resp = httpx.get(self._BASE_URL, params=params, timeout=15)
            resp.raise_for_status()
            payload = resp.json()
        except Exception as exc:
            return _unavailable(f"Marketstack request failed: {exc}", self.NAME)

        if not isinstance(payload.get("data"), list) or not payload["data"]:
            error_msg = payload.get("error", {}).get("message") if isinstance(payload.get("error"), dict) else None
            return _unavailable(
                error_msg or "Marketstack returned no data for the requested period",
                self.NAME,
            )

        _write_cache(path, payload)
        return _ok(payload["data"], self.NAME)


# ---------- Alpha Vantage (secondary scaffold) ----------

class AlphaVantageProvider(PriceProvider):
    """Alpha Vantage daily time-series scaffold.

    The free tier does not cover ASX listings — OML.AX returns {} (no error,
    just an empty response). Kept behind PriceProvider for extensibility only.
    """

    _BASE_URL = "https://www.alphavantage.co/query"
    NAME = "alphavantage"

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    def get_price_history(self, start: str, end: str) -> dict[str, Any]:
        path = _cache_path(self.NAME, SYMBOL, "TIME_SERIES_DAILY", start, end)
        cached = _read_cache(path)
        if cached is not None:
            return _ok(cached.get("data", []), self.NAME)

        params = {
            "function": "TIME_SERIES_DAILY",
            "symbol": SYMBOL,
            "outputsize": "full",
            "apikey": self._api_key,
        }
        try:
            resp = httpx.get(self._BASE_URL, params=params, timeout=15)
            resp.raise_for_status()
            payload = resp.json()
        except Exception as exc:
            return _unavailable(f"Alpha Vantage request failed: {exc}", self.NAME)

        series = payload.get("Time Series (Daily)")
        if not series:
            note = (
                payload.get("Information")
                or payload.get("Note")
                or "No data returned (ASX not covered on Alpha Vantage free tier)"
            )
            return _unavailable(f"Alpha Vantage: {note}", self.NAME)

        data = _av_filter(series, start, end)
        if not data:
            return _unavailable(
                "Alpha Vantage returned no data for the requested date range",
                self.NAME,
            )

        _write_cache(path, {"data": data})
        return _ok(data, self.NAME)


def _av_filter(series: dict[str, Any], start: str, end: str) -> list[dict[str, Any]]:
    """Normalise Alpha Vantage time-series to the shared data shape, filtered to [start, end]."""
    rows = []
    for date_str, vals in sorted(series.items()):
        if start <= date_str <= end:
            rows.append(
                {
                    "date": f"{date_str}T00:00:00+0000",
                    "open": float(vals.get("1. open", 0)),
                    "high": float(vals.get("2. high", 0)),
                    "low": float(vals.get("3. low", 0)),
                    "close": float(vals.get("4. close", 0)),
                }
            )
    return rows


# ---------- factory ----------

def get_provider() -> PriceProvider | None:
    """Return the primary available price provider, or None if no key is configured.

    Marketstack is primary (v2/HTTPS/OML.AX works on free tier).
    Alpha Vantage is the secondary scaffold (ASX not covered on free tier).
    """
    ms_key = os.environ.get("MARKETSTACK_API_KEY", "").strip()
    if ms_key:
        return MarketstackProvider(ms_key)

    av_key = os.environ.get("ALPHAVANTAGE_API_KEY", "").strip()
    if av_key:
        return AlphaVantageProvider(av_key)

    return None
