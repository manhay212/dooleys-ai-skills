#!/usr/bin/env python3
"""Ad-hoc Polymarket keyword search: 'what does the market say about <X>?'
Returns matching events with the same signal block as the reader. Keyless."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

import polymarket_common as pc
from polymarket_client import PolymarketClient, PolymarketError

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CONFIG = os.path.join(HERE, "config", "categories.json")
DEFAULT_OUTPUT = os.path.join(HERE, "output_polymarket_search.json")


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Search Polymarket events by keyword.")
    p.add_argument("query", nargs="?", help="search text")
    p.add_argument("--query", dest="query_opt", help="search text (alt to positional)")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--config", default=DEFAULT_CONFIG)
    p.add_argument("--output", default=DEFAULT_OUTPUT)
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    query = args.query or args.query_opt
    if not query:
        print("No query provided.", file=sys.stderr)
        return 1
    config = pc.load_config(args.config)
    th, we = config["thresholds"], config["weights"]
    client = PolymarketClient()
    now = datetime.now(timezone.utc)
    errors = {}
    try:
        events = client.search_events(query, limit=args.limit)
    except PolymarketError as e:
        events, errors["search"] = [], str(e)

    enriched = [pc.enrich_event(ev, now, [], [], th, we) for ev in events]
    enriched.sort(key=lambda e: e.get("event_significance", 0.0), reverse=True)

    output = {
        "timestamp": pc.now_iso(),
        "query": query,
        "count": len(enriched),
        "events": enriched,
        "errors": errors,
    }
    with open(args.output, "w", encoding="utf-8") as fh:
        json.dump(output, fh, indent=2, ensure_ascii=False)
    print(f"Wrote {args.output}: {len(enriched)} events for '{query}'.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
