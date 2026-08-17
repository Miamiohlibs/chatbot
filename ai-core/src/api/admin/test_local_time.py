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


# --- the links the patron was shown -----------------------------------------


def test_cited_urls_are_deduped_but_keep_citation_order():
    """Order is [1], [2], [3] as the patron read them, so it carries meaning
    and must not be sorted away. But the same page is routinely cited twice
    in one answer -- the printing answer cites its own page as [1] and [4] --
    and storing it twice would make "how often do we send people here" wrong.
    """
    from src.memory.conversation_store import _dedupe_keep_order

    assert _dedupe_keep_order(["b", "a", "b", "c"]) == ["b", "a", "c"]
    assert _dedupe_keep_order([]) == []
    # Junk in the citations list must not become a stored "URL".
    assert _dedupe_keep_order([None, "", "  ", 7, "x"]) == ["x"]
    assert _dedupe_keep_order(["  http://a  "]) == ["http://a"]


def test_the_query_layer_exposes_cited_urls():
    """The admin console reads this; a missing column must degrade to an
    empty list rather than raise, like everything else in review_queries."""
    from src.api.admin.review_queries import _msg_dict

    class _M:
        id = "m1"
        type = "assistant"
        content = "see the guide [1]"
        citedUrls = ["https://example.org/a"]

    assert _msg_dict(_M())["cited_urls"] == ["https://example.org/a"]

    class _Old:  # a row written before the column existed
        id = "m0"
        type = "assistant"
        content = "old"

    assert _msg_dict(_Old())["cited_urls"] == []


# --- link-click plumbing ----------------------------------------------------


def test_linkclick_is_in_the_purge_child_tables_and_before_message():
    """Every FK into Conversation is ON DELETE RESTRICT, and that one list
    drives BOTH the archive dump and the delete. A child missing from it
    fails the next purge; worse, since the list also drives the archive, the
    rows would be deleted without ever being written to the archive.

    LinkClick points at Message as well, so it must come BEFORE Message or
    the Message delete hits a RESTRICT violation.
    """
    import re
    from pathlib import Path

    src = (Path(__file__).resolve().parents[3] / "scripts"
           / "archive_conversations.py").read_text(encoding="utf-8")
    block = src[src.index("CHILD_TABLES = ["):]
    block = block[: block.index("]")]
    names = re.findall(r'\("(\w+)",', block)
    assert "LinkClick" in names, "the next purge would fail"
    assert names.index("LinkClick") < names.index("Message")


def test_the_socket_handler_is_actually_registered():
    """Same wiring discipline as test_guards_are_wired: a handler defined but
    never bound to an event is invisible until someone notices no data."""
    from pathlib import Path

    src = (Path(__file__).resolve().parents[2] / "main.py").read_text(encoding="utf-8")
    assert "async def _v2_link_click" in src
    assert 'sio_v2.on("linkClick", _v2_link_click)' in src
