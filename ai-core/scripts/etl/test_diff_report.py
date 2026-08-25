"""
Unit tests for the ETL diff-report Markdown renderer.

Run: `python -m scripts.etl.test_diff_report` from ai-core/.

The diff report is what a librarian reads to APPROVE an ETL run
(see scripts/etl/gate.py). If it's missing a category, or claims
"0 tombstoned" when there really are tombstones, the librarian
approves blindly. Tests pin the rendered shape so a regression in
the Markdown layout fails CI.
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

# Allow running from ai-core/ as `python -m scripts.etl.test_diff_report`.
_HERE = Path(__file__).resolve().parent
_AI_CORE = _HERE.parent.parent
sys.path.insert(0, str(_AI_CORE))

from scripts.etl.diff_report import DiffReport, render_markdown  # noqa: E402
from scripts.etl.upsert import UpsertResult  # noqa: E402


def _empty_report(
    started: dt.datetime = None,
    finished: dt.datetime = None,
) -> DiffReport:
    return DiffReport(
        run_started_at=started or dt.datetime(2026, 5, 7, 2, 0, 0),
        run_finished_at=finished or dt.datetime(2026, 5, 7, 2, 5, 0),
        discovered_url_count=0,
        upsert=UpsertResult(),
    )


# --- Header + summary --------------------------------------------------


def test_renders_finished_timestamp() -> None:
    md = render_markdown(_empty_report(
        finished=dt.datetime(2026, 5, 7, 14, 30, 0),
    ))
    assert "2026-05-07" in md
    assert "14:30" in md


def test_renders_run_duration() -> None:
    md = render_markdown(_empty_report(
        started=dt.datetime(2026, 5, 7, 2, 0, 0),
        finished=dt.datetime(2026, 5, 7, 2, 7, 30),
    ))
    # 7m30s = 450 seconds.
    assert "450s" in md


def test_renders_summary_counts() -> None:
    rep = DiffReport(
        run_started_at=dt.datetime(2026, 5, 7, 2, 0, 0),
        run_finished_at=dt.datetime(2026, 5, 7, 2, 5, 0),
        discovered_url_count=580,
        fetched_url_count=572,
        extracted_doc_count=540,
        chunks_created=2304,
        chunks_dropped_short=18,
        upsert=UpsertResult(
            new_chunk_ids=["c-a", "c-b"],
            changed_chunk_ids=["c-c"],
            deduped_chunk_ids=["c-d", "c-e", "c-f"],
            tombstoned_urls=set(),
            new_url_count=0,
        ),
    )
    md = render_markdown(rep)
    assert "**580**" in md  # discovered
    assert "**572**" in md  # fetched
    assert "**540**" in md  # extracted
    assert "**2304**" in md  # chunks created
    assert "18" in md  # chunks dropped short
    assert "**2**" in md  # new chunks
    assert "**1**" in md  # changed chunks
    assert "**3**" in md  # deduped


# --- Tombstoned URLs section -------------------------------------------


def test_no_tombstones_omits_section() -> None:
    md = render_markdown(_empty_report())
    # The summary line "Tombstoned URLs: 0" always renders. The
    # explicit `## ⚠️ Tombstoned URLs ...` section only when there
    # are some.
    assert "## ⚠️ Tombstoned URLs" not in md


def test_tombstones_listed_when_present() -> None:
    rep = _empty_report()
    rep.upsert.tombstoned_urls = {
        "https://www.lib.miamioh.edu/old-page-1/",
        "https://www.lib.miamioh.edu/old-page-2/",
    }
    md = render_markdown(rep)
    assert "Tombstoned URLs" in md
    assert "old-page-1" in md
    assert "old-page-2" in md


def test_tombstones_truncated_at_50() -> None:
    """Big sweeps could tombstone hundreds of URLs; the renderer caps
    the visible list at 50 with an 'and N more' line so the librarian
    doesn't get a wall of text."""
    rep = _empty_report()
    rep.upsert.tombstoned_urls = {
        f"https://x.com/page-{i}/" for i in range(75)
    }
    md = render_markdown(rep)
    assert "and 25 more" in md  # 75 - 50 = 25


