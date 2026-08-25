"""How much of the timeline the classifier reads before it decides.

THE BUG (measured on production 2026-08-25): the reading window was one
single span from the earliest asked-about message to the latest, read with
take=5000 and ordered ascending. Ask about conversations from the 5th and
the 25th and that span is twenty days, far more than 5000 messages, so the
cap kept the oldest rows and silently dropped the recent ones. 260 ids went
in; 39 came back with no verdict.

The direction of the loss is what makes it serious. No verdict means no
testing tag, and no testing tag reads as a member of the public -- so the
wider the span asked about, the more of our own scripted runs got counted
as patrons. Across all of history it inflated the non-testing count from 11
to 58.
"""

import datetime as dt
from types import SimpleNamespace as NS

import pytest

import src.api.admin.review_queries as RQ

DAY0 = dt.datetime(2026, 8, 5, 9, tzinfo=dt.timezone.utc)


def _msg(cid, i, when, type_="user", content="where are the study rooms"):
    return NS(id=f"{cid}-{i}", conversationId=cid, type=type_,
              content=content, timestamp=when, wasRefusal=False,
              isPositiveRated=None, confidence=None,
              reviewedAt=None, reviewedBy=None)


class _DB:
    """A fake that honours `take` and `order` -- without those the
    truncation this file is about cannot be reproduced at all."""

    def __init__(self, msgs):
        self._msgs = msgs
        self.windows = []
        self.message = NS(find_many=self._find)
        self.modeltokenusage = NS(find_many=self._none)
        self.conversation = NS(find_many=self._convs)
        self.conversationfeedback = NS(find_many=self._none)

    async def _none(self, **kw):
        return []

    async def _convs(self, where=None):
        ids = ((where or {}).get("id") or {}).get("in") or []
        return [NS(id=i, origin=None, sourceOverride=None,
                   sourceOverrideBy=None) for i in ids]

    async def _find(self, where=None, order=None, take=None, skip=None):
        w = where or {}
        cid = w.get("conversationId") or {}
        if isinstance(cid, dict) and "in" in cid:
            rows = [m for m in self._msgs if m.conversationId in cid["in"]]
        else:
            ts = w.get("timestamp") or {}
            lo, hi = ts.get("gte"), ts.get("lte")
            self.windows.append((lo, hi))
            rows = [m for m in self._msgs
                    if (lo is None or m.timestamp >= lo)
                    and (hi is None or m.timestamp <= hi)]
        rows.sort(key=lambda m: m.timestamp,
                  reverse=bool(order) and order.get("timestamp") == "desc")
        return rows[:take] if take else rows


def _spread_over_twenty_days():
    """Two conversations at opposite ends, filler in between.

    Shaped like the real thing: bursts minutes apart with hours of nothing
    between them.
    """
    msgs = [_msg("first", 0, DAY0), _msg("first", 1, DAY0 + dt.timedelta(seconds=30))]
    for d in range(1, 20):
        when = DAY0 + dt.timedelta(days=d)
        msgs += [_msg(f"filler{d}", j, when + dt.timedelta(seconds=60 * j))
                 for j in range(3)]
    last = DAY0 + dt.timedelta(days=20)
    msgs += [_msg("last", 0, last), _msg("last", 1, last + dt.timedelta(seconds=30))]
    return msgs


@pytest.mark.asyncio
async def test_a_wide_span_does_not_drop_the_recent_conversations(monkeypatch):
    """The regression, in miniature: cap smaller than the filler."""
    monkeypatch.setattr(RQ, "_WINDOW_TAKE", 10)
    db = _DB(_spread_over_twenty_days())
    out = await RQ.sources_for_conversations(db, ["first", "last"])
    assert "first" in out
    assert "last" in out, (
        "the conversation at the far end of the span lost its verdict -- "
        "which would have read as a member of the public")


@pytest.mark.asyncio
async def test_it_reads_one_window_per_cluster_not_one_giant_one(monkeypatch):
    monkeypatch.setattr(RQ, "_WINDOW_TAKE", 10)
    db = _DB(_spread_over_twenty_days())
    await RQ.sources_for_conversations(db, ["first", "last"])
    assert len(db.windows) >= 2, "still reading the whole span in one go"
    for lo, hi in db.windows:
        assert hi - lo < dt.timedelta(hours=2), (
            f"window {lo}..{hi} spans days; the cap will bite inside it")


@pytest.mark.asyncio
async def test_every_conversation_asked_about_gets_a_verdict(monkeypatch):
    """Whatever the windows miss, answer for it anyway.

    A caller that asks about a conversation and is handed nothing has no way
    to tell "we looked and could not attribute it" from "we never looked".
    """
    monkeypatch.setattr(RQ, "_WINDOW_TAKE", 1)
    db = _DB(_spread_over_twenty_days())
    asked = ["first", "last", "filler7"]
    out = await RQ.sources_for_conversations(db, asked)
    assert set(asked) <= set(out)


@pytest.mark.asyncio
async def test_a_conversation_with_no_messages_is_left_out_deliberately():
    """186 of the 852 beta conversations never had a word typed in them.

    They are page-opens, not questions, and must not arrive at the caller
    labelled anything -- least of all as a patron.
    """
    db = _DB([_msg("real", 0, DAY0)])
    out = await RQ.sources_for_conversations(db, ["real", "never-typed"])
    assert "real" in out
    assert "never-typed" not in out
