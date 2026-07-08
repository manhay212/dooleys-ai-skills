"""Unit tests for the credential-gated source availability check."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from market_data import _source_available  # noqa: E402

CFG = {"sources": {
    "yahoo_direct": {"auth_env": None},
    "eodhd": {"auth_env": "EODHD_API_KEY"},
}}


def test_keyless_available():
    assert _source_available("yahoo_direct", CFG) is True


def test_gated_unavailable_without_env(monkeypatch):
    monkeypatch.delenv("EODHD_API_KEY", raising=False)
    assert _source_available("eodhd", CFG) is False


def test_gated_available_with_env(monkeypatch):
    monkeypatch.setenv("EODHD_API_KEY", "abc")
    assert _source_available("eodhd", CFG) is True


def test_unknown_source_unavailable():
    assert _source_available("nope", CFG) is False
