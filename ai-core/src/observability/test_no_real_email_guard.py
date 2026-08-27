"""The suite cannot send a real email.

src/api/admin/test_ticket_conversation_link.py posted three correction
tickets per run and did not stub send_alert_email, so every full-suite run
mailed the operator three times -- "Chatbot correction ticket from Kevin /
Where is the music library? / Amos Music Library.", that file's fixture
data. The suite ran more than a dozen times on 2026-08-27 before anybody
connected the inbox to the test run.

The old arrangement relied on every author remembering to monkeypatch it.
One file forgot, and there was nothing between that and the operator's
inbox. These tests are the proof that forgetting is no longer enough.
"""

import smtplib

import pytest


def test_opening_an_smtp_connection_fails_loudly():
    """Not silently swallowed: a test that tries to mail somebody has a
    bug in it and should say so, rather than passing quietly."""
    with pytest.raises(AssertionError) as e:
        smtplib.SMTP("localhost", 25)
    assert "SMTP" in str(e.value)


def test_smtp_ssl_is_blocked_too():
    with pytest.raises(AssertionError):
        smtplib.SMTP_SSL("localhost", 465)


def test_the_wrapper_reports_success_without_sending():
    """Code that branches on the result -- the ticket handler sets
    emailSent from it -- has to keep exercising the success branch."""
    from src.observability.alerting import send_alert_email

    assert send_alert_email(subject="s", body="b") is True


def test_the_guard_is_autouse_not_opt_in():
    """No import, no fixture request, no decorator in this file asks for
    the block. If it only applied on request it would not have caught the
    file that forgot."""
    assert smtplib.SMTP is not smtplib.socket.socket  # sanity
    with pytest.raises(AssertionError):
        smtplib.SMTP()
