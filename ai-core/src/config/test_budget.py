"""The budget ladder: thresholds, hysteresis, and failing open.

The dangerous bugs here are not crashes, they are quiet wrong answers:
a threshold off by one rung silently stops protecting the ceiling, and a
state file that fails CLOSED takes the bot away from every student because
of a JSON typo. Both are tested explicitly.
"""
from __future__ import annotations

import datetime as _dt
import json

from src.config import budget as B


def _aug(day: int = 15) -> _dt.date:
    return _dt.date(2026, 8, day)  # 31 days


# THE SAME IMPORT-ORDER LUCK, IN FOUR TESTS THE NOTE ABOVE MISSED.
#
# They spelled the student purse as $75, which is the module DEFAULT and
# not a number any deployment uses: .env has held $25 before the flip and
# $45 after it since 2026-08-13, deliberately -- the eval purse is the
# larger one during development. So these passed when nothing had loaded
# .env yet and failed in a full run, and a colleague reading the four red
# lines would reasonably conclude the money was misconfigured. It is not;
# the tests were. Found 2026-08-30.
#
# Read the purse from the module. What is worth pinning here is the
# LADDER -- that 85% is where the cheap model comes on -- not the dollar
# figure the ladder is a percentage of.
_PURSE = B.MONTHLY_SERVING_USD


# --- the two purses ------------------------------------------------------


# THESE ASSERTED THE IMPORT-TIME CONSTANTS AND SO DEPENDED ON COLLECTION
# ORDER. `src/main.py` calls load_dotenv(override=True) at import; anything
# that imports it earlier in a run brings BUDGET_LAUNCH_AT and
# BUDGET_POSTLAUNCH_SERVING_USD into the process, the flip resolves to the
# post-launch split, and these failed -- while the same file passed alone.
#
# Found 2026-08-20, and the split flipped on 2026-08-13, so the five tests had
# been passing on import-order luck for a week. They test the FUNCTION at a
# stated moment now, which is what split_for() was built for, and the
# post-launch side is asserted rather than left to chance.
_PRE = _dt.datetime(2026, 8, 1)          # before BUDGET_LAUNCH_AT
_POST = _dt.datetime(2026, 8, 20)        # after it


def test_the_two_purses_are_real_and_separate():
    """No dollar figure here on purpose.

    The split is an operator decision that has already changed once and is
    documented in .env to change again (5/95 when development stops). A
    test that names today's numbers fails on the day somebody follows
    those instructions correctly, which teaches the next reader to ignore
    it. What must hold is that both purses exist, neither is zero, and
    they are not the same number read twice.
    """
    serving, evl = B._PRELAUNCH_SERVING_USD, B._PRELAUNCH_EVAL_USD
    assert serving > 0 and evl > 0
    assert B.MONTHLY_TOTAL_USD == B.MONTHLY_SERVING_USD + B.MONTHLY_EVAL_USD
    assert B.split_for(_PRE) == (serving, evl)


def test_the_flip_takes_effect_at_launch_and_not_before():
    """Only exercised when a launch moment is configured; with none set the
    split never changes, which is the documented default."""
    if B.LAUNCH_AT is None:
        assert B.split_for(_PRE) == B.split_for(_POST)
        return
    before = B.split_for(_PRE if _PRE < B.LAUNCH_AT else B.LAUNCH_AT
                         - _dt.timedelta(days=1))
    after = B.split_for(B.LAUNCH_AT + _dt.timedelta(seconds=1))
    assert before == (B._PRELAUNCH_SERVING_USD, B._PRELAUNCH_EVAL_USD)
    # An unset post-launch figure leaves that purse alone, by design.
    assert after[0] == (B._PRELAUNCH_SERVING_USD
                        if B._POSTLAUNCH_SERVING_USD is None
                        else B._POSTLAUNCH_SERVING_USD)
    assert after[1] == (B._PRELAUNCH_EVAL_USD
                        if B._POSTLAUNCH_EVAL_USD is None
                        else B._POSTLAUNCH_EVAL_USD)


def test_daily_line_divides_the_student_purse_by_the_real_month_length():
    """Not a hardcoded 30: a $2.50 line in February would overspend the purse.

    Ratios, not absolutes, so the month arithmetic is what is under test and
    not whichever side of launch the process happens to have loaded.
    """
    purse = B.MONTHLY_SERVING_USD
    assert B.daily_serving_line(_dt.date(2026, 8, 1)) == purse / 31
    assert B.daily_serving_line(_dt.date(2026, 2, 1)) == purse / 28
    assert B.daily_serving_line(_dt.date(2026, 4, 1)) == purse / 30


