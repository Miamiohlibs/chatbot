"""Tests for data_health's reporting contract.

WHY: `--quiet` meant "no stdout at all", so under cron it wrote a 0-byte log
forever. That file is indistinguishable from "the check never ran" -- and it
cost real time: an 81-day-old corpus was being reported there every morning
and read as silence. The email path was working the whole time; the log was
the thing lying.
"""
from __future__ import annotations

import scripts.data_health as dh


def _finding(name, ok, summary="s", detail=()):
    return dh.Finding(name, ok, summary, list(detail))


def _run(monkeypatch, findings, quiet, capsys, sent=None):
    monkeypatch.setattr(dh, "CHECKS", [lambda f=f: f for f in findings])
    calls = []

    def _fake_send(subject, body, to=None):
        # `to` matters now: the daily report goes to a wider list than the
        # incident alerts, and a fake that cannot receive it would hide a
        # send failure as a passing test. Returning True matters too --
        # the real function returns a bool and main() branches on it.
        calls.append((subject, body, to))
        return True
    monkeypatch.setattr("src.observability.alerting.send_alert_email", _fake_send)
    code = dh.main(force_email=False, quiet=quiet)
    if sent is not None:
        sent.extend(calls)
    return code, capsys.readouterr().out


def test_quiet_prints_nothing_when_every_check_passes(monkeypatch, capsys):
    """An empty log must genuinely mean all clear -- that is the whole point
    of keeping quiet mode quiet."""
    code, out = _run(monkeypatch, [_finding("a", True), _finding("b", True)],
                     quiet=True, capsys=capsys)
    assert out.strip() == ""
    assert code == 0


def test_quiet_still_prints_the_things_that_need_a_human(monkeypatch, capsys):
    """The regression: 0-byte log while the corpus aged 81 days."""
    code, out = _run(monkeypatch, [
        _finding("all good", True, "fine"),
        _finding("corpus freshness", False, "the search index is 81 days old",
                 ["a librarian must sign the .approval file"]),
    ], quiet=True, capsys=capsys)
    assert "corpus freshness" in out
    assert "81 days old" in out
    assert "[ACT]" in out
    assert "a librarian must sign" in out, "detail lines carry the action"
    assert code == 1


def test_quiet_omits_the_passing_checks(monkeypatch, capsys):
    """Quiet is still quiet: OK rows stay out so the log is all signal."""
    _, out = _run(monkeypatch, [
        _finding("roster vs CSV", True, "74 people, matches"),
        _finding("corpus freshness", False, "81 days old"),
    ], quiet=True, capsys=capsys)
    assert "roster vs CSV" not in out
    assert "[OK ]" not in out


def test_verbose_prints_everything(monkeypatch, capsys):
    _, out = _run(monkeypatch, [
        _finding("roster vs CSV", True, "74 people, matches"),
        _finding("corpus freshness", False, "81 days old"),
    ], quiet=False, capsys=capsys)
    assert "roster vs CSV" in out and "corpus freshness" in out


def test_problems_are_emailed_in_quiet_mode_too(monkeypatch, capsys):
    """Quiet only ever governed stdout; the notification is the real channel
    and must not depend on it."""
    sent = []
    _run(monkeypatch, [_finding("corpus freshness", False, "81 days old")],
         quiet=True, capsys=capsys, sent=sent)
    assert len(sent) == 1
    # No "needs you" wording: this mail goes to colleagues as well as the
    # operator, and a subject telling three people something needs them
    # when it needs one of them is how a daily mail becomes a filter rule.
    subject = sent[0][0]
    assert "need you" not in subject.lower()
    assert "maintenance item" in subject
    assert "81 days old" in sent[0][1]


def test_exit_code_reports_whether_anything_needs_action(monkeypatch, capsys):
    ok, _ = _run(monkeypatch, [_finding("a", True)], quiet=True, capsys=capsys)
    bad, _ = _run(monkeypatch, [_finding("a", False)], quiet=True, capsys=capsys)
    assert (ok, bad) == (0, 1)


def test_a_check_that_raises_becomes_a_finding_not_a_crash(monkeypatch, capsys):
    def _boom():
        raise RuntimeError("weaviate is down")
    monkeypatch.setattr(dh, "CHECKS", [_boom, lambda: _finding("b", True)])
    monkeypatch.setattr("src.observability.alerting.send_alert_email",
                        lambda *a, **k: True)  # the real one returns a bool
    code = dh.main(force_email=False, quiet=True)
    out = capsys.readouterr().out
    assert code == 1
    assert "the check itself failed" in out
    assert "weaviate is down" in out
    assert "_boom" in out


