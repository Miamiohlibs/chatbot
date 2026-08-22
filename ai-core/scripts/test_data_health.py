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
        # send failure as a passing test.
        calls.append((subject, body, to))
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
                        lambda *a, **k: None)
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
