"""
Tests for the cost panel's model-history and rate-card helpers.

WHY these exist: the panel's job is to make an unpriced model impossible to
miss. A retired model once served 1,518 turns and reported $0.00 on every cost
report for five months because nothing distinguished "free" from "no rate on
file". These tests pin the distinction at the render boundary, where a human
reads it.

This matters MORE since 2026-09-01, not less: the rate card was cut to the
GPT-5.6 line, so anything outside it is unpriced BY DESIGN and the flag is
the only thing standing between that and a page saying "$0".

The helpers are pure except for _model_history, which takes a fake db -- no
Prisma, no network, so this runs in the offline sandbox.
"""
from __future__ import annotations

import pytest

from src.api.admin.cost_view_router import (
    _aggregate,
    _day_of,
    _model_history,
    _rate_card,
)


class _FakeDb:
    """Minimal stand-in for the Prisma client's group_by/find_many surface."""

    def __init__(self, groups=None, rows=None, raises=False):
        self._groups = groups or []
        self._rows = rows or []
        self._raises = raises

    def is_connected(self):
        return True

    class _Table:
        def __init__(self, outer):
            self._outer = outer

        async def group_by(self, **_kwargs):
            if self._outer._raises:
                raise RuntimeError("engine down")
            return self._outer._groups

        async def find_many(self, **_kwargs):
            if self._outer._raises:
                raise RuntimeError("engine down")
            return self._outer._rows

    @property
    def modeltokenusage(self):
        return self._Table(self)


def _group(model, turns, inp, cached, out, first, last):
    return {
        "llmModelName": model,
        "_count": {"_all": turns},
        "_sum": {
            "promptTokens": inp,
            "cachedInputTokens": cached,
            "completionTokens": out,
        },
        "_min": {"createdAt": first},
        "_max": {"createdAt": last},
    }


# Real ModelTokenUsage shapes, with the ids updated to the 5.6-only world:
# a dated snapshot of a live model, a plain live model, and one retired id
# that no longer has a rate.
_REAL_HISTORY = [
    _group("gpt-5.6-terra-2026-08-21", 1518, 2_692_981, 0, 817_527,
           "2025-12-17T03:25:42.285Z", "2026-05-12T14:07:38.056Z"),
    _group("gpt-5.6-luna", 457, 4_741_401, 4_297_107, 112_503,
           "2026-07-18T07:05:01.015Z", "2026-07-31T15:52:18.729Z"),
    _group("gpt-5.5-retired", 16, 40_668, 0, 1_313,
           "2026-05-24T20:22:17.813Z", "2026-05-27T17:10:15.079Z"),
]


@pytest.mark.asyncio
async def test_history_prices_a_pinned_snapshot_instead_of_reporting_zero():
    hist = await _model_history(_FakeDb(groups=_REAL_HISTORY))
    snap = next(h for h in hist if h["model"] == "gpt-5.6-terra-2026-08-21")
    assert snap["priced"] is True
    assert 15.0 < snap["usd"] < 15.5, snap["usd"]  # a pin must not read $0


@pytest.mark.asyncio
async def test_history_sorted_by_turns_so_the_workhorse_is_first():
    hist = await _model_history(_FakeDb(groups=_REAL_HISTORY))
    assert [h["turns"] for h in hist] == [1518, 457, 16]


@pytest.mark.asyncio
async def test_history_reports_first_and_last_use_as_dates():
    hist = await _model_history(_FakeDb(groups=_REAL_HISTORY))
    top = hist[0]
    assert top["first_seen"] == "2025-12-17"
    assert top["last_seen"] == "2026-05-12"


@pytest.mark.asyncio
async def test_history_shows_which_base_rate_a_dated_snapshot_used():
    """Otherwise "why is this row $1.20" has no answer on the page."""
    hist = await _model_history(_FakeDb(groups=_REAL_HISTORY))
    snap = next(h for h in hist if h["model"] == "gpt-5.6-terra-2026-08-21")
    assert snap["priced_as"] == "gpt-5.6-terra"
    luna = next(h for h in hist if h["model"] == "gpt-5.6-luna")
    assert luna["priced_as"] is None  # no annotation when the id is already base


