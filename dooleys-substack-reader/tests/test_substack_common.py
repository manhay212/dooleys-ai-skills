"""Unit tests for the pure logic in substack_common.

These cover the parsing / window / profile-resolution / html-conversion logic that does
NOT need the network, so they run fast and offline:

    python3 tests/test_substack_common.py      # built-in runner (no pytest needed)
    python3 -m pytest tests/                    # also works if pytest is installed
"""
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import substack_common as sc


# --------------------------------------------------------------------------- #
# normalize_account_entry — handle vs. publication subdomain
# --------------------------------------------------------------------------- #
def test_normalize_bare_handle():
    assert sc.normalize_account_entry("cryptohayes") == {"kind": "handle", "handle": "cryptohayes"}


def test_normalize_at_handle_and_whitespace():
    assert sc.normalize_account_entry("  @CryptoHayes ") == {"kind": "handle", "handle": "cryptohayes"}


def test_normalize_profile_url():
    assert sc.normalize_account_entry("https://substack.com/@marcusjin") == {
        "kind": "handle", "handle": "marcusjin"}


def test_normalize_publication_subdomain_url():
    assert sc.normalize_account_entry("https://capitalcycle.substack.com") == {
        "kind": "publication", "subdomain": "capitalcycle"}


def test_normalize_publication_bare_subdomain():
    assert sc.normalize_account_entry("capitalcycle.substack.com") == {
        "kind": "publication", "subdomain": "capitalcycle"}


def test_normalize_publication_subdomain_with_path():
    assert sc.normalize_account_entry("https://cryptohayes.substack.com/archive") == {
        "kind": "publication", "subdomain": "cryptohayes"}


# --------------------------------------------------------------------------- #
# publications_from_profile — primary first, dedup, keep all
# --------------------------------------------------------------------------- #
def _profile(primary, others):
    return {
        "name": "Marcus Jin", "handle": "marcusjin",
        "primaryPublication": primary,
        "publicationUsers": [{"publication": p} for p in others],
    }


def test_publications_single():
    prof = _profile({"id": 1, "subdomain": "cryptohayes", "name": "Crypto Trader Digest"},
                    [{"id": 1, "subdomain": "cryptohayes", "name": "Crypto Trader Digest"}])
    pubs = sc.publications_from_profile(prof)
    assert pubs == [{"id": 1, "subdomain": "cryptohayes", "name": "Crypto Trader Digest"}]


def test_publications_multiple_primary_first_deduped():
    prof = _profile(
        {"id": 10, "subdomain": "capitalcycle", "name": "資本週期"},
        [{"id": 10, "subdomain": "capitalcycle", "name": "資本週期"},
         {"id": 20, "subdomain": "cryptocyclesignal", "name": "加密市場週期訊號"}],
    )
    pubs = sc.publications_from_profile(prof)
    assert [p["subdomain"] for p in pubs] == ["capitalcycle", "cryptocyclesignal"]


def test_publications_skips_entries_without_subdomain():
    prof = _profile({"id": 1, "subdomain": "cryptohayes", "name": "A"},
                    [{"id": 2, "name": "no subdomain here"}])
    pubs = sc.publications_from_profile(prof)
    assert [p["subdomain"] for p in pubs] == ["cryptohayes"]


def test_publications_empty_profile():
    assert sc.publications_from_profile({"name": "x"}) == []


# --------------------------------------------------------------------------- #
# parse_post_url
# --------------------------------------------------------------------------- #
def test_parse_post_url_standard():
    assert sc.parse_post_url("https://cryptohayes.substack.com/p/reality-test") == {
        "subdomain": "cryptohayes", "slug": "reality-test",
        "url": "https://cryptohayes.substack.com/p/reality-test"}


def test_parse_post_url_with_query_and_trailing():
    got = sc.parse_post_url("https://capitalcycle.substack.com/p/some-slug?utm=1")
    assert got["subdomain"] == "capitalcycle"
    assert got["slug"] == "some-slug"


def test_parse_post_url_rejects_non_post():
    assert sc.parse_post_url("https://cryptohayes.substack.com/archive") is None
    assert sc.parse_post_url("https://substack.com/@cryptohayes") is None
    assert sc.parse_post_url("not a url") is None


# --------------------------------------------------------------------------- #
# time window
# --------------------------------------------------------------------------- #
def test_compute_cutoff():
    now = datetime(2026, 6, 20, 12, 0, tzinfo=timezone.utc)
    assert sc.compute_cutoff(now, 48) == datetime(2026, 6, 18, 12, 0, tzinfo=timezone.utc)


def test_parse_post_date_z_suffix():
    dt = sc.parse_post_date("2026-06-17T13:00:46.272Z")
    assert dt == datetime(2026, 6, 17, 13, 0, 46, 272000, tzinfo=timezone.utc)


