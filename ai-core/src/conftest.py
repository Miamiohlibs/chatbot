"""Shared pytest fixtures for the ai-core test suite."""
from __future__ import annotations

import pytest

from src.prompts import builder

# Ensure every SHIPPED prefix is registered, then snapshot that as the
# clean baseline. Importing the modules runs their module-level
# register_prefix() calls (idempotent).
from src.prompts import (  # noqa: E402,F401
    agent_v1,
    clarifier_v1,
    judge_v1,
    synthesizer_v1,
)

_BASELINE_REGISTRY = dict(builder._REGISTRY)


@pytest.fixture(autouse=True)
def _isolate_prefix_registry():
    """Reset the global prompt-prefix registry to the shipped-prefix
    baseline around EVERY test.

    The registry is a module-level global. Tests register throwaway
    prefixes (e.g. ``test_client_prefix_v1`` via _ensure_test_prefix) or
    clear it (test_builder), and the registry holds whatever was last
    written. Without isolation that leaked across modules and produced
    order-dependent failures under ``pytest src/`` that did NOT reproduce
    when a module ran alone -- the classic symptom being
    test_cache_health's "every registered prefix clears the 1024-token
    cache threshold" tripping over a leaked 237-token throwaway prefix,
    or "current prefixes registered" failing because an earlier test had
    cleared the registry.

    Resetting to the SHIPPED baseline (not just snapshot/restore) means
    every test starts from exactly the production set: no junk, all
    shipped prefixes present. Production is unaffected -- the running app
    registers prefixes once at import and never clears them; this is
    purely test hygiene that makes the suite order-independent.
    """
    builder._REGISTRY.clear()
    builder._REGISTRY.update(_BASELINE_REGISTRY)
    try:
        yield
    finally:
        builder._REGISTRY.clear()
        builder._REGISTRY.update(_BASELINE_REGISTRY)

# --- never let a test touch production booking state ---------------------
#
# Caught 2026-08-04: test_real_backends drives book_room with confirm=True
# against a fake LibCal, so booking_quota.record() fired against the REAL
# ledger at /opt/chatbot/data/booking_quota.json and left the operator's own
# address sitting at its daily cap. A unit suite must not be able to consume
# a real student's allowance, so this is enforced for every test rather than
# remembered per file.
@pytest.fixture(autouse=True)
def _isolate_booking_ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("BOOKING_QUOTA_PATH", str(tmp_path / "booking_quota.json"))
    yield

@pytest.fixture(autouse=True)
def _no_real_audit_log(monkeypatch, tmp_path_factory):
    """A test can never write to the real audit log.

    WHY THIS EXISTS. The corpus gate and the kill switch started recording
    to data/audit/ on 2026-08-30. The tests written WITH that change
    redirected the directory; the dozen tests written before it did not,
    and they exercise the same endpoints -- so a full-suite run appended
    its fixture data to the production log. Twenty kilobytes of
    `a@miamioh.edu` and `ip: testclient` were sitting in the August file
    before anybody looked.

    That log is the thing that replaced a shared passphrase. A record
    nobody trusts is worth less than the control it replaced, and one that
    fills with test rows on every CI run is one nobody will trust.

    Autouse and directory-level, so remembering is no longer part of it. A
    test that WANTS to assert on the log redirects AUDIT_DIR itself and
    still gets a private one.
    """
    from src.api.admin import audit

    monkeypatch.setattr(
        audit, "AUDIT_DIR",
        tmp_path_factory.mktemp("audit"), raising=False)


@pytest.fixture(autouse=True)
def _no_real_email(monkeypatch, request):
    """A test can never send a real alert email.

    WHY THIS EXISTS. src/api/admin/test_ticket_conversation_link.py posted
    three tickets per run and did NOT stub send_alert_email, so every
    full-suite run mailed the operator three times. They arrived as
    "Chatbot correction ticket from Kevin / Where is the music library? /
    Amos Music Library." -- that file's fixture data -- and there were
    dozens before anybody connected the mail to the test run. The suite was
    run more than a dozen times that day.

    The old arrangement relied on every author remembering to monkeypatch
    it. One file forgot and there was nothing between that and the
    operator's inbox. Autouse, so forgetting is no longer possible.

    The socket layer is patched, not just the wrapper: a test that reaches
    for smtplib directly, or a helper that builds its own client, is
    caught too. Raising rather than silently swallowing -- a test that
    tries to send mail is a test with a bug in it, and it should say so
    loudly instead of passing.

    Opt out for the two tests that exist to check the sender itself:

        @pytest.mark.allow_real_email
    """
    if request.node.get_closest_marker("allow_real_email") is not None:
        return

    import smtplib

    def _blocked(*a, **kw):
        raise AssertionError(
            "a test tried to open an SMTP connection. Stub "
            "send_alert_email (see test_ticket_router.py) instead of "
            "mailing the operator -- this fired for real dozens of times "
            "on 2026-08-27."
        )

    monkeypatch.setattr(smtplib, "SMTP", _blocked)
    monkeypatch.setattr(smtplib, "SMTP_SSL", _blocked)

    # And make the wrapper a no-op returning "sent", so the code paths that
    # branch on its result still exercise the success branch.
    try:
        from src.observability import alerting

        monkeypatch.setattr(alerting, "send_alert_email",
                            lambda *a, **kw: True)
    except Exception:  # noqa: BLE001 -- never break collection over this
        pass


def pytest_configure(config):
    """Register the opt-out marker so --strict-markers stays usable."""
    config.addinivalue_line(
        "markers",
        "allow_real_email: this test exercises the mail sender itself; the "
        "suite-wide SMTP block is lifted for it.",
    )
