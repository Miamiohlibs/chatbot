"""LibCal is hand-maintained, and on 2026-08-26 it published Special
Collections as open "8:00pm to 4:00pm" on the Friday -- an am/pm typo
against the 8:00am the other four weekdays carried. The bot repeated it
word for word.

The hard part is not catching it. It is catching it WITHOUT catching
King Library, which really is open until 1:00am and whose interval wraps
midnight in exactly the same way.
"""

import pytest

from src.tools.libcal_comprehensive_tools import (
    HOURS_NOT_POSTED,
    describe_libcal_day,
    interval_is_impossible,
)


class TestIntervalIsImpossible:
    @pytest.mark.parametrize("frm,to", [
        ("8:00pm", "4:00pm"),   # the real one, from LibCal 2026-08-28
        ("7:00pm", "3:00pm"),
        ("11:00pm", "12:00pm"),
    ])
    def test_wraps_midnight_and_closes_in_the_afternoon(self, frm, to):
        assert interval_is_impossible(frm, to)

    @pytest.mark.parametrize("frm,to", [
        ("7:00am", "1:00am"),    # King, a normal term weeknight
        ("10:00am", "2:00am"),   # King during finals
        ("9:00pm", "12:00am"),   # a late study space
        ("8:00pm", "2:00am"),
    ])
    def test_a_real_overnight_close_is_left_alone(self, frm, to):
        """The whole risk of this guard. A wrong "closed" costs a patron
        a trip just as surely as a wrong "open"."""
        assert not interval_is_impossible(frm, to)

    @pytest.mark.parametrize("frm,to", [
        ("8:00am", "4:00pm"),
        ("9:00am", "9:00pm"),
        ("12:00pm", "5:00pm"),
        ("12:00am", "11:59pm"),
    ])
    def test_ordinary_days_untouched(self, frm, to):
        assert not interval_is_impossible(frm, to)

    @pytest.mark.parametrize("frm,to", [
        ("", "4:00pm"), (None, "4:00pm"), ("half past eight", "4:00pm"),
        ("25:00", "4:00pm"), ("8:75pm", "4:00pm"),
    ])
    def test_unparseable_is_never_called_impossible(self, frm, to):
        """Guessing at a time we cannot read would turn a display bug
        into a coverage bug."""
        assert not interval_is_impossible(frm, to)

    def test_24_hour_clock_input(self):
        assert not interval_is_impossible("07:00", "23:00")
        assert interval_is_impossible("20:00", "16:00")


class TestDescribeLibcalDay:
    def test_the_real_friday_is_declined(self):
        day = {"status": "open", "hours": [{"from": "8:00pm", "to": "4:00pm"}]}
        state, display = describe_libcal_day(day)
        assert state == "unknown"
        assert display == HOURS_NOT_POSTED

    def test_the_real_thursday_still_answers(self):
        day = {"status": "open", "hours": [{"from": "8:00am", "to": "4:00pm"}]}
        assert describe_libcal_day(day) == ("open", "8:00am to 4:00pm")

    def test_one_bad_interval_condemns_the_whole_day(self):
        """A split day -- morning plus evening -- with one impossible
        half cannot be partly published: we do not know which half is
        the typo, so stating either is a guess."""
        day = {"status": "open", "hours": [
            {"from": "8:00am", "to": "12:00pm"},
            {"from": "8:00pm", "to": "4:00pm"},
        ]}
        assert describe_libcal_day(day)[0] == "unknown"

    def test_a_normal_split_day_is_fine(self):
        day = {"status": "open", "hours": [
            {"from": "8:00am", "to": "12:00pm"},
            {"from": "1:00pm", "to": "5:00pm"},
        ]}
        state, display = describe_libcal_day(day)
        assert state == "open"
        assert display == "8:00am to 12:00pm and 1:00pm to 5:00pm"

    def test_closed_and_text_days_are_not_affected(self):
        assert describe_libcal_day({"status": "closed"})[0] == "closed"
        assert describe_libcal_day(
            {"status": "text", "text": "9am-4pm by appt"}
        )[0] == "text"
