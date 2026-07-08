"""
Source adapter registry and base interface for dooleys-market-data.

Each adapter module exposes a single function:

    def fetch(source_symbol: str, start: str | None, end: str | None, cfg: dict) -> pd.DataFrame:
        ...

Returns DataFrame indexed by date (UTC, daily) with either:
  - ['open', 'high', 'low', 'close', 'adj_close', 'volume'] (ohlcv), or
  - ['value'] (observations)

Must handle: missing key, 'max available' (start=None), rate limits (sleep+retry),
and return EMPTY frame (not raise) on soft failure so the core can log + continue.
"""

import importlib
import logging
from typing import Any, Dict, Optional, Protocol, runtime_checkable

import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Protocol for type checking (optional — adapters are duck-typed at runtime)
# ---------------------------------------------------------------------------

@runtime_checkable
class SourceAdapter(Protocol):
    """Expected shape of a source adapter module: exposes a fetch callable."""

    def fetch(
        self, source_symbol: str, start: Optional[str], end: Optional[str], cfg: Dict[str, Any]
    ) -> pd.DataFrame:
        ...


# ---------------------------------------------------------------------------
# Registry of known adapters (map adapter name → module name)
# ---------------------------------------------------------------------------

_ADAPTER_REGISTRY: Dict[str, str] = {
    "fred": "sources.fred",
    "stooq": "sources.stooq",
    "eia": "sources.eia",
    "coingecko": "sources.coingecko",
    "treasury": "sources.treasury",
    "yahoo": "sources.yahoo",
    "yahoo_direct": "sources.yahoo_direct",
    "eodhd": "sources.eodhd",
}


def register_adapter(name: str, module_path: str) -> None:
    """Add a new adapter to the registry at runtime."""
    _ADAPTER_REGISTRY[name] = module_path
    logger.info("Registered adapter '%s' → %s", name, module_path)


def list_adapters() -> Dict[str, str]:
    """Return a copy of the current adapter registry."""
    return dict(_ADAPTER_REGISTRY)


def get_adapter(name: str):
    """
    Import and return the named adapter module.

    Raises ImportError if the adapter cannot be found or loaded.
    """
    module_path = _ADAPTER_REGISTRY.get(name)
    if module_path is None:
        raise ImportError(
            f"Unknown adapter '{name}'. Known adapters: {list(_ADAPTER_REGISTRY.keys())}"
        )
    try:
        mod = importlib.import_module(module_path)
    except ImportError as exc:
        raise ImportError(
            f"Failed to import adapter '{name}' from '{module_path}': {exc}"
        ) from exc

    if not hasattr(mod, "fetch"):
        raise AttributeError(
            f"Adapter module '{module_path}' does not expose a 'fetch' function"
        )

    return mod
