"""Unit tests for catalog.normalize_sources + chain-primary derivation."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from catalog import normalize_sources, _catalog_to_series_record  # noqa: E402


def test_legacy_single_source():
    e = {"source": "fred", "source_symbol": "DGS10", "table_kind": "observations"}
    assert normalize_sources(e) == [{"source": "fred", "symbol": "DGS10", "kind": "observations"}]


def test_chain_form():
    e = {"table_kind": "ohlcv", "sources": [
        {"source": "yahoo_direct", "symbol": "^GSPC"},
        {"source": "fred", "symbol": "SP500", "kind": "observations"}]}
    out = normalize_sources(e)
    assert out[0] == {"source": "yahoo_direct", "symbol": "^GSPC", "kind": None}
    assert out[1] == {"source": "fred", "symbol": "SP500", "kind": "observations"}


def test_chain_skips_malformed_and_falls_back_to_legacy_when_empty():
    assert normalize_sources({"sources": [{"symbol": "x"}], "source": "fred", "source_symbol": "M2"}) \
        == [{"source": "fred", "symbol": "M2", "kind": None}]


def test_empty_when_nothing_usable():
    assert normalize_sources({"name": "orphan"}) == []


def test_record_uses_chain_primary():
    rec = _catalog_to_series_record({
        "ticker": "SPX", "name": "S&P 500", "asset_class": "equity-index",
        "table_kind": "ohlcv", "sources": [
            {"source": "yahoo_direct", "symbol": "^GSPC"},
            {"source": "fred", "symbol": "SP500", "kind": "observations"}]})
    assert rec["source"] == "yahoo_direct" and rec["source_symbol"] == "^GSPC"
    # the raw chain must NOT be stashed into notes
    assert "sources" not in (rec.get("notes") or "")