# --- what the daily report is allowed to say -------------------------------
#
# Operator ruling 2026-08-22, after the mail started going to colleagues:
# refusals, out-of-scope answers and low-confidence turns are the bot working
# correctly. Declining what it cannot support is the design. Mailing them
# every morning trained the reader to skim past the whole message, and buried
# the two signals where a human actually said the answer was no good.


def test_the_report_does_not_carry_refusals_or_confidence_as_findings():
    """Read from source, because the failure is a check being ADDED back.

    A behavioural test would need the check to exist before it could catch
    it, which is one deploy too late.
    """
    import inspect
    src = inspect.getsource(dh)
    names = [n for n in dir(dh) if n.startswith("check_")]
    assert "check_real_questions_we_failed" not in names, (
        "the refusal check is back; refusals are the bot working correctly "
        "and are not patron feedback")
    assert "check_what_real_users_disliked" in names
    # And nothing else grew a refusal-shaped report.
    checks = inspect.getsource(dh).split("CHECKS = (")[1].split(")")[0]
    for banned in ("refus", "out_of_scope", "low_confidence"):
        assert banned not in checks.lower(), banned


def test_the_feedback_check_ignores_our_own_testing():
    """Scripted runs and staff rehearsals produce thumbs-downs too.

    Reporting those as patron dissatisfaction inflates the one number this
    mail exists to carry.
    """
    import inspect
    src = inspect.getsource(dh.check_what_real_users_disliked)
    assert "TESTING_TAGS" in src
    assert "sources_for_conversations" in src, (
        "the check must use the same classifier as the dashboard, or the "
        "two will disagree about who somebody was")


def test_the_feedback_check_reads_thumbs_and_ratings_only():
    import inspect
    src = inspect.getsource(dh.check_what_real_users_disliked)
    assert "isPositiveRated" in src
    assert "conversationfeedback" in src
    assert "wasRefusal" not in src, "refusals are not patron feedback"


def test_patron_feedback_is_the_first_thing_in_the_body(monkeypatch, capsys):
    # It is what the readers asked to see. The maintenance checks would bury
    # it if they came first.
    sent = []
    _run(monkeypatch,
         [_finding("corpus freshness", False, "81 days old"),
          _finding("what real users disliked", False, "2 complaints")],
         quiet=True, capsys=capsys, sent=sent)
    body = sent[0][1]
    assert body.index("what real users disliked") < body.index("corpus freshness")


def test_the_report_goes_to_its_own_list_not_the_alert_list(monkeypatch,
                                                            capsys):
    """Colleagues asked to see the daily report, not every incident alert.

    Adding them to ALERT_EMAIL_TO would have signed them up for
    dependency-down mail at three in the morning.
    """
    monkeypatch.setenv("DAILY_REPORT_EMAIL_TO", "a@x.edu,b@x.edu")
    sent = []
    _run(monkeypatch, [_finding("corpus freshness", False, "old")],
         quiet=True, capsys=capsys, sent=sent)
    assert sent[0][2] == "a@x.edu,b@x.edu"


def test_with_no_list_configured_it_falls_back_to_the_operator(monkeypatch,
                                                               capsys):
    monkeypatch.delenv("DAILY_REPORT_EMAIL_TO", raising=False)
    sent = []
    _run(monkeypatch, [_finding("corpus freshness", False, "old")],
         quiet=True, capsys=capsys, sent=sent)
    assert sent[0][2] is None, "None means send_alert_email uses ALERT_EMAIL_TO"


def test_the_subject_leads_with_the_complaint_when_there_is_one(monkeypatch,
                                                               capsys):
    sent = []
    _run(monkeypatch,
         [_finding("corpus freshness", False, "81 days old"),
          _finding("what real users disliked", False,
                   "2 piece(s) of negative feedback from real users")],
         quiet=True, capsys=capsys, sent=sent)
    assert "negative feedback" in sent[0][0]


def test_an_unrated_comment_is_not_counted_as_a_bad_rating():
    """The star widget initialises to 0 and submits whatever it holds.

    So 0 means "wrote a comment, never picked a star" -- not one star. The
    real row this protects reads "this is just Kevin checking that the bot
    is up and running", which is neither a complaint nor a patron.
    """
    import inspect
    src = inspect.getsource(dh.check_what_real_users_disliked)
    assert "<= 0" in src or "0 <" in src, (
        "the zero-rating guard is gone; every comment-only submission will "
        "be mailed as patron dissatisfaction")