# --- the ladder ----------------------------------------------------------


def test_quiet_day_is_normal():
    lvl, _ = B.level_for(serving_today=0.10, serving_mtd=3.00, when=_aug())
    assert lvl == B.L_NORMAL


def test_daily_line_breach_alerts_but_changes_nothing_for_students():
    line = B.daily_serving_line(_aug())
    lvl, reason = B.level_for(serving_today=line * 1.01, serving_mtd=5.0,
                              when=_aug())
    assert lvl == B.L_ALERT
    assert "daily line" in reason
    st = B.BudgetState(level=lvl)
    assert st.force_cheap_model is False
    assert st.refuse_new_conversations is False
    assert st.rate_max == B.RATE_MAX_NORMAL


def test_one_and_a_half_days_of_spend_forces_the_cheap_model():
    line = B.daily_serving_line(_aug())
    lvl, _ = B.level_for(serving_today=line * 1.6, serving_mtd=5.0, when=_aug())
    assert lvl == B.L_CHEAP
    st = B.BudgetState(level=lvl)
    assert st.force_cheap_model is True
    # Degrading quality must NOT also throttle or refuse -- that is two
    # more rungs up, and conflating them would punish students at the
    # first sign of a busy day.
    assert st.rate_max == B.RATE_MAX_NORMAL
    assert st.refuse_new_conversations is False


def test_a_runaway_day_tightens_the_limits():
    line = B.daily_serving_line(_aug())
    lvl, _ = B.level_for(serving_today=line * 3.0, serving_mtd=5.0, when=_aug())
    assert lvl == B.L_TIGHTEN
    st = B.BudgetState(level=lvl)
    assert st.rate_max == B.RATE_MAX_TIGHTENED < B.RATE_MAX_NORMAL
    assert st.max_turns == B.MAX_TURNS_TIGHTENED < B.MAX_TURNS_NORMAL
    assert st.refuse_new_conversations is False, (
        "one expensive day must never take the service away from students"
    )


def test_only_an_exhausted_monthly_purse_refuses_students():
    line = B.daily_serving_line(_aug())
    # A colossal single day: still not a refusal.
    lvl, _ = B.level_for(serving_today=line * 50, serving_mtd=20.0, when=_aug())
    assert lvl == B.L_TIGHTEN
    # The purse actually running out: refusal.
    lvl, reason = B.level_for(serving_today=0.5, serving_mtd=75.0, when=_aug())
    assert lvl == B.L_REFUSE
    assert "month-to-date" in reason
    assert B.BudgetState(level=lvl).refuse_new_conversations is True


def test_monthly_thresholds_are_where_the_design_says():
    for fraction, want in ((0.70, B.L_ALERT),
                           (0.85, B.L_CHEAP),
                           (0.95, B.L_TIGHTEN),
                           (1.00, B.L_REFUSE)):
        mtd = _PURSE * fraction
        lvl, _ = B.level_for(serving_today=0.0, serving_mtd=mtd, when=_aug())
        assert lvl == want, (fraction, mtd, lvl, want)


def test_the_higher_of_the_two_triggers_wins():
    """A quiet day inside an exhausted month must not read as normal."""
    lvl, _ = B.level_for(serving_today=0.0, serving_mtd=_PURSE * 0.96,
                         when=_aug())
    assert lvl == B.L_TIGHTEN
    # ...and a wild day inside a quiet month must not read as normal either.
    line = B.daily_serving_line(_aug())
    lvl, _ = B.level_for(serving_today=line * 2.6, serving_mtd=1.0, when=_aug())
    assert lvl == B.L_TIGHTEN


# --- hysteresis ----------------------------------------------------------


def test_escalation_is_never_delayed():
    """Money is leaving; there is nothing to be gained by waiting."""
    assert B.apply_hysteresis(B.L_REFUSE, B.L_NORMAL, serving_today=0.0,
                              serving_mtd=80.0, when=_aug()) == B.L_REFUSE


