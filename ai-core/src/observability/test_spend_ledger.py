"""The spend ledger's failure behaviour, which is the part that matters.

The arithmetic is cost_rollup's and already tested there. What is new here
is *when the ledger is allowed to fail*, and the two answers are opposite
on purpose:

  record_eval_spend  must NEVER raise -- it is called at the end of a
                     100-minute run whose results are already on disk.
  read_spend         must return None, not zeros -- zeros read as a quiet
                     month and would let the guard clear a level it should
                     be holding.
"""
from __future__ import annotations

import datetime as _dt

from src.observability import spend_ledger as SL


def test_month_start():
    assert SL._month_start(_dt.date(2026, 8, 17)) == _dt.date(2026, 8, 1)
    assert SL._month_start(_dt.date(2026, 1, 1)) == _dt.date(2026, 1, 1)


def test_total_is_both_purses():
    s = SL.Spend(serving_mtd=40.0, eval_mtd=12.0)
    assert s.total_mtd == 52.0


def test_recording_nothing_is_a_success_not_a_db_round_trip(monkeypatch):
    called = {"n": 0}

    def boom(*a, **k):
        called["n"] += 1
        raise AssertionError("should not touch the DB for an empty batch")

    monkeypatch.setattr(SL.asyncio, "run", boom)
    assert SL.record_eval_spend([]) is True
    assert called["n"] == 0


async def _boom(*a, **k):
    raise RuntimeError("db is gone")


def test_record_eval_spend_never_raises(monkeypatch):
    """A dead DB must not kill a run that has already produced its results."""
    monkeypatch.setattr(SL, "_arecord_eval_spend", _boom)
    assert SL.record_eval_spend(
        [{"model": "gpt-5.6-terra", "input_tokens": 1000,
          "cached_input_tokens": 0, "output_tokens": 100, "calls": 1}]
    ) is False


def test_read_spend_returns_none_not_zeros_on_failure(monkeypatch):
    """Zeros would look like a quiet month and clear a degrade level."""
    monkeypatch.setattr(SL, "_aread_spend", _boom)
    got = SL.read_spend()
    assert got is None
    assert got != SL.Spend(), "an empty Spend() is the dangerous wrong answer"


def test_eval_call_site_is_distinct_from_serving_call_sites():
    """DailyCost's unique key is (date, model, callSite). If "eval" collided
    with a serving call site, the rollup and the eval would overwrite each
    other's rows."""
    serving_sites = {"agent_loop", "synthesizer", "clarifier", "judge",
                     "embedding", "v2_turn"}
    assert SL.EVAL_CALL_SITE not in serving_sites


def test_dev_call_sites_are_charged_to_development_not_students():
    """The operator's own test harness is development spend.

    Charging it to the students' purse made a $1.17 afternoon of testing
    breach a $0.81 student daily line -- the guard would have paged the
    operator about their own work, and the ceiling would have throttled
    students because of traffic no student generated.
    """
    assert "v2_turn_dev" in SL.DEV_CALL_SITES
    assert "v2_turn" not in SL.DEV_CALL_SITES, (
        "real student traffic must stay on the students' purse"
    )
    assert SL.EVAL_CALL_SITE not in SL.DEV_CALL_SITES, (
        "the eval has its own call site and its own accounting path"
    )


# --- a librarian testing spends from the testing purse --------------------

def test_staff_test_traffic_is_charged_to_testing():
    """`dev` is true only for a script or localhost -- no browser origin at
    all. A librarian testing through /librarian/staff-test arrives in a
    real browser from our own host, so every question she asked was
    charged to the STUDENT purse. Measured 2026-09-01: $0.38 of $2.30,
    seventeen per cent of what that purse had spent, and growing as the
    eight department heads start testing."""
    from src.observability.spend_ledger import DEV_CALL_SITES

    assert "v2_turn_staff" in DEV_CALL_SITES
    assert "v2_turn" not in DEV_CALL_SITES, "a patron still spends from theirs"


def test_the_three_testing_labels_stay_distinct():
    """One purse, three labels. Keeping them apart in the record is what
    lets the cost page answer "how much of that was us developing versus
    us checking"."""
    from src.observability.spend_ledger import DEV_CALL_SITES

    assert len(set(DEV_CALL_SITES)) == 3


def test_the_socket_picks_the_label_from_the_marker():
    """Read from source: the choice is made in the token-logging call and
    there is no unit-testable seam around a live socket."""
    # Read the FILE, do not import it. `import src.main` builds the whole
    # application -- it opens logs/app.log, which root owns, so this test
    # passed as root and failed as anybody else. A test that depends on
    # who runs it is a test that reports the wrong thing half the time.
    import pathlib

    src = (pathlib.Path(__file__).resolve().parents[1] / "main.py").read_text(
        encoding="utf-8")
    i = src.index('call_site=("v2_turn_dev"')
    block = src[i:i + 300]
    assert "v2_turn_staff" in block
    assert "client_is_staff_test" in block
