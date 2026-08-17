"""Admin timestamps are shown in the libraries' timezone, not the box's.

The operator, looking at a real conversation on 2026-08-15, asked why the
admin still showed UTC:

    created: 2026-08-15 22:35:04.964000+00:00

That is 6:35pm Eastern. A librarian reviewing a conversation should not have
to subtract four hours -- and cannot tell whether a given row is off by four
or five without knowing whether that date fell in DST.
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from src.api.admin.review_queries import local_dt, local_ts  # noqa: E402


def test_the_operators_actual_row_reads_as_eastern():
    stamp = dt.datetime(2026, 8, 15, 22, 35, 4, 964000, tzinfo=dt.timezone.utc)
    assert local_ts(stamp) == "2026-08-15 18:35 EDT"


def test_dst_is_handled_in_both_directions():
    """Hard-coding -4 or -5 would be wrong for half the year."""
    summer = dt.datetime(2026, 8, 15, 22, 35, tzinfo=dt.timezone.utc)
    winter = dt.datetime(2026, 1, 15, 22, 35, tzinfo=dt.timezone.utc)
    assert local_ts(summer).endswith("EDT")
    assert local_ts(winter).endswith("EST")
    assert "18:35" in local_ts(summer)   # UTC-4
    assert "17:35" in local_ts(winter)   # UTC-5


def test_naive_values_are_read_as_utc():
    """Postgres stores UTC and every writer here uses it."""
    assert local_ts(dt.datetime(2026, 8, 15, 22, 35)) == "2026-08-15 18:35 EDT"


def test_it_never_raises_into_a_page():
    """Everything in review_queries degrades rather than 500s."""
    assert local_ts(None) == ""
    assert local_ts("") == ""
    assert local_ts("already a string") == "already a string"
    assert local_dt(None) is None
    assert local_dt("nonsense") is None


def test_the_evening_date_bucket_moves_to_the_right_day():
    """Why local_dt exists. The cost dashboard buckets by .date(), and on a
    UTC clock an 8pm Eastern conversation falls on the FOLLOWING day --
    evening is peak library use, so every night's spend landed on tomorrow.
    """
    evening = dt.datetime(2026, 8, 16, 0, 30, tzinfo=dt.timezone.utc)  # 8:30pm EDT 08-15
    assert evening.date().isoformat() == "2026-08-16", "the bug being fixed"
    assert local_dt(evening).date().isoformat() == "2026-08-15"
