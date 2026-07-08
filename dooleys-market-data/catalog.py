"""
Config layer for dooleys-market-data.
Reads catalog.yaml and sources.yaml, reconciles with the series table.
"""

import os
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional

import yaml

from db import get_market_data_dir, get_series, upsert_series, update_series_status

logger = logging.getLogger(__name__)


def _default_config_dir() -> Path:
    return get_market_data_dir() / "config"


def load_catalog(catalog_path: Optional[Path] = None) -> Dict[str, Any]:
    """
    Load the catalog YAML file.
    
    Returns a dict with keys:
        asset_classes: dict of group_name -> {description, series: [...]}
    """
    if catalog_path is None:
        catalog_path = _default_config_dir() / "catalog.yaml"
    
    if not catalog_path.exists():
        raise FileNotFoundError(f"Catalog not found: {catalog_path}")
    
    with open(catalog_path, "r") as fh:
        catalog = yaml.safe_load(fh)
    
    return catalog


def load_sources(sources_path: Optional[Path] = None) -> Dict[str, Any]:
    """
    Load the sources YAML file.
    
    Returns a dict with keys:
        sources: dict of source_name -> {base_url, auth_env, rate_limit_per_min, ...}
        defaults: dict of backfill_years, on_short_history, etc.
    """
    if sources_path is None:
        sources_path = _default_config_dir() / "sources.yaml"
    
    if not sources_path.exists():
        raise FileNotFoundError(f"Sources not found: {sources_path}")
    
    with open(sources_path, "r") as fh:
        sources = yaml.safe_load(fh)
    
    return sources


