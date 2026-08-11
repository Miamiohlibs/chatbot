"""Named-holiday resolution for the hours window.

The operator ruling is that any specific date inside ~1 month is answered
live from LibCal. That only holds if a holiday NAME becomes the right
concrete date -- otherwise the question falls through to whatever week
happened to be fetched, which is how "when does Art library open labor
day monday" came back with THIS Monday's hours (thumbs-down 2026-08-10).
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent.parent))

import pytest  # noqa: E402

from src.scope.date_window import (  # noqa: E402
    WINDOW_DAYS,
    _holiday_name_matches,
    resolve_target_date,
    within_window,
)

pytest.importorskip("holidays")

AUG_10_2026 = date(2026, 8, 10)   # a Monday


def test_labor_day_resolves_even_when_a_weekday_is_also_named():
    """The reported case. "monday" alone resolves to the nearest Monday,
    which on 2026-08-10 was that very day; the holiday has to win."""
    assert resolve_target_date(
        "when does Art library open labor day monday", AUG_10_2026
    ) == date(2026, 9, 7)


def test_labor_day_is_inside_the_live_window_from_early_august():
    """28 days out, so the 31-day ruling covers it -- the answer should be
    the real hours, not a pointer to the hours page."""
    d = resolve_target_date("labor day hours", AUG_10_2026)
    assert within_window(d, AUG_10_2026)
    assert (d - AUG_10_2026).days <= WINDOW_DAYS


def test_july_fourth_is_not_juneteenth():
    """"Independence Day" is a substring of "Juneteenth National
    Independence Day", so a substring match returned the next Juneteenth
    -- 2027-06-18 for a question about the 4th of July."""
    for phrasing in ("july 4", "fourth of july", "4th of july",
                     "independence day"):
        got = resolve_target_date(f"library hours on {phrasing}", AUG_10_2026)
        assert got == date(2027, 7, 4), f"{phrasing} -> {got}"


def test_every_holiday_keyword_resolves_to_a_real_date():
    """A keyword in the table that no longer matches any holiday name
    would fail silently -- the resolver just returns None and the question
    is answered from the wrong week."""
    from src.scope.date_window import _HOLIDAYS

    for kw in _HOLIDAYS:
        got = resolve_target_date(f"are you open on {kw}", AUG_10_2026)
        assert got is not None, kw
        assert got >= AUG_10_2026, f"{kw} resolved into the past: {got}"


def test_prefix_matching_separates_the_two_independence_days():
    assert _holiday_name_matches("Independence Day", "Independence Day")
    assert _holiday_name_matches("Independence Day (observed)",
                                 "Independence Day")
    assert not _holiday_name_matches(
        "Juneteenth National Independence Day", "Independence Day")
    # the other fragments are genuine prefixes of their real names
    assert _holiday_name_matches("New Year's Day", "New Year")
    assert _holiday_name_matches("Washington's Birthday", "Washington")
    assert _holiday_name_matches("Martin Luther King Jr. Day",
                                 "Martin Luther King")
    assert _holiday_name_matches("Christmas Day", "Christmas")


def test_a_far_off_holiday_is_resolved_but_falls_outside_the_window():
    """Thanksgiving in August is 3+ months out: the date is known, and the
    caller uses within_window to send it to the hours page instead."""
    d = resolve_target_date("thanksgiving hours", AUG_10_2026)
    assert d == date(2026, 11, 26)
    assert not within_window(d, AUG_10_2026)


def test_a_bare_weekday_is_not_a_specific_date():
    """Left to the weekday arithmetic in the orchestrator; this module
    only claims dates it can pin down."""
    assert resolve_target_date("hours on monday", AUG_10_2026) is None