def test_recovery_needs_clearance_below_the_trigger():
    """Just under the line is not enough, or the guard flaps and mails
    on every 15-minute crossing."""
    trigger = _PURSE * 0.85          # the rung that put us on the cheap model
    clear = trigger * (1 - B.RECOVERY_MARGIN)
    # Just under the trigger is not clearance -> hold at cheap.
    assert B.apply_hysteresis(B.L_ALERT, B.L_CHEAP, serving_today=0.0,
                              serving_mtd=trigger - 0.01,
                              when=_aug()) == B.L_CHEAP
    # Past the margin -> allowed to step down one rung.
    assert B.apply_hysteresis(B.L_ALERT, B.L_CHEAP, serving_today=0.0,
                              serving_mtd=clear - 0.01,
                              when=_aug()) == B.L_ALERT


def test_recovery_steps_down_one_rung_at_a_time():
    """From refusing to normal in one hop would swing the service wide open
    on a single reading."""
    got = B.apply_hysteresis(B.L_NORMAL, B.L_REFUSE, serving_today=0.0,
                             serving_mtd=0.0, when=_aug())
    assert got == B.L_TIGHTEN


# --- state file ----------------------------------------------------------


# THE MONTH IN A FIXTURE HAS TO BE THIS MONTH.
#
# read_state() deliberately voids a state file from a previous month --
# the purse refilled at midnight on the 1st and nobody should still be
# refusing students on last month's numbers. Two tests below wrote
# `month="2026-08"` and asserted the level came back, which held for
# thirty days and failed on the thirty-first: on 2026-09-01 they returned
# level 0, reason "new month (2026-09)".
#
# A test that goes red one day a month is a test people learn to ignore,
# and this is the second time this file has had one -- see the note about
# the $75 purse further up. The rollover it was accidentally exercising is
# real and worth pinning, so it has its own test now instead.
_THIS_MONTH = _dt.date.today().strftime("%Y-%m")


def test_state_roundtrips(tmp_path):
    p = tmp_path / "state.json"
    st = B.BudgetState(level=B.L_CHEAP, reason="because", serving_mtd=64.0,
                       serving_today=1.0, eval_mtd=12.0,
                       month=_THIS_MONTH,
                       checked_at=_dt.datetime.now().astimezone().isoformat())
    B.write_state(st, p)
    back = B.read_state(p)
    assert back.level == B.L_CHEAP
    assert back.force_cheap_model is True
    assert back.serving_mtd == 64.0
    assert back.missing is False
    assert back.stale is False


def test_write_is_atomic_and_leaves_no_temp_file(tmp_path):
    p = tmp_path / "state.json"
    B.write_state(B.BudgetState(level=B.L_ALERT, month="2026-08"), p)
    assert p.exists()
    assert list(tmp_path.glob("*.tmp")) == []


def test_missing_state_fails_open(tmp_path):
    st = B.read_state(tmp_path / "nope.json")
    assert st.level == B.L_NORMAL
    assert st.missing is True
    assert st.refuse_new_conversations is False


def test_corrupt_state_fails_open_not_closed(tmp_path):
    """A JSON typo must not refuse every student. See FAIL OPEN, LOUDLY."""
    p = tmp_path / "state.json"
    p.write_text("{ this is not json")
    st = B.read_state(p)
    assert st.level == B.L_NORMAL
    assert st.refuse_new_conversations is False
    p.write_text('"a bare string, not an object"')
    assert B.read_state(p).level == B.L_NORMAL


def test_stale_state_keeps_its_level_rather_than_reverting(tmp_path):
    """A broken cron must not quietly un-throttle a runaway month."""
    p = tmp_path / "state.json"
    old = (_dt.datetime.now().astimezone()
           - _dt.timedelta(seconds=B.STALE_AFTER_S + 60))
    p.write_text(json.dumps({
        "level": B.L_TIGHTEN, "reason": "r", "serving_mtd": 72.0,
        "serving_today": 0.1, "eval_mtd": 1.0,
        "month": _dt.date.today().strftime("%Y-%m"),
        "checked_at": old.isoformat(),
    }))
    st = B.read_state(p)
    assert st.stale is True
    assert st.level == B.L_TIGHTEN, "staleness is reported, not corrected"


def test_last_months_state_does_not_throttle_this_month(tmp_path):
    """The purse refills at midnight on the 1st; nobody should still be
    refused on last month's numbers."""
    p = tmp_path / "state.json"
    p.write_text(json.dumps({
        "level": B.L_REFUSE, "reason": "purse empty", "serving_mtd": 80.0,
        "serving_today": 0.0, "eval_mtd": 25.0, "month": "2020-01",
        "checked_at": _dt.datetime.now().astimezone().isoformat(),
    }))
    st = B.read_state(p)
    assert st.level == B.L_NORMAL
    assert st.refuse_new_conversations is False


