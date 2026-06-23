#!/usr/bin/env python3
"""Scan macro/investment-relevant Polymarket categories and emit a ranked,
de-noised JSON feed of significant markets. Keyless."""
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
DEFAULT_WATCHLIST = os.path.join(HERE, "config", "watchlist.json")
DEFAULT_OUTPUT = os.path.join(HERE, "output_polymarket_reader.json")


def _csv(value):
    return [x.strip() for x in value.split(",") if x.strip()] if value else None


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Scan Polymarket macro categories for significant markets.")
    p.add_argument("--categories", type=_csv, help="bucket names, e.g. monetary,geopolitics")
    p.add_argument("--tags", type=_csv, help="raw tag slugs (overrides --categories)")
    p.add_argument("--min-score", type=float, default=0.0)
    p.add_argument("--min-volume", type=float, default=None, help="override config min_volume floor")
    p.add_argument("--limit", type=int, default=40, help="max events in output")
    p.add_argument("--scan-limit", type=int, default=40, help="events fetched per tag")
    p.add_argument("--all", action="store_true", help="include filtered-out events too")
    p.add_argument("--config", default=DEFAULT_CONFIG)
    p.add_argument("--watchlist", default=DEFAULT_WATCHLIST)
    p.add_argument("--output", default=DEFAULT_OUTPUT)
    return p.parse_args(argv)


def load_watchlist(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return [pc.parse_event_ref(e)["value"] for e in (json.load(fh).get("events") or [])]
    except (FileNotFoundError, ValueError):
        return []


def main(argv=None):
    args = parse_args(argv)
    config = pc.load_config(args.config)
    if args.min_volume is not None:
        config["thresholds"]["min_volume"] = args.min_volume
    th, we = config["thresholds"], config["weights"]
    slugs_by_bucket = pc.resolve_slugs(config, args.categories, args.tags)
    if not slugs_by_bucket:
        print("No categories/tags resolved.", file=sys.stderr)
        return 1

    client = PolymarketClient()
    now = datetime.now(timezone.utc)
    errors = {}
    collected = {}  # event_id -> [raw_event, set(buckets), set(tags)]

    try:
        for bucket, slugs in slugs_by_bucket.items():
            for slug in slugs:
                try:
                    events = client.get_events_by_tag(slug, limit=args.scan_limit)
                except PolymarketError as e:
                    errors[f"tag:{slug}"] = str(e)
                    continue
                for ev in events:
                    eid = str(ev.get("id"))
                    if eid in collected:
                        collected[eid][1].add(bucket)
                        collected[eid][2].add(slug)
                    else:
                        collected[eid] = [ev, {bucket}, {slug}]
    except Exception as e:  # noqa: BLE001 — fatal before any usable result
        print(f"Fatal: {type(e).__name__}: {e}", file=sys.stderr)
        return 2

    enriched = [pc.enrich_event(ev, now, sorted(b), sorted(t), th, we)
                for ev, b, t in collected.values()]

    # Watchlist: always-include events by slug (deduped against the scan).
    seen_slugs = {e["slug"] for e in enriched}
    for slug in load_watchlist(args.watchlist):
        if slug in seen_slugs:
            for e in enriched:
                if e["slug"] == slug:
                    e["watchlisted"] = True
            continue
        try:
            ev = client.get_event_by_slug(slug)
        except PolymarketError as e:
            errors[f"watchlist:{slug}"] = str(e)
            continue
        if ev:
            enriched.append(pc.enrich_event(ev, now, ["watchlist"], [], th, we, watchlisted=True))

    kept = [e for e in enriched if pc.passes_denoise(e, th, args.min_score)]
    ranked = pc.rank_and_cap(kept, args.limit)
    kept_ids = {id(e) for e in ranked}
    filtered_out = [e for e in enriched if id(e) not in kept_ids] if args.all else []

    output = {
        "timestamp": pc.now_iso(),
        "params": {
            "categories": args.categories or list(slugs_by_bucket.keys()),
            "tags": args.tags, "min_score": args.min_score,
            "min_volume": th["min_volume"], "limit": args.limit,
        },
        "buckets_scanned": list(slugs_by_bucket.keys()),
        "counts": {
            "events_scanned": len(enriched),
            "events_kept": len(ranked),
            "filtered_out": len(enriched) - len(ranked),
        },
        "events": ranked,
        "filtered_out": filtered_out,
        "errors": errors,
    }
    with open(args.output, "w", encoding="utf-8") as fh:
        json.dump(output, fh, indent=2, ensure_ascii=False)
    print(f"Wrote {args.output}: {len(ranked)} events kept "
          f"(scanned {len(enriched)}, filtered {len(enriched) - len(ranked)}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
