"""Unit tests for the pure logic in threads_common.

These cover the parsing/window/config logic that does NOT need a browser, so they
run fast and offline (`python3 -m pytest tests/` or `python3 tests/test_threads_common.py`).
"""
import os
import sys
import json
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import threads_common as tc


def test_normalize_username_variants():
    assert tc.normalize_username("@Zuck") == "zuck"
    assert tc.normalize_username("zuck") == "zuck"
    assert tc.normalize_username("  @Mosseri  ") == "mosseri"
    assert tc.normalize_username("https://www.threads.com/@zuck") == "zuck"
    assert tc.normalize_username("/@zuck/post/ABC") == "zuck"


def test_shortcode_from_url():
    assert tc.shortcode_from_url("/@zuck/post/DZpPDXbCeTt") == "DZpPDXbCeTt"
    assert tc.shortcode_from_url("https://www.threads.com/@zuck/post/DZaExc0ESvs?x=1") == "DZaExc0ESvs"
    assert tc.shortcode_from_url("/@zuck") is None


def test_parse_count():
    assert tc.parse_count("846") == 846
    assert tc.parse_count("17.6K") == 17600
    assert tc.parse_count("1.2M") == 1200000
    assert tc.parse_count("1,234") == 1234
    assert tc.parse_count("") is None
    assert tc.parse_count(None) is None
    assert tc.parse_count("Like") is None  # no digits -> not a count


def test_parse_iso_and_window():
    cutoff = tc.compute_cutoff(now=datetime(2026, 6, 19, 12, 0, tzinfo=timezone.utc), within_hours=48)
    assert cutoff == datetime(2026, 6, 17, 12, 0, tzinfo=timezone.utc)

    recent = tc.parse_iso("2026-06-18T10:00:00.000Z")
    old = tc.parse_iso("2026-06-01T10:00:00.000Z")
    assert tc.within_window(recent, cutoff) is True
    assert tc.within_window(old, cutoff) is False
    # tz-aware comparison should not raise
    assert recent.tzinfo is not None


def test_load_accounts_from_arg():
    # CSV arg wins, strips @ and whitespace, dedupes preserving order
    assert tc.load_accounts("@zuck, mosseri ,zuck") == ["zuck", "mosseri"]


def test_load_accounts_from_file():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "accounts.json"
        p.write_text(json.dumps({"usernames": ["@A", "b", "B"]}))
        assert tc.load_accounts(None, accounts_path=p) == ["a", "b"]


def test_load_accounts_missing_file_returns_empty():
    assert tc.load_accounts(None, accounts_path=Path("/nonexistent/accounts.json")) == []


def test_load_credentials_env_first(monkeypatch=None):
    os.environ["THREADS_USERNAME"] = "envuser"
    os.environ["THREADS_PASSWORD"] = "envpass"
    try:
        creds = tc.load_credentials(config_path=Path("/nonexistent/credentials.json"))
        assert creds == {"username": "envuser", "password": "envpass"}
    finally:
        del os.environ["THREADS_USERNAME"]
        del os.environ["THREADS_PASSWORD"]


def test_load_credentials_file_fallback():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "credentials.json"
        p.write_text(json.dumps({"username": "fileuser", "password": "filepass"}))
        # ensure env not set
        os.environ.pop("THREADS_USERNAME", None)
        os.environ.pop("THREADS_PASSWORD", None)
        creds = tc.load_credentials(config_path=p)
        assert creds == {"username": "fileuser", "password": "filepass"}


def test_load_credentials_empty_when_nothing():
    os.environ.pop("THREADS_USERNAME", None)
    os.environ.pop("THREADS_PASSWORD", None)
    creds = tc.load_credentials(config_path=Path("/nonexistent/credentials.json"))
    assert creds == {"username": None, "password": None}


def test_assemble_output_shape():
    cutoff = datetime(2026, 6, 17, 12, 0, tzinfo=timezone.utc)
    results = {
        "zuck": [
            {"id": "X", "url": "u", "author": "zuck", "datetime": "2026-06-18T10:00:00.000Z",
             "is_repost": False, "text": "hi", "metrics": {"like": 5}, "media": [], "truncated": False}
        ]
    }
    out = tc.assemble_output(results, within_hours=48, cutoff=cutoff, errors={"foo": "bar"})
    assert out["within_hours"] == 48
    assert out["cutoff"] == cutoff.isoformat()
    assert out["total_posts"] == 1
    assert out["accounts"]["zuck"]["post_count"] == 1
    assert out["accounts"]["zuck"]["posts"][0]["id"] == "X"
    assert out["errors"] == {"foo": "bar"}
    assert "timestamp" in out


def _run():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {fn.__name__}: {e}")
        except Exception as e:  # pragma: no cover
            failed += 1
            print(f"ERROR {fn.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    return failed


if __name__ == "__main__":
    sys.exit(1 if _run() else 0)
