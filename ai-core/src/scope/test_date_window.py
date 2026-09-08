"""
Offline tests for the hours 1-month date-window rule.

Run: `python -m src.scope.test_date_window` from ai-core/.

Deterministic via an injected `today` -- no clock dependence, no API.
Asserts the hr_thanksgiving operator ruling end-to-end through the v2
gate `_is_long_period_hours`.
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_AI_CORE = _HERE.parent.parent
sys.path.insert(0, str(_AI_CORE))

from src.scope.date_window import (
    WINDOW_DAYS,
    resolve_target_date,
    within_window,
)
from src.graph.new_orchestrator import _is_long_period_hours

_MAY19 = date(2026, 5, 19)


def test_resolve_holiday_far() -> None:
    d = resolve_target_date("are you open Thanksgiving day?", today=_MAY19)
    assert d is not None and d.year == 2026 and d.month == 11
    assert (d - _MAY19).days > WINDOW_DAYS  # ~6 months out


def test_resolve_relative_and_explicit() -> None:
    assert resolve_target_date("hours tomorrow", today=_MAY19) == date(2026, 5, 20)
    d = resolve_target_date("library hours on May 25", today=_MAY19)
    assert d == date(2026, 5, 25)
    dec = resolve_target_date("open on December 25?", today=_MAY19)
    assert dec == date(2026, 12, 25)


def test_resolve_none_for_generic_or_openended() -> None:
    assert resolve_target_date("what are the summer hours", today=_MAY19) is None
    assert resolve_target_date("what are the library hours", today=_MAY19) is None
    assert resolve_target_date("", today=_MAY19) is None


def test_within_window() -> None:
    assert within_window(_MAY19 + timedelta(days=10), today=_MAY19) is True
    assert within_window(_MAY19 + timedelta(days=WINDOW_DAYS), today=_MAY19) is True
    assert within_window(_MAY19 + timedelta(days=WINDOW_DAYS + 1), today=_MAY19) is False
    assert within_window(_MAY19 - timedelta(days=1), today=_MAY19) is False  # past


def test_gate_short_term_is_live() -> None:
    assert _is_long_period_hours("is the library open tonight?", today=_MAY19) is False
    assert _is_long_period_hours("what time do you close today", today=_MAY19) is False


def test_gate_thanksgiving_far_is_long_period() -> None:
    # hr_thanksgiving: 6 months out -> point-to-page + explain.
    assert _is_long_period_hours("are you open Thanksgiving day?", today=_MAY19) is True


def test_gate_thanksgiving_near_is_live() -> None:
    # Same question, but asked ~2 weeks before -> answerable live.
    assert _is_long_period_hours(
        "are you open Thanksgiving day?", today=date(2026, 11, 12)
    ) is False


def test_gate_near_specific_date_is_live() -> None:
    assert _is_long_period_hours("hours next Tuesday?", today=_MAY19) is False
    assert _is_long_period_hours("library hours on May 25", today=_MAY19) is False


def test_gate_far_specific_date_is_long_period() -> None:
    assert _is_long_period_hours("hours on December 25?", today=_MAY19) is True


def test_gate_openended_phrasing_is_long_period() -> None:
    assert _is_long_period_hours("what are the summer hours", today=_MAY19) is True
    assert _is_long_period_hours("hours during winter break?", today=_MAY19) is True


def test_gate_generic_no_date_not_long_period() -> None:
    # No date, no open-ended marker -> normal path (live), unchanged.
    assert _is_long_period_hours("what are the library hours", today=_MAY19) is False


def main() -> int:
    tests = [
        test_resolve_holiday_far,
        test_resolve_relative_and_explicit,
        test_resolve_none_for_generic_or_openended,
        test_within_window,
        test_gate_short_term_is_live,
        test_gate_thanksgiving_far_is_long_period,
        test_gate_thanksgiving_near_is_live,
        test_gate_near_specific_date_is_live,
        test_gate_far_specific_date_is_long_period,
        test_gate_openended_phrasing_is_long_period,
        test_gate_generic_no_date_not_long_period,
    ]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())


# --- "today" is not up for debate ----------------------------------------
#
# A student asked, on Sunday 6 September 2026: "Is there any facility on
# Miami's campus that is open TODAY on Sunday, September 6 Labor Day
# weekend to study?" Every Miami library was shut that day. The bot
# answered "King Library is open on Monday (2026-09-07) from 1pm to 1am" --
# true, for a day nobody asked about, with nothing marking the difference.
#
# "Labor Day" matched the holiday branch, which ran first and took the
# whole sentence with it.

_SUN = date(2026, 9, 6)          # Sunday of Labor Day weekend
_LABOR_DAY = date(2026, 9, 7)    # the Monday itself


def test_today_wins_over_every_other_date_word():
    said = ("Is there any facility on Miami's campus that is open today on "
            "Sunday, September 6 Labor Day weekend to study?")
    assert resolve_target_date(said, today=_SUN) == _SUN
    assert resolve_target_date("open today", today=_SUN) == _SUN
    assert resolve_target_date("are you open tonight", today=_SUN) == _SUN


def test_a_holiday_weekend_is_not_the_holiday():
    """"Labor Day weekend" names the stretch, not the Monday. Same for an
    eve: Christmas Eve is not Christmas."""
    assert resolve_target_date("open Labor Day weekend", today=_SUN) is None
    assert resolve_target_date("open Christmas Eve", today=_SUN) is None
    # The holiday itself still resolves -- this must not have broken it.
    assert resolve_target_date("open on Labor Day", today=_SUN) == _LABOR_DAY
    assert resolve_target_date("open on Christmas", today=_SUN) == date(2026, 12, 25)


def test_todays_own_date_does_not_jump_a_year():
    """PREFER_DATES_FROM="future" read "September 6" asked ON 6 September
    as 2027 -- a date LibCal has no rows for."""
    assert resolve_target_date("open September 6", today=_SUN) == _SUN
    # A date genuinely still to come is left alone.
    assert resolve_target_date("open December 25", today=_SUN) == date(2026, 12, 25)


# --- search_dates hands back fragments that are not dates ----------------
#
# It returns everything it can read as one. "hours for December 25" comes
# back [('hours', today), ('December 25', Dec 25)] -- "hours" read as a
# unit -- and "what time do you close December 25" leads with ('do', ...).
# Taking the first match answered about today, or about a day derived from
# the word "do", while the real date sat second in the list.
#
# Checked against all 736 distinct questions in the message table: four
# resolutions changed and every one of them was previously wrong.


def test_a_unit_word_does_not_win_over_the_real_date():
    assert resolve_target_date("hours for December 25", today=_SUN) == date(2026, 12, 25)
    assert resolve_target_date("what time do you close December 25",
                               today=_SUN) == date(2026, 12, 25)
    assert resolve_target_date("hours on Dec 25", today=_SUN) == date(2026, 12, 25)


def test_a_bare_weekday_is_still_a_date():
    """"next monday" reaches us as the fragment "monday". An early version
    of the filter refused it and lost a question that used to work."""
    assert resolve_target_date("when does Art library open next monday",
                               today=_SUN) == date(2026, 9, 7)


def test_tomorrow_survives_a_sentence_with_clock_times_in_it():
    """search_dates never mentions "tomorrow" in "tomorrow 10am to 11am" --
    it returns 10am and 11am and reads them as days of the month, which is
    how a room booking for tomorrow was resolved to May 2027."""
    tomorrow = _SUN + timedelta(days=1)
    assert resolve_target_date("tomorrow 10am to 11am", today=_SUN) == tomorrow
    assert resolve_target_date("book me a study room at King tomorrow at 3pm",
                               today=_SUN) == tomorrow


def test_a_question_with_no_date_still_declines():
    """The filter must not turn every sentence into today."""
    for q in ("what are your hours", "open hours", "where is the makerspace",
              "who is the biology librarian"):
        assert resolve_target_date(q, today=_SUN) is None, q