def test_an_all_clear_morning_still_sends_the_report(monkeypatch, capsys):
    """The bug this locks down: on 2026-08-23 every check passed, so nothing
    was mailed, and the three readers concluded the cron was broken.

    Silence has to mean one thing. Now it means the job did not run.
    """
    sent = []
    code, _ = _run(monkeypatch, [_finding("a", True), _finding("b", True)],
                   quiet=True, capsys=capsys, sent=sent)
    assert len(sent) == 1, "an all-clear day must still produce a report"
    assert "all clear" in sent[0][0]
    assert code == 0, "all clear is not a failure exit"


def test_a_failed_send_is_logged_as_a_failure_not_as_success(monkeypatch,
                                                             capsys, caplog):
    """send_alert_email returns False instead of raising.

    So the happy-path log line had to be conditional, or a morning where
    nobody was told would read in the log exactly like one where they were.
    """
    monkeypatch.setattr(dh, "CHECKS", [lambda: _finding("a", True)])
    monkeypatch.setattr("src.observability.alerting.send_alert_email",
                        lambda subject, body, to=None: False)
    with caplog.at_level("ERROR"):
        code = dh.main(force_email=False, quiet=True)
    capsys.readouterr()
    assert code == 2, "a report nobody received is not a successful run"
    assert any("SEND FAILED" in r.message for r in caplog.records)


# --- LibCal impossible-interval check ------------------------------------
#
# WHY: LibCal published Special Collections as open "8:00pm to 4:00pm" on
# 2026-08-28 and 2026-09-04 -- both Fridays, so a recurring entry with an
# am/pm typo -- and the bot repeated it word for word. The bot now declines
# such an interval, but declining is not fixing: those days read "hours not
# posted" until the calendar's owner edits LibCal, and only this check tells
# them to.


class _Loc:
    def __init__(self, payload):
        self.payload = payload


def _wire(monkeypatch, locations, payload):
    monkeypatch.setattr(dh, "_libcal_locations", lambda: locations)

    async def _token():
        return "t"

    class _Resp:
        def raise_for_status(self): pass
        def json(self): return payload

    class _Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, *a, **k): return _Resp()

    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", lambda **k: _Client())
    monkeypatch.setattr(
        "src.tools.libcal_comprehensive_tools._get_oauth_token", _token
    )


def _payload(intervals_by_day):
    return [{"dates": {
        day: {"status": "open", "hours": ivs}
        for day, ivs in intervals_by_day.items()
    }}]


def test_libcal_check_reports_the_impossible_friday(monkeypatch):
    _wire(monkeypatch, [("8424", "Special Collections")],
          _payload({"2026-08-28": [{"from": "8:00pm", "to": "4:00pm"}]}))
    f = dh.check_libcal_hours_are_possible()
    assert not f.ok
    assert "2026-08-28" in " ".join(f.detail)
    assert "8424" in " ".join(f.detail)


def test_libcal_check_passes_on_a_real_overnight_close(monkeypatch):
    """King really is open until 1:00am. Reporting that as broken would
    make this check worse than not having it."""
    _wire(monkeypatch, [("1234", "King")],
          _payload({"2026-08-28": [{"from": "7:00am", "to": "1:00am"}]}))
    assert dh.check_libcal_hours_are_possible().ok


def test_libcal_check_says_how_much_it_looked_at(monkeypatch):
    _wire(monkeypatch, [("1", "A"), ("2", "B")],
          _payload({"2026-08-28": [{"from": "8:00am", "to": "4:00pm"}]}))
    f = dh.check_libcal_hours_are_possible()
    assert f.ok and "2 location" in f.summary


def test_seeing_nothing_is_not_the_same_as_all_clear(monkeypatch):
    """The bug the first version of this check shipped with.

    It looked spaces up with psycopg, which is not installed here, and
    swallowed the ImportError into an empty list -- then reported "no
    impossible intervals" while having read nothing at all. A health
    check that cannot see must say so."""
    def _boom():
        raise RuntimeError("no module named psycopg")
    monkeypatch.setattr(dh, "_libcal_locations", _boom)
    f = dh.check_libcal_hours_are_possible()
    assert not f.ok
    assert "Nothing was checked" in " ".join(f.detail)


def test_a_libcal_outage_does_not_double_alarm(monkeypatch):
    """check_dependencies already reports LibCal being down. One cause
    must not ring two alarms in the same mail."""
    _wire(monkeypatch, [("8424", "Special Collections")], None)

    import httpx

    class _Dead:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, *a, **k): raise RuntimeError("connection refused")

    monkeypatch.setattr(httpx, "AsyncClient", lambda **k: _Dead())
    f = dh.check_libcal_hours_are_possible()
    assert f.ok and "skipped" in f.summary