def test_filter_posts_by_window_keeps_recent_only():
    cutoff = datetime(2026, 6, 18, 0, 0, tzinfo=timezone.utc)
    posts = [
        {"slug": "new", "post_date": "2026-06-19T10:00:00Z"},
        {"slug": "edge", "post_date": "2026-06-18T00:00:00Z"},   # exactly at cutoff -> kept
        {"slug": "old", "post_date": "2026-06-10T10:00:00Z"},
    ]
    kept = sc.filter_posts_by_window(posts, cutoff)
    assert [p["slug"] for p in kept] == ["new", "edge"]


def test_filter_posts_skips_unparseable_dates():
    cutoff = datetime(2026, 6, 18, 0, 0, tzinfo=timezone.utc)
    posts = [{"slug": "bad", "post_date": None}, {"slug": "ok", "post_date": "2026-06-19T00:00:00Z"}]
    assert [p["slug"] for p in sc.filter_posts_by_window(posts, cutoff)] == ["ok"]


# --------------------------------------------------------------------------- #
# paywall / truncation detection + record building
# --------------------------------------------------------------------------- #
def test_free_post_not_paywalled():
    post = {"id": 1, "title": "T", "audience": "everyone", "should_show_paywall": None,
            "body_html": "<p>Hello world here</p>", "post_date": "2026-06-19T00:00:00Z",
            "canonical_url": "https://x.substack.com/p/t", "slug": "t"}
    rec = sc.build_post_record(post, "x")
    assert rec["is_paywalled"] is False
    assert rec["truncated"] is False
    assert rec["title"] == "T"
    assert rec["publication"] == "x"
    assert "Hello world here" in rec["text"]
    assert rec["word_count"] >= 3


def test_paid_post_flagged_paywalled_and_truncated():
    post = {"id": 2, "title": "Paid", "audience": "only_paid", "should_show_paywall": True,
            "body_html": "<p>teaser</p>", "post_date": "2026-06-19T00:00:00Z",
            "canonical_url": "https://x.substack.com/p/paid", "slug": "paid"}
    rec = sc.build_post_record(post, "x")
    assert rec["is_paywalled"] is True
    assert rec["truncated"] is True


def test_record_url_prefers_canonical():
    post = {"id": 3, "title": "C", "canonical_url": "https://x.substack.com/p/canon",
            "slug": "canon", "body_html": "<p>hi</p>", "post_date": "2026-06-19T00:00:00Z"}
    assert sc.build_post_record(post, "x")["url"] == "https://x.substack.com/p/canon"


# --------------------------------------------------------------------------- #
# html_to_markdown + count_words
# --------------------------------------------------------------------------- #
def test_html_to_markdown_keeps_text_and_links():
    md = sc.html_to_markdown('<h2>Title</h2><p>Some <a href="https://e.com">link</a> here.</p>')
    assert "Title" in md
    assert "link" in md
    assert "https://e.com" in md


def test_html_to_markdown_handles_empty():
    assert sc.html_to_markdown("") == ""
    assert sc.html_to_markdown(None) == ""


def test_html_to_markdown_strips_empty_image_links():
    # Substack wraps hero/inline images in links; with images ignored these become empty
    # `[](cdn_url)` artifacts that add noise. They should be removed, real text kept.
    html = ('<a href="https://substackcdn.com/image/fetch/x"><img src="y"></a>'
            '<p>The real first paragraph.</p>')
    md = sc.html_to_markdown(html)
    assert "The real first paragraph." in md
    assert "[](" not in md
    assert "substackcdn" not in md


def test_html_to_markdown_collapses_excess_blank_lines():
    md = sc.html_to_markdown("<p>a</p><p></p><p></p><p>b</p>")
    assert "\n\n\n" not in md


def test_count_words():
    assert sc.count_words("one two three") == 3
    assert sc.count_words("") == 0
    assert sc.count_words("  spaced   out  ") == 2


# --------------------------------------------------------------------------- #
# config parsing
# --------------------------------------------------------------------------- #
def test_accounts_from_config_list():
    assert sc.accounts_from_config({"accounts": ["cryptohayes", "@marcusjin"]}) == [
        "cryptohayes", "@marcusjin"]


def test_accounts_from_config_missing_key():
    assert sc.accounts_from_config({}) == []


# --------------------------------------------------------------------------- #
# minimal self-contained runner (no pytest dependency required)
# --------------------------------------------------------------------------- #
def _run():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"ok   {fn.__name__}")
        except Exception as e:
            failed += 1
            print(f"FAIL {fn.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    return failed


if __name__ == "__main__":
    sys.exit(1 if _run() else 0)