def normalize_sources(entry: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return the ordered list of source refs for a catalog/series entry.

    Accepts either the legacy single-source form (``source`` + ``source_symbol``)
    or the new chain form (``sources: [{source, symbol, kind?}, ...]``). Always
    returns a list of ``{"source", "symbol", "kind"}`` dicts (``kind`` may be
    ``None``). Returns ``[]`` when nothing usable is present.

    The chain lives in ``catalog.yaml``; it is the source of truth and is re-read
    at fetch time (the DB ``series`` row only stores the primary — element 0).
    """
    chain = entry.get("sources")
    if chain:
        out: List[Dict[str, Any]] = []
        for ref in chain:
            if not isinstance(ref, dict):
                continue
            src = ref.get("source")
            sym = ref.get("symbol", ref.get("source_symbol"))
            if not src or not sym:
                continue
            out.append({"source": src, "symbol": sym, "kind": ref.get("kind")})
        if out:
            return out
    # Legacy fallback
    src = entry.get("source")
    sym = entry.get("source_symbol")
    if src and sym:
        return [{"source": src, "symbol": sym, "kind": entry.get("table_kind")}]
    return []


def iter_catalog_series(catalog: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Public accessor: the flattened list of series dicts from the catalog
    (each with its parent asset_class injected). Loads the catalog if not given.
    """
    if catalog is None:
        catalog = load_catalog()
    return _flatten_catalog(catalog)


def staleness_grace_map(catalog: Optional[Dict[str, Any]] = None) -> Dict[str, int]:
    """Map of ticker -> staleness_grace_days override (for known-laggy feeds),
    read from the catalog. Empty if none defined."""
    out: Dict[str, int] = {}
    try:
        for entry in iter_catalog_series(catalog):
            g = entry.get("staleness_grace_days")
            if g is not None:
                try:
                    out[entry["ticker"]] = int(g)
                except (ValueError, TypeError):
                    pass
    except Exception as exc:  # noqa: BLE001 — best-effort; doctor must not crash
        logger.warning("Could not read staleness grace overrides: %s", exc)
    return out


def _flatten_catalog(catalog: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Flatten the nested catalog structure into a list of series dicts.
    Each series dict gets its parent asset_class injected.
    """
    result: List[Dict[str, Any]] = []
    asset_classes = catalog.get("asset_classes", {})
    
    for group_name, group_info in asset_classes.items():
        if not isinstance(group_info, dict):
            continue
        for series in group_info.get("series", []):
            if not isinstance(series, dict):
                continue
            entry = dict(series)
            entry["asset_class"] = group_name
            # Default status to active if not specified
            if "status" not in entry:
                entry["status"] = "active"
            # Default table_kind to observations if not specified
            if "table_kind" not in entry:
                entry["table_kind"] = "observations"
            result.append(entry)
    
    return result


def sync_catalog(
    conn: "sqlite3.Connection",  # type: ignore[name-defined] # noqa: F821
    catalog: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Reconcile the catalog YAML with the `series` database table.
    
    - New series in catalog: INSERT into series table.
    - Existing series with changed source/source_symbol: UPDATE.
    - Series in DB but not in catalog: set status='deprecated'.
    
    Returns a summary dict:
        {added: int, updated: int, deprecated: int, details: [...]}
    """
    import sqlite3
    
    if catalog is None:
        catalog = load_catalog()
    
    catalog_series = _flatten_catalog(catalog)
    catalog_tickers = {s["ticker"] for s in catalog_series}
    
    # Get all series currently in DB
    db_series = get_series(conn, status="%")
    db_by_ticker = {s["ticker"]: s for s in db_series}
    
    added = 0
    updated = 0
    deprecated = 0
    details: List[Dict[str, Any]] = []
    
    for cat_entry in catalog_series:
        ticker = cat_entry["ticker"]
        
        if ticker not in db_by_ticker:
            # New series — insert
            series_record = _catalog_to_series_record(cat_entry)
            sid = upsert_series(conn, series_record)
            added += 1
            details.append({"action": "added", "ticker": ticker, "series_id": sid})
            logger.info("Added series: %s (id=%s)", ticker, sid)
        else:
            # Existing — check for changes
            existing = db_by_ticker[ticker]
            needs_update = False
            
            for field in ["source", "source_symbol", "name", "unit", "frequency",
                          "table_kind", "asset_class", "subclass"]:
                cat_val = cat_entry.get(field)
                db_val = existing.get(field)
                if cat_val is not None and cat_val != db_val:
                    needs_update = True
                    break
            
            # Also check if status should be re-activated
            cat_status = cat_entry.get("status", "active")
            if existing.get("status") != cat_status:
                needs_update = True
            
            if needs_update:
                series_record = _catalog_to_series_record(cat_entry)
                # Preserve existing data not in catalog
                for preserve_field in ["first_available", "last_updated", "series_id"]:
                    if preserve_field not in series_record and preserve_field in existing:
                        series_record[preserve_field] = existing[preserve_field]
                sid = upsert_series(conn, series_record)
                updated += 1
                details.append({"action": "updated", "ticker": ticker, "series_id": sid})
                logger.info("Updated series: %s (id=%s)", ticker, sid)
    
    # Deprecate series in DB but not in catalog
    for ticker, db_entry in db_by_ticker.items():
        if ticker not in catalog_tickers and db_entry.get("status") != "deprecated":
            update_series_status(conn, db_entry["series_id"], "deprecated")
            deprecated += 1
            details.append(
                {"action": "deprecated", "ticker": ticker, "series_id": db_entry["series_id"]}
            )
            logger.info("Deprecated series: %s (id=%s)", ticker, db_entry["series_id"])
    
    return {
        "added": added,
        "updated": updated,
        "deprecated": deprecated,
        "details": details,
        "total_active": len(catalog_series),
        "total_in_db": len(db_series),
    }


def _catalog_to_series_record(cat_entry: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert a catalog entry to a series table record dict.
    Handles trigger_levels: converts dict to JSON string if present.
    """
    import json

    # Derive the primary source/symbol from a chain (element 0) so chain-form
    # entries satisfy the NOT NULL source/source_symbol columns. Legacy entries
    # already carry these fields, so setdefault leaves them untouched.
    refs = normalize_sources(cat_entry)
    if refs:
        cat_entry = dict(cat_entry)
        cat_entry.setdefault("source", refs[0]["source"])
        cat_entry.setdefault("source_symbol", refs[0]["symbol"])

    record: Dict[str, Any] = {}

    field_map = [
        "ticker", "name", "asset_class", "subclass", "source", "source_symbol",
        "unit", "frequency", "table_kind", "status", "notes",
    ]
    
    for field in field_map:
        if field in cat_entry:
            record[field] = cat_entry[field]
    
    # Handle trigger_levels
    if "trigger_levels" in cat_entry and cat_entry["trigger_levels"] is not None:
        if isinstance(cat_entry["trigger_levels"], dict):
            record["trigger_levels"] = json.dumps(cat_entry["trigger_levels"])
        else:
            record["trigger_levels"] = cat_entry["trigger_levels"]
    
    # Handle first_available if present
    if "first_available" in cat_entry:
        record["first_available"] = cat_entry["first_available"]
    
    # Handle extra catalog fields (eia_route, etc.) — store in notes.
    # 'sources' (the chain) is re-read from catalog.yaml at fetch time, so it is
    # NOT stashed here (it would bloat notes and the DB only needs the primary).
    extra_fields = {k: v for k, v in cat_entry.items()
                    if k not in field_map
                    and k not in ["trigger_levels", "first_available", "description", "sources"]}
    if extra_fields:
        existing_notes = record.get("notes", "")
        extra_json = json.dumps(extra_fields)
        record["notes"] = f"{existing_notes} | extra: {extra_json}".strip(" |")
    
    return record