def test_state_json_denormalises_the_knobs():
    """An operator reading the file by eye, or any other process, should not
    have to re-derive the ladder."""
    d = B.BudgetState(level=B.L_TIGHTEN).to_json()
    assert d["force_cheap_model"] is True
    assert d["rate_max"] == B.RATE_MAX_TIGHTENED
    assert d["max_turns"] == B.MAX_TURNS_TIGHTENED
    assert d["refuse_new_conversations"] is False
    assert d["level_name"] == "tightened"


def test_current_state_is_cached_but_resettable(tmp_path, monkeypatch):
    p = tmp_path / "state.json"
    monkeypatch.setattr(B, "STATE_PATH", p)
    B.reset_cache()
    B.write_state(B.BudgetState(level=B.L_NORMAL, month=_THIS_MONTH), p)
    assert B.current_state().level == B.L_NORMAL
    B.write_state(B.BudgetState(level=B.L_REFUSE, month=_THIS_MONTH), p)
    assert B.current_state().level == B.L_NORMAL, "served from cache"
    B.reset_cache()
    assert B.current_state().level == B.L_REFUSE


def test_every_rung_says_what_changes():
    """The text goes into the alert email and the report; an empty one there
    is a rung nobody can act on."""
    for r in B.LADDER:
        assert r.what_changes.strip()
        assert r.level in B.LEVEL_NAMES
    assert {r.level for r in B.LADDER} == {B.L_ALERT, B.L_CHEAP,
                                          B.L_TIGHTEN, B.L_REFUSE}


# --- the split flips on a date, not when somebody remembers ---------------
#
# The failure this guards against is silent and in the worst direction: on
# the first morning of term students meet a $25 ceiling while $75 sits
# unspent in the eval purse, and nothing says so except complaints.


def test_no_launch_date_means_the_split_never_moves() -> None:
    """The default must be inert. A date nobody set must not flip anything."""
    assert B._moment_env("BUDGET_NO_SUCH_VAR_AT_ALL") is None
    saved = B.LAUNCH_AT
    try:
        B.LAUNCH_AT = None
        assert B.split_for(_dt.date(2026, 9, 4)) == B.split_for(_dt.date(2026, 1, 1))
    finally:
        B.LAUNCH_AT = saved


def test_the_split_flips_at_the_launch_MOMENT_not_that_midnight() -> None:
    """The beta opens at 6pm on a day that is a test day until then, so the
    student ceiling must not arrive eighteen hours early."""
    saved = (B.LAUNCH_AT, B._POSTLAUNCH_SERVING_USD, B._POSTLAUNCH_EVAL_USD)
    try:
        B.LAUNCH_AT = _dt.datetime(2026, 8, 13, 18, 0)
        B._POSTLAUNCH_SERVING_USD = 45.0
        B._POSTLAUNCH_EVAL_USD = None          # eval purse deliberately untouched
        pre = B._PRELAUNCH_SERVING_USD

        assert B.split_for(_dt.datetime(2026, 8, 13, 17, 59))[0] == pre, \
            "one minute before launch is still a test day"
        assert B.split_for(_dt.datetime(2026, 8, 13, 18, 0))[0] == 45.0, \
            "the flip happens AT the moment, not after it"
        assert B.split_for(_dt.datetime(2026, 8, 13, 0, 1))[0] == pre, \
            "midnight on launch day must NOT flip -- that is the whole point"
        assert B.split_for(_dt.datetime(2026, 12, 25))[0] == 45.0, \
            "the flip is permanent, not a one-day event"
    finally:
        B.LAUNCH_AT, B._POSTLAUNCH_SERVING_USD, B._POSTLAUNCH_EVAL_USD = saved


