"""US-04 — unit tests for core/prices.py.

All tests run offline: HTTP calls are monkeypatched. Cache reads/writes use
tmp_path so the real data/cache/ directory is not touched.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

import core.prices as prices_mod
from core.prices import (
    AlphaVantageProvider,
    MarketstackProvider,
    _cache_path,
    get_provider,
)


# ---------- helpers ----------

_SAMPLE_MARKETSTACK_PAYLOAD = {
    "pagination": {"limit": 1000, "offset": 0, "count": 1, "total": 1},
    "data": [
        {
            "date": "2025-02-28T00:00:00+0000",
            "open": 0.955,
            "high": 0.98,
            "low": 0.945,
            "close": 0.97,
            "volume": 1351001.0,
            "symbol": "OML.AX",
        }
    ],
}

_SAMPLE_AV_PAYLOAD = {
    "Meta Data": {"2. Symbol": "OML.AX"},
    "Time Series (Daily)": {
        "2025-02-28": {
            "1. open": "0.955",
            "2. high": "0.980",
            "3. low": "0.945",
            "4. close": "0.970",
        }
    },
}


# ---------- cache helpers ----------

def test_cache_path_format():
    p = _cache_path("marketstack", "OML.AX", "eod", "2025-01-01", "2025-01-31")
    assert "marketstack" in p.name
    assert "OML_AX" in p.name
    assert "2025-01-01" in p.name
    assert "2025-01-31" in p.name
    assert p.suffix == ".json"


# ---------- MarketstackProvider — cache hit ----------

def test_marketstack_returns_cached_data(tmp_path, monkeypatch):
    monkeypatch.setattr(prices_mod, "_CACHE_DIR", tmp_path)

    path = _cache_path("marketstack", "OML.AX", "eod", "2025-02-28", "2025-02-28")
    # Recompute path with monkeypatched dir
    real_path = tmp_path / path.name
    real_path.write_text(json.dumps(_SAMPLE_MARKETSTACK_PAYLOAD))

    provider = MarketstackProvider(api_key="dummy_key")
    result = provider.get_price_history("2025-02-28", "2025-02-28")

    assert result["available"] is True
    assert len(result["data"]) == 1
    assert result["data"][0]["close"] == pytest.approx(0.97)
    assert result["source"] == "marketstack"


# ---------- MarketstackProvider — live call cached to disk ----------

def test_marketstack_live_call_writes_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(prices_mod, "_CACHE_DIR", tmp_path)

    mock_resp = MagicMock()
    mock_resp.json.return_value = _SAMPLE_MARKETSTACK_PAYLOAD
    mock_resp.raise_for_status.return_value = None

    with patch("core.prices.httpx.get", return_value=mock_resp) as mock_get:
        provider = MarketstackProvider(api_key="valid_key")
        result = provider.get_price_history("2025-02-28", "2025-02-28")

    assert result["available"] is True
    assert len(result["data"]) == 1
    mock_get.assert_called_once()

    # Cache file must have been written
    path = _cache_path("marketstack", "OML.AX", "eod", "2025-02-28", "2025-02-28")
    cache_file = tmp_path / path.name
    assert cache_file.exists()
    cached = json.loads(cache_file.read_text())
    assert cached["data"][0]["close"] == pytest.approx(0.97)


# ---------- MarketstackProvider — second call uses cache, not HTTP ----------

def test_marketstack_second_call_uses_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(prices_mod, "_CACHE_DIR", tmp_path)

    mock_resp = MagicMock()
    mock_resp.json.return_value = _SAMPLE_MARKETSTACK_PAYLOAD
    mock_resp.raise_for_status.return_value = None

    with patch("core.prices.httpx.get", return_value=mock_resp) as mock_get:
        provider = MarketstackProvider(api_key="valid_key")
        provider.get_price_history("2025-02-28", "2025-02-28")  # fills cache
        provider.get_price_history("2025-02-28", "2025-02-28")  # must hit cache

    assert mock_get.call_count == 1  # only one HTTP call total


# ---------- MarketstackProvider — HTTP failure returns unavailable ----------

def test_marketstack_http_failure_returns_unavailable(tmp_path, monkeypatch):
    monkeypatch.setattr(prices_mod, "_CACHE_DIR", tmp_path)

    with patch("core.prices.httpx.get", side_effect=Exception("connection timeout")):
        provider = MarketstackProvider(api_key="invalid_key")
        result = provider.get_price_history("2025-02-28", "2025-02-28")

    assert result["available"] is False
    assert "unavailable" in result["error"].lower() or "timeout" in result["error"].lower() or "connection" in result["error"].lower()


# ---------- AlphaVantageProvider — returns unavailable for empty payload ----------

def test_alphavantage_empty_payload_returns_unavailable(tmp_path, monkeypatch):
    monkeypatch.setattr(prices_mod, "_CACHE_DIR", tmp_path)

    mock_resp = MagicMock()
    mock_resp.json.return_value = {}  # ASX not covered — returns {}
    mock_resp.raise_for_status.return_value = None

    with patch("core.prices.httpx.get", return_value=mock_resp):
        provider = AlphaVantageProvider(api_key="dummy_av_key")
        result = provider.get_price_history("2025-02-28", "2025-02-28")

    assert result["available"] is False
    assert "alpha vantage" in result["error"].lower()


# ---------- AlphaVantageProvider — returns data when payload has time series ----------

def test_alphavantage_returns_data_when_series_present(tmp_path, monkeypatch):
    monkeypatch.setattr(prices_mod, "_CACHE_DIR", tmp_path)

    mock_resp = MagicMock()
    mock_resp.json.return_value = _SAMPLE_AV_PAYLOAD
    mock_resp.raise_for_status.return_value = None

    with patch("core.prices.httpx.get", return_value=mock_resp):
        provider = AlphaVantageProvider(api_key="dummy_av_key")
        result = provider.get_price_history("2025-02-01", "2025-02-28")

    assert result["available"] is True
    assert len(result["data"]) == 1
    assert result["data"][0]["close"] == pytest.approx(0.97)


# ---------- get_provider factory ----------

def test_get_provider_returns_marketstack_when_key_set(monkeypatch):
    monkeypatch.setenv("MARKETSTACK_API_KEY", "ms_test_key")
    monkeypatch.delenv("ALPHAVANTAGE_API_KEY", raising=False)
    provider = get_provider()
    assert isinstance(provider, MarketstackProvider)


def test_get_provider_returns_alphavantage_when_only_av_key_set(monkeypatch):
    monkeypatch.delenv("MARKETSTACK_API_KEY", raising=False)
    monkeypatch.setenv("ALPHAVANTAGE_API_KEY", "av_test_key")
    provider = get_provider()
    assert isinstance(provider, AlphaVantageProvider)


def test_get_provider_returns_none_when_no_keys(monkeypatch):
    monkeypatch.delenv("MARKETSTACK_API_KEY", raising=False)
    monkeypatch.delenv("ALPHAVANTAGE_API_KEY", raising=False)
    provider = get_provider()
    assert provider is None


def test_get_provider_prefers_marketstack_over_alphavantage(monkeypatch):
    monkeypatch.setenv("MARKETSTACK_API_KEY", "ms_test_key")
    monkeypatch.setenv("ALPHAVANTAGE_API_KEY", "av_test_key")
    provider = get_provider()
    assert isinstance(provider, MarketstackProvider)
