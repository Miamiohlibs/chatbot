"""Sweeping our own testing out of the flagged queue.

A flagged turn means "a patron may have had a bad experience here". 286 of
the 300 sitting in the queue came from our own scripted runs, which say
nothing of the kind -- and they buried the fourteen that might be real.

These tests are about the two ways a bulk close goes wrong: closing
something real, and being unable to undo it.
"""

import datetime as dt
from types import SimpleNamespace as NS

import pytest

from src.api.admin.review_queries import TESTING_TAGS, close_testing_rows

NOW = dt.datetime(2026, 8, 21, 12, tzinfo=dt.timezone.utc)


def _m(cid, i=0, type_="user", content="q", secs=0):
    return NS(id=f"{cid}-{type_}-{i}", conversationId=cid, type=type_,
              content=content, timestamp=NOW + dt.timedelta(seconds=secs),
              wasRefusal=(type_ == "assistant"), isPositiveRated=None,
              confidence="low", reviewedAt=None, reviewedBy=None)


class _DB:
    def __init__(self, flagged, msgs, dev=(), origins=None):
        self.updates = []
        self._flagged = flagged
        self._msgs = msgs
        self._dev = set(dev)
        self._origins = origins or {}
        self.message = NS(find_many=self._find, update=self._update)
        self.modeltokenusage = NS(find_many=self._usage)
        self.conversation = NS(find_many=self._convs)

    async def _find(self, where=None, order=None, take=None, skip=None):
        w = where or {}
        cid = (w.get("conversationId") or {})
        if isinstance(cid, dict) and "in" in cid:
            return [m for m in self._msgs if m.conversationId in cid["in"]]
        ts = w.get("timestamp")
        if isinstance(ts, dict):
            # The classifier widens to a time window so a scripted run is
            # visible even when only one of its conversations is flagged.
            lo, hi = ts.get("gte"), ts.get("lte")
            return [m for m in self._msgs
                    if (lo is None or m.timestamp >= lo)
                    and (hi is None or m.timestamp <= hi)]
        return self._flagged

    async def _update(self, where=None, data=None):
        self.updates.append((where["id"], dict(data or {})))
        return None

    async def _usage(self, where=None, **_):
        return [NS(conversationId=c, callSite="v2_turn_dev") for c in self._dev]

    async def _convs(self, where=None, **_):
        return [NS(id=c, origin=o) for c, o in self._origins.items()]


def _burst_msgs(n, prefix="b"):
    """n one-question conversations opened seconds apart -- a script."""
    return [_m(f"{prefix}{i}", i, "user", f"question {i}", secs=20 * i)
            for i in range(n)]


def test_a_scripted_run_is_closed():
    msgs = _burst_msgs(6)
    flagged = [_m("b0", 0, "assistant", "refused")]
    db = _DB(flagged, msgs, dev=["b2"])
    import asyncio
    res = asyncio.run(close_testing_rows(db, dry_run=False))
    assert res["closed"] == 1
    assert db.updates and db.updates[0][1]["reviewedAt"] is not None


def test_a_conversation_we_cannot_attribute_is_kept():
    # The cost of leaving one is that somebody reads it. The cost of closing
    # one wrongly is that nobody ever does.
    msgs = [_m("lonely", 0, "user", "when do you close")]
    flagged = [_m("lonely", 0, "assistant", "refused")]
    db = _DB(flagged, msgs)
    import asyncio
    res = asyncio.run(close_testing_rows(db, dry_run=False))
    assert res["closed"] == 0 and res["kept"] == 1
    assert db.updates == []


def test_a_dry_run_writes_nothing():
    msgs = _burst_msgs(6)
    db = _DB([_m("b0", 0, "assistant", "refused")], msgs, dev=["b1"])
    import asyncio
    res = asyncio.run(close_testing_rows(db, dry_run=True))
    assert res["closed"] == 1
    assert db.updates == [], "a preview must not touch the database"
    assert res["dry_run"] is True


def test_the_preview_and_the_write_agree():
    # The operator decides from the preview. If the write closes a different
    # set, the number they agreed to was not the number that happened.
    msgs = _burst_msgs(6)
    flagged = [_m(f"b{i}", i, "assistant", "refused") for i in range(6)]
    import asyncio
    a = asyncio.run(close_testing_rows(_DB(flagged, msgs, dev=["b1"]),
                                       dry_run=True))
    b = asyncio.run(close_testing_rows(_DB(flagged, msgs, dev=["b1"]),
                                       dry_run=False))
    assert a["closed"] == b["closed"]
    assert a["by_tag"] == b["by_tag"]


def test_the_staff_link_counts_as_testing():
    msgs = [_m("s1", 0, "user", "hello")]
    db = _DB([_m("s1", 0, "assistant", "refused")], msgs,
             origins={"s1": "staff"})
    import asyncio
    assert asyncio.run(close_testing_rows(db, dry_run=True))["closed"] == 1


def test_closing_is_reversible_by_construction():
    # Nothing is deleted: the row is stamped reviewed and still readable on
    # the reviewed tab.
    msgs = _burst_msgs(6)
    db = _DB([_m("b0", 0, "assistant", "refused")], msgs, dev=["b0"])
    import asyncio
    asyncio.run(close_testing_rows(db, dry_run=False))
    _id, data = db.updates[0]
    assert set(data) == {"reviewedAt", "reviewedBy"}, \
        "a sweep must only stamp the row, never change its content"


def test_one_bad_row_does_not_stop_the_others():
    class _Flaky(_DB):
        async def _update(self, where=None, data=None):
            if where["id"].startswith("b1"):
                raise RuntimeError("row is locked")
            return await super()._update(where=where, data=data)

    msgs = _burst_msgs(6)
    flagged = [_m(f"b{i}", i, "assistant", "refused") for i in range(6)]
    db = _Flaky(flagged, msgs, dev=["b0"])
    import asyncio
    res = asyncio.run(close_testing_rows(db, dry_run=False))
    assert res["closed"] == 6
    assert len(db.updates) == 5, "the other five should still be stamped"


def test_a_database_failure_closes_nothing_rather_than_guessing():
    class _Down:
        message = NS(find_many=lambda **_: (_ for _ in ()).throw(
            RuntimeError("down")))
    import asyncio
    res = asyncio.run(close_testing_rows(_Down(), dry_run=False))
    assert res == {"closed": 0, "kept": 0, "by_tag": {}, "dry_run": False}


def test_only_testing_tags_are_swept():
    # `local` stays alongside `bot`: it is what "bot" was called before
    # 2026-08-27 and twelve conversations still carry it. Dropping it would
    # quietly reclassify twelve known scripts as patron traffic, which is
    # the direction that inflates every "real patron" number we report.
    assert TESTING_TAGS == {"bot", "local", "staff", "maybe-staff"}
    assert "unlabelled" not in TESTING_TAGS