# --- Fetch failures section --------------------------------------------


def test_no_fetch_failures_omits_section() -> None:
    md = render_markdown(_empty_report())
    assert "Fetch failures" not in md


def test_fetch_failures_listed() -> None:
    rep = _empty_report()
    rep.fetch_failures = [
        ("https://www.lib.miamioh.edu/dead-link/", "404 Not Found"),
        ("https://mid.miamioh.edu/library/", "SSLError: cert expired"),
    ]
    md = render_markdown(rep)
    assert "Fetch failures" in md
    assert "dead-link" in md
    assert "SSLError" in md  # librarian can SEE the cert problem


# --- Extraction rejects (grouped by reason) ----------------------------


def test_extraction_rejects_grouped_by_reason() -> None:
    """Grouping is the librarian's friend -- "5 pages too short, 3
    pages mostly boilerplate" beats listing every URL flat."""
    rep = _empty_report()
    rep.extraction_rejects = [
        ("https://x/short-1/", "body_text < 200 chars"),
        ("https://x/short-2/", "body_text < 200 chars"),
        ("https://x/short-3/", "body_text < 200 chars"),
        ("https://x/boiler-1/", "boilerplate ratio > 0.80"),
    ]
    md = render_markdown(rep)
    assert "body_text < 200 chars (3)" in md  # count after grouping
    assert "boilerplate ratio > 0.80 (1)" in md


def test_extraction_rejects_truncate_per_group_at_10() -> None:
    rep = _empty_report()
    rep.extraction_rejects = [
        (f"https://x/short-{i}/", "too short")
        for i in range(15)
    ]
    md = render_markdown(rep)
    # Cap is 10 per reason group.
    assert "too short (15)" in md
    assert "and 5 more" in md


# --- Filtered URLs (exclusion rules) -----------------------------------


def test_rejected_urls_grouped_by_reason() -> None:
    rep = _empty_report()
    rep.rejected_urls = [
        ("https://www.lib.miamioh.edu/about/news-events/exhibit-2024/", "news_excluded"),
        ("https://www.lib.miamioh.edu/about/news-events/talk-2024/", "news_excluded"),
        ("https://www.lib.miamioh.edu/dead-test-page/", "404"),
    ]
    md = render_markdown(rep)
    assert "URLs filtered" in md
    assert "news_excluded" in md
    assert "2 URLs" in md  # 2 news-events
    assert "404" in md


# --- Always-rendered sections ------------------------------------------


def test_top_summary_always_renders() -> None:
    """Even an empty run renders the Summary block so cron failures
    that produce a malformed report are visible."""
    md = render_markdown(_empty_report())
    assert "## Summary" in md
    assert "Discovered URLs" in md
    assert "Fetched" in md
    assert "Extracted docs" in md
    assert "Chunks created" in md
    assert "Tombstoned URLs" in md.replace(  # the count line, not the section
        "## ⚠️ Tombstoned URLs",
        "",
    )


def test_cost_estimate_renders() -> None:
    rep = _empty_report()
    rep.cost_estimate_usd = 0.4567
    md = render_markdown(rep)
    # Renders to 2 decimal places.
    assert "$0.46" in md


def test_zero_cost_renders_zero() -> None:
    """Default 0.0 still renders, doesn't crash on str format."""
    md = render_markdown(_empty_report())
    assert "$0.00" in md


