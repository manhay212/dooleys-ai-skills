#!/usr/bin/env python3
"""Deep-dive a single Polymarket event/market by URL, slug, or id. Optionally
attach the odds time-series (price history) per market. Keyless."""
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
DEFAULT_OUTPUT = os.path.join(HERE, "output_polymarket_event.json")


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Deep-dive one Polymarket event by url/slug/id.")
    p.add_argument("ref", help="Polymarket event URL, slug, or numeric id")
    p.add_argument("--history", action="store_true", help="attach price-history per market")
    p.add_argument("--interval", default="1w", help="history window (e.g. 1d,1w,1m,max)")
    p.add_argument("--fidelity", type=int, default=180, help="history resolution (minutes)")
    p.add_argument("--config", default=DEFAULT_CONFIG)
    p.add_argument("--output", default=DEFAULT_OUTPUT)
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    config = pc.load_config(args.config)
    th, we = config["thresholds"], config["weights"]
    client = PolymarketClient()
    ref = pc.parse_event_ref(args.ref)
    now = datetime.now(timezone.utc)
    errors = {}

    try:
        raw = (client.get_event_by_id(ref["value"]) if ref["kind"] == "id"
               else client.get_event_by_slug(ref["value"]))
    except PolymarketError as e:
        print(f"Lookup failed: {e}", file=sys.stderr)
        return 1
    if not raw:
        print(f"Event not found for ref: {args.ref}", file=sys.stderr)
        return 1

    record = pc.enrich_event(raw, now, [], [], th, we)
    record["description"] = raw.get("description")

    if args.history:
        raw_markets = raw.get("markets") or []
        for i, mrec in enumerate(record["markets"]):
            token_ids = pc.coerce_list(raw_markets[i].get("clobTokenIds")) if i < len(raw_markets) else []
            if not token_ids:
                mrec["price_history"] = []
                continue
            try:
                mrec["price_history"] = client.get_price_history(
                    token_ids[0], interval=args.interval, fidelity=args.fidelity)
            except PolymarketError as e:
                mrec["price_history"] = []
                errors[f"history:{mrec.get('question')}"] = str(e)

    output = {"timestamp": pc.now_iso(), "requested_ref": args.ref,
              "event": record, "errors": errors}
    with open(args.output, "w", encoding="utf-8") as fh:
        json.dump(output, fh, indent=2, ensure_ascii=False)
    print(f"Wrote {args.output}: '{record['title']}' "
          f"({len(record['markets'])} markets{', with history' if args.history else ''}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