@pytest.mark.asyncio
async def test_history_flags_an_unpriced_model_rather_than_billing_it_at_zero():
    groups = [_group("gpt-9-imaginary", 40, 500_000, 0, 50_000,
                     "2026-07-01T00:00:00Z", "2026-07-02T00:00:00Z")]
    hist = await _model_history(_FakeDb(groups=groups))
    assert hist[0]["priced"] is False
    assert hist[0]["usd"] == 0.0  # $0 is fine on the wire...
    # ...as long as `priced` is what the template branches on. If a future
    # refactor drops the flag, the page silently claims a real $0 again.


@pytest.mark.asyncio
async def test_history_degrades_to_empty_on_db_failure_never_raises():
    """The panel must not 500 the admin board when the engine is down."""
    assert await _model_history(_FakeDb(raises=True)) == []


@pytest.mark.asyncio
async def test_windowed_rows_carry_the_priced_flag_too():
    """The by-day/model/site table shows money as well, so it needs the flag."""

    class _Row:
        def __init__(self, model):
            from datetime import datetime, timezone
            self.createdAt = datetime(2026, 7, 30, tzinfo=timezone.utc)
            self.llmModelName = model
            self.callSite = "v2_turn"
            self.promptTokens = 1000
            self.cachedInputTokens = 0
            self.completionTokens = 100

    d = await _aggregate(_FakeDb(rows=[_Row("gpt-5.6-luna"), _Row("nope-9")]), 7)
    flags = {r["model"]: r["priced"] for r in d["rows"]}
    assert flags == {"gpt-5.6-luna": True, "nope-9": False}


def test_rate_card_shows_only_models_we_actually_call():
    """Operator ruling 2026-08-21: the page lists what we spend on.

    It used to print all ~21 priced models with a used/never column, which
    buried the two rows this service runs on. Since 2026-09-01 the table
    itself is short (5.6 only), and the PAGE is shorter still: only what we
    actually call. Sol is priced but never called, so it stays off.
    """
    hist = [{"model": "gpt-5.6-luna"}, {"model": "gpt-5.6-terra-2026-08-21"}]
    names = {c["model"] for c in _rate_card(hist)}
    assert "gpt-5.6-luna" in names
    assert "gpt-5.6-terra" in names   # matched via the snapshot's base model
    assert "gpt-5.6-sol" not in names  # priced, never called -- not shown
    assert all(c["used"] or c["unlogged"] for c in _rate_card(hist))


def test_the_hidden_rate_rows_are_counted_not_silently_dropped():
    # Omitting rows is fine; omitting them invisibly is how a page starts
    # lying about what it covers.
    from scripts.cost_rollup import PRICE_PER_1M_TOKENS
    from src.api.admin.cost_view_router import _hidden_rate_rows
    hist = [{"model": "gpt-5.6-luna"}]
    assert _hidden_rate_rows(hist) > 0
    assert _hidden_rate_rows(hist) == len(PRICE_PER_1M_TOKENS) - len(_rate_card(hist))


def test_rate_card_is_alphabetical_so_the_page_is_scannable():
    names = [c["model"] for c in _rate_card([{"model": "gpt-5.6-terra"},
                                             {"model": "gpt-5.6-luna"}])]
    assert names == sorted(names)


@pytest.mark.parametrize(
    "value,expected",
    [
        ("2026-05-12T14:07:38.056Z", "2026-05-12"),  # group_by returns strings
        (None, "—"),
    ],
)
def test_day_of_handles_both_shapes_prisma_returns(value, expected):
    assert _day_of(value) == expected


def test_day_of_handles_a_real_datetime():
    from datetime import datetime, timezone
    assert _day_of(datetime(2026, 7, 31, 15, 52, tzinfo=timezone.utc)) == "2026-07-31"


def test_rate_card_does_not_claim_embeddings_were_never_used():
    """We call the embeddings API once per turn but log no usage row for it.

    "never" would be a flat lie on the page; the third state exists so the
    rate card can distinguish "we don't call this" from "we call this and
    don't record it".
    """
    # Still listed even though nothing logs it -- it is called every turn,
    # so leaving it off the short list would hide a real cost.
    card = {c["model"]: c for c in _rate_card([{"model": "gpt-5.6-luna"}])}
    emb = card["text-embedding-3-large"]
    assert emb["used"] is False      # genuinely absent from ModelTokenUsage
    assert emb["unlogged"] is True   # ...but we do call it, so don't say "never"
    # A model we neither call nor log is simply not on the page any more.
    assert "gpt-5.6-sol" not in card