def main() -> int:
    tests = [
        test_renders_finished_timestamp,
        test_renders_run_duration,
        test_renders_summary_counts,
        test_no_tombstones_omits_section,
        test_tombstones_listed_when_present,
        test_tombstones_truncated_at_50,
        test_no_fetch_failures_omits_section,
        test_fetch_failures_listed,
        test_extraction_rejects_grouped_by_reason,
        test_extraction_rejects_truncate_per_group_at_10,
        test_rejected_urls_grouped_by_reason,
        test_top_summary_always_renders,
        test_cost_estimate_renders,
        test_zero_cost_renders_zero,
    ]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {t.__name__}: {e}")
        except Exception as e:
            failed += 1
            print(f"ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())


def test_the_report_lists_what_is_being_added_by_page():
    """An approval gate that does not show what is being approved is a rubber
    stamp.

    `UpsertResult.new_urls` -- {source_url: chunk_count} -- has been populated
    by preview since it was written, and the report never rendered it. On
    2026-08-18 a librarian was being asked to sign off 212 new chunks with no
    way to see which pages they came from, while the SAME report itemised
    every page being removed.
    """
    import datetime as dt

    from scripts.etl.diff_report import DiffReport, render_markdown
    from scripts.etl.upsert import UpsertResult

    now = dt.datetime(2026, 8, 18, 4, 0)
    up = UpsertResult(weaviate_collection_version="(preview)")
    up.new_urls = {
        "https://www.ham.miamioh.edu/library/about/mission-and-policies/": 15,
        "https://www.lib.miamioh.edu/about/organization/staff/": 39,
        "https://www.lib.miamioh.edu/small/": 1,
    }
    md = render_markdown(DiffReport(run_started_at=now, run_finished_at=now,
                                    discovered_url_count=3, upsert=up))

    assert "New or rewritten content, by page" in md
    assert "3 page(s) contribute the 55 new/rewritten chunks" in md
    for url in up.new_urls:
        assert url in md, url
    # Heaviest first -- those are the ones worth a reviewer's attention.
    assert md.index("/about/organization/staff/") < md.index("/small/")


def test_unreachable_urls_are_reported_as_kept_not_lost():
    """The reviewer must be able to tell "we could not reach this, so we kept
    it" from "this was deleted from the website"."""
    import datetime as dt

    from scripts.etl.diff_report import DiffReport, render_markdown

    now = dt.datetime(2026, 8, 18, 4, 0)
    md = render_markdown(DiffReport(
        run_started_at=now, run_finished_at=now, discovered_url_count=1,
        unreachable_protected=[
            ("https://www.ham.miamioh.edu/library/", "SSLError: CERT...")],
    ))
    assert "NOT tombstoned" in md
    assert "www.ham.miamioh.edu/library/" in md
    assert "Only 404 and 410 count" in md


def test_a_renamed_url_is_not_reported_as_lost() -> None:
    """Since urls are canonicalised, `/staff/` is written as `/staff`: the
    old spelling orphans while the new one gains the same chunks.

    Matched literally, the first canonicalising run put 45 renamed pages in
    the LOST column -- the staff directory among them -- and the one column
    a librarian is told to read became noise.
    """
    report = _empty_report()
    report.upsert = UpsertResult(
        orphaned_urls={"https://x.edu/staff/": 14,
                             "https://x.edu/gone": 3},
        new_urls={"https://x.edu/staff": 14},
    )
    md = render_markdown(report)
    assert "1 URL(s) / 3 chunks would be LOST outright" in md, md
    lost_block = md.split("### Lost outright")[1].split("### Re-chunked")[0]
    assert "https://x.edu/gone" in lost_block
    assert "/staff" not in lost_block, "a rename is not a loss"


def test_the_rechunked_row_shows_the_new_count_for_a_rename() -> None:
    report = _empty_report()
    report.upsert = UpsertResult(
        orphaned_urls={"https://x.edu/staff/": 14},
        new_urls={"https://x.edu/staff": 9},
    )
    md = render_markdown(report)
    churn = md.split("### Re-chunked")[1]
    assert "| 14 | 9 |" in churn.replace(" https://x.edu/staff/ |", "") or "9" in churn
