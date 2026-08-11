"""When librarian chat NEXT opens.

The widget's only two states were "available 9:00am - 6:00pm" and
"currently offline". Offline told a student nothing about how long to
wait, and the status message said "Chat service opens at 9:00am" whenever
today was a service day -- without checking that 9am had already gone.
Reproduced live at 22:22 on a Monday. On a Friday evening it points a
student at a librarian who is not back until Monday, 62 hours later.
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent.parent))

import pytest  # noqa: E402

from src.api import askus_hours as A  # noqa: E402

EST = ZoneInfo("America/New_York")


def _at(y, m, d, hh, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=EST)


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _week(days: dict):
    """days: {"2026-08-10": [("9:00am", "6:00pm")] or "closed"}"""
    dates = {}
    for iso, spec in days.items():
        if spec == "closed":
            dates[iso] = {"status": "closed", "hours": []}
        else:
            dates[iso] = {
                "status": "open",
                "hours": [{"from": f, "to": t} for f, t in spec],
            }
    return [{"name": "Ask Us Chat Service", "dates": dates}]


@pytest.fixture()
def libcal(monkeypatch):
    """Serve a canned week, and record nothing else touches the network."""
    calls = []

    def install(payload):
        class _Client:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, url, headers=None, params=None):
                calls.append(params)
                return _FakeResponse(payload)

        monkeypatch.setattr(A, "LIBCAL_ASKUS_ID", "1234")
        monkeypatch.setattr(A, "LIBCAL_HOUR_URL", "https://libcal.test/hours")
        monkeypatch.setattr(A.httpx, "AsyncClient", lambda **kw: _Client())

        async def _tok():
            return "token"

        monkeypatch.setattr(A, "_get_oauth_token", _tok)
        return calls

    return install


def _run(coro):
    import asyncio
    return asyncio.run(coro)


def test_after_closing_it_points_at_tomorrow_not_this_morning(libcal):
    """The live repro: 22:22 Monday, closed since 6pm, and the endpoint
    said "opens at 9:00am"."""
    libcal(_week({
        "2026-08-10": [("9:00am", "6:00pm")],
        "2026-08-11": [("9:00am", "6:00pm")],
    }))
    nxt = _run(A.find_next_open(now=_at(2026, 8, 10, 22, 22)))
    assert nxt["date"] == "2026-08-11"
    assert nxt["when"] == "tomorrow"
    assert nxt["time"] == "9:00am"


def test_friday_evening_points_at_monday(libcal):
    """The operator's question. 2026-08-14 is a Friday; the weekend is
    closed, so the true wait is until Monday."""
    libcal(_week({
        "2026-08-14": [("9:00am", "6:00pm")],
        "2026-08-15": "closed",
        "2026-08-16": "closed",
        "2026-08-17": [("9:00am", "6:00pm")],
    }))
    nxt = _run(A.find_next_open(now=_at(2026, 8, 14, 19, 0)))
    assert nxt["date"] == "2026-08-17"
    assert nxt["when"] == "Monday"
    assert nxt["days_away"] == 3


def test_before_opening_it_still_says_today(libcal):
    libcal(_week({"2026-08-10": [("9:00am", "6:00pm")]}))
    nxt = _run(A.find_next_open(now=_at(2026, 8, 10, 7, 30)))
    assert nxt["date"] == "2026-08-10"
    assert nxt["when"] == "later today"


def test_a_second_period_later_the_same_day_is_found(libcal):
    """Some days LibCal publishes a split schedule; the gap is not the end
    of the day."""
    libcal(_week({
        "2026-08-10": [("9:00am", "12:00pm"), ("2:00pm", "6:00pm")],
    }))
    nxt = _run(A.find_next_open(now=_at(2026, 8, 10, 12, 30)))
    assert nxt["time"] == "2:00pm"
    assert nxt["when"] == "later today"


def test_closed_days_are_skipped(libcal):
    libcal(_week({
        "2026-08-10": "closed",
        "2026-08-11": "closed",
        "2026-08-12": [("10:00am", "4:00pm")],
    }))
    nxt = _run(A.find_next_open(now=_at(2026, 8, 10, 9, 0)))
    assert nxt["date"] == "2026-08-12"
    assert nxt["time"] == "10:00am"


def test_a_long_break_returns_nothing_rather_than_a_made_up_time(libcal):
    """Over winter break there IS no next opening within the window. The
    caller says so; it must not name a day."""
    libcal(_week({f"2026-12-{d:02d}": "closed" for d in range(20, 32)}))
    assert _run(A.find_next_open(now=_at(2026, 12, 20, 9, 0))) is None


def test_one_request_covers_the_whole_range(libcal):
    """/askus-hours/week makes seven sequential calls. The status the
    widget polls asks once."""
    calls = libcal(_week({"2026-08-11": [("9:00am", "6:00pm")]}))
    _run(A.find_next_open(now=_at(2026, 8, 10, 22, 0)))
    assert len(calls) == 1
    assert calls[0]["from"] == "2026-08-10"
    assert calls[0]["to"] == "2026-08-17"


def test_a_libcal_outage_is_not_an_exception(libcal):
    """The widget polls this. A failure means "we do not know", not a 500."""
    def _boom(**kw):
        raise RuntimeError("libcal down")

    import types
    A_httpx = A.httpx
    try:
        A.httpx = types.SimpleNamespace(AsyncClient=_boom)
        assert _run(A.find_next_open(now=_at(2026, 8, 10, 22, 0))) is None
    finally:
        A.httpx = A_httpx


def test_time_parsing_lands_on_the_named_date_not_today():
    from datetime import date

    got = A._parse_time_on(date(2026, 9, 7), "9:00am")
    assert got.date() == date(2026, 9, 7)
    assert (got.hour, got.minute) == (9, 0)
    assert A._parse_time_on(date(2026, 9, 7), "") is None
    assert A._parse_time_on(date(2026, 9, 7), "not a time") is None