def test_an_unset_post_launch_figure_leaves_that_purse_alone() -> None:
    """Unset means UNCHANGED, not zero. The operator asked for the student
    purse to move and the eval purse to be left alone; getting this wrong
    would silently cut the eval purse to nothing at launch."""
    saved = (B.LAUNCH_AT, B._POSTLAUNCH_SERVING_USD, B._POSTLAUNCH_EVAL_USD)
    try:
        B.LAUNCH_AT = _dt.datetime(2026, 8, 13, 18, 0)
        B._POSTLAUNCH_SERVING_USD = 45.0
        B._POSTLAUNCH_EVAL_USD = None
        serving, evl = B.split_for(_dt.datetime(2026, 8, 14))
        assert serving == 45.0
        assert evl == B._PRELAUNCH_EVAL_USD, \
            "the eval purse must be untouched, not zeroed"
        # and the mirror case
        B._POSTLAUNCH_SERVING_USD = None
        B._POSTLAUNCH_EVAL_USD = 5.0
        serving, evl = B.split_for(_dt.datetime(2026, 8, 14))
        assert serving == B._PRELAUNCH_SERVING_USD
        assert evl == 5.0
    finally:
        B.LAUNCH_AT, B._POSTLAUNCH_SERVING_USD, B._POSTLAUNCH_EVAL_USD = saved


def test_a_bare_date_still_works_and_means_midnight() -> None:
    saved = B.LAUNCH_AT
    try:
        assert B._moment_env("BUDGET_NO_SUCH_VAR") is None
        import os
        os.environ["BUDGET_TEST_MOMENT"] = "2026-08-13"
        assert B._moment_env("BUDGET_TEST_MOMENT") == _dt.datetime(2026, 8, 13, 0, 0)
        os.environ["BUDGET_TEST_MOMENT"] = "2026-08-13T18:00"
        assert B._moment_env("BUDGET_TEST_MOMENT") == _dt.datetime(2026, 8, 13, 18, 0)
        del os.environ["BUDGET_TEST_MOMENT"]
    finally:
        B.LAUNCH_AT = saved


def test_a_mistyped_launch_date_keeps_the_pre_launch_split(monkeypatch) -> None:
    """Failing towards LESS student budget is the safe direction: it shows up
    as a throttled student and a complaint, not as an invoice."""
    monkeypatch.setenv("BUDGET_LAUNCH_AT", "Sept 4th")
    assert B._moment_env("BUDGET_LAUNCH_AT") is None
    monkeypatch.setenv("BUDGET_LAUNCH_AT", "2026-13-45")
    assert B._moment_env("BUDGET_LAUNCH_AT") is None
    monkeypatch.setenv("BUDGET_LAUNCH_AT", "2026-09-04")
    assert B._moment_env("BUDGET_LAUNCH_AT") == _dt.datetime(2026, 9, 4)


def test_the_ceiling_actually_refuses_at_one_hundred_percent() -> None:
    """$45 has to be a wall, not a suggestion: the operator is spending it to
    collect real student data and needs to know the ladder ends in refusal."""
    # level_for measures against the module's own purse, so assert at 100%
    # of whatever that currently is rather than hardcoding a figure.
    purse = B.MONTHLY_SERVING_USD
    lvl, why = B.level_for(serving_today=0.0, serving_mtd=purse,
                           when=_dt.date(2026, 8, 20))
    assert lvl == B.L_REFUSE, f"at 100% of ${purse:.2f} the ladder said {why}"
    # and one cent under the wall is not refusal
    lvl_under, _ = B.level_for(serving_today=0.0, serving_mtd=purse * 0.96,
                               when=_dt.date(2026, 8, 20))
    assert lvl_under < B.L_REFUSE


def test_a_state_file_from_last_month_is_void_not_stale(tmp_path):
    """The purse refills at midnight on the 1st, so a level carried over
    from last month would refuse students on numbers that no longer apply.

    This behaviour was real and unpinned -- the only thing exercising it
    was two round-trip tests going red every 1st of the month, which is
    the opposite of a test.
    """
    p = tmp_path / "state.json"
    B.write_state(B.BudgetState(level=B.L_REFUSE, reason="spent",
                                serving_mtd=99.0, month="2020-01"), p)
    back = B.read_state(p)
    assert back.level == B.L_NORMAL
    assert "new month" in back.reason
    assert back.month == _dt.date.today().strftime("%Y-%m")
    # Void, not missing: the file was read fine, its contents just no
    # longer apply. Reporting it as missing would send a "the guard has
    # not run" alert on the 1st of every month.
    assert back.missing is False


def test_a_state_file_from_this_month_keeps_its_level(tmp_path):
    p = tmp_path / "state.json"
    B.write_state(B.BudgetState(level=B.L_REFUSE, reason="spent",
                                month=_THIS_MONTH), p)
    assert B.read_state(p).level == B.L_REFUSE
