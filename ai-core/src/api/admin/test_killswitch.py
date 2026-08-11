"""The one-click shutdown promised to colleagues.

Two properties matter more than the button working:
  * a PAUSED bot must stay paused across a restart -- if it was paused
    because it was misbehaving, a crash-restart must not put it back in
    service silently
  * the flag must be clearable WITHOUT this router, so a broken web surface
    never leaves the operator with no way out
"""

import pytest

from src.api.admin import killswitch_router as ks


@pytest.fixture(autouse=True)
def flag(tmp_path, monkeypatch):
    p = tmp_path / "SERVICE_PAUSED"
    monkeypatch.setattr(ks, "_FLAG_PATH", p)
    yield p


def test_starts_in_service(flag):
    assert ks.is_paused() is False


def test_pause_then_resume(flag):
    ks.pause(who="test", note="because")
    assert ks.is_paused() is True
    assert "because" in ks.pause_reason()
    assert "paused_by: test" in ks.pause_reason()
    ks.resume(who="test")
    assert ks.is_paused() is False


def test_the_flag_is_a_file_so_it_survives_a_restart(flag):
    """A module-level variable would be lost on restart, silently putting a
    deliberately-paused bot back in front of patrons."""
    ks.pause(who="test")
    assert flag.exists(), "the state must be on disk, not in memory"
    # simulate a fresh process: nothing in memory, flag still there
    assert ks.is_paused() is True


def test_it_can_be_cleared_without_the_web_ui(flag):
    """Escape hatch: if the admin page is broken, deleting the file works."""
    ks.pause(who="test")
    flag.unlink()
    assert ks.is_paused() is False


def test_resuming_when_not_paused_is_harmless(flag):
    ks.resume(who="test")          # no exception
    assert ks.is_paused() is False


def test_a_broken_flag_path_fails_open(monkeypatch):
    """If the check itself breaks, the bot must keep SERVING -- an
    observability bug must not take the service down."""
    class Boom:
        def exists(self):
            raise OSError("disk gone")
    monkeypatch.setattr(ks, "_FLAG_PATH", Boom())
    assert ks.is_paused() is False


def test_the_patron_message_points_somewhere_useful():
    """A maintenance notice that just says "unavailable" wastes the turn."""
    assert "Ask Us" in ks.PAUSED_MESSAGE
    assert "lib.miamioh.edu" in ks.PAUSED_MESSAGE


# --- who may work the switch ---------------------------------------------
#
# Operator ruling 2026-08-10: the admin token alone is too easy for a
# control that takes the service down. Both actions also need an email from
# SERVICE_PAUSE_OPERATORS plus the shared passphrase.


@pytest.fixture()
def creds(monkeypatch):
    monkeypatch.setenv("SERVICE_PAUSE_OPERATORS",
                       "qum@miamioh.edu, Bomholmm@MiamiOH.edu ,maderir@miamioh.edu")
    monkeypatch.setenv("SERVICE_PAUSE_PASSWORD", "test-passphrase")


def test_an_operator_on_the_list_with_the_passphrase_is_allowed(creds):
    assert ks.check_operator("qum@miamioh.edu", "test-passphrase") is None


def test_the_email_match_ignores_case_and_padding(creds):
    """Operators type their own address; "  Qum@MiamiOH.edu " is the same
    person as the list entry."""
    assert ks.check_operator("  Qum@MiamiOH.edu ", "test-passphrase") is None
    assert ks.check_operator("bomholmm@miamioh.edu", "test-passphrase") is None


def test_an_email_not_on_the_list_is_refused(creds):
    why = ks.check_operator("stranger@miamioh.edu", "test-passphrase")
    assert why and "not on the operator list" in why


def test_the_wrong_passphrase_is_refused(creds):
    why = ks.check_operator("qum@miamioh.edu", "nope")
    assert why == "Wrong passphrase."


def test_a_blank_email_is_refused(creds):
    assert ks.check_operator("", "test-passphrase")
    assert ks.check_operator("   ", "test-passphrase")


def test_an_unconfigured_allowlist_locks_everyone_out(monkeypatch):
    """Fail closed. Safe only because the flag is a FILE -- an operator with
    a shell can still touch data/SERVICE_PAUSED during an incident, and the
    message says so."""
    monkeypatch.delenv("SERVICE_PAUSE_OPERATORS", raising=False)
    monkeypatch.setenv("SERVICE_PAUSE_PASSWORD", "test-passphrase")
    why = ks.check_operator("qum@miamioh.edu", "test-passphrase")
    assert why and "SERVICE_PAUSED" in why


def test_an_unconfigured_passphrase_locks_everyone_out(monkeypatch):
    monkeypatch.setenv("SERVICE_PAUSE_OPERATORS", "qum@miamioh.edu")
    monkeypatch.delenv("SERVICE_PAUSE_PASSWORD", raising=False)
    why = ks.check_operator("qum@miamioh.edu", "")
    assert why and "SERVICE_PAUSED" in why


def test_an_empty_passphrase_never_matches_an_unset_one(monkeypatch):
    """The dangerous shape: unset secret + blank field comparing equal."""
    monkeypatch.setenv("SERVICE_PAUSE_OPERATORS", "qum@miamioh.edu")
    monkeypatch.setenv("SERVICE_PAUSE_PASSWORD", "")
    assert ks.check_operator("qum@miamioh.edu", "") is not None


def test_the_allowlist_tolerates_ragged_configuration(monkeypatch):
    monkeypatch.setenv("SERVICE_PAUSE_OPERATORS",
                       " a@miamioh.edu ,, b@miamioh.edu,")
    assert ks.allowed_operators() == ["a@miamioh.edu", "b@miamioh.edu"]


# --- the routes actually enforce it --------------------------------------
#
# check_operator being right is not the same as the route calling it. The
# failure that matters is a POST that pauses the service anyway.


def _switch_client(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from starlette.testclient import TestClient

    monkeypatch.setattr(ks, "_FLAG_PATH", tmp_path / "SERVICE_PAUSED")
    monkeypatch.setenv("SERVICE_PAUSE_OPERATORS", "qum@miamioh.edu")
    monkeypatch.setenv("SERVICE_PAUSE_PASSWORD", "test-passphrase")
    app = FastAPI()
    app.include_router(ks.build_killswitch_router({"guard": lambda: None}))
    return TestClient(app)


def test_pausing_without_credentials_is_refused_and_changes_nothing(
        tmp_path, monkeypatch):
    c = _switch_client(tmp_path, monkeypatch)
    r = c.post("/admin/service/pause", data={"note": "sneaky"},
               follow_redirects=False)
    assert r.status_code == 403
    assert not ks.is_paused(), "the service must still be up"


def test_pausing_with_a_stranger_email_is_refused(tmp_path, monkeypatch):
    c = _switch_client(tmp_path, monkeypatch)
    r = c.post("/admin/service/pause",
               data={"email": "stranger@miamioh.edu",
                     "password": "test-passphrase"},
               follow_redirects=False)
    assert r.status_code == 403
    assert not ks.is_paused()


def test_pausing_with_a_wrong_passphrase_is_refused(tmp_path, monkeypatch):
    c = _switch_client(tmp_path, monkeypatch)
    r = c.post("/admin/service/pause",
               data={"email": "qum@miamioh.edu", "password": "guess"},
               follow_redirects=False)
    assert r.status_code == 403
    assert not ks.is_paused()


def test_a_refusal_never_echoes_the_passphrase_back(tmp_path, monkeypatch):
    c = _switch_client(tmp_path, monkeypatch)
    r = c.post("/admin/service/pause",
               data={"email": "qum@miamioh.edu",
                     "password": "hunter2-should-not-appear"},
               follow_redirects=False)
    assert "hunter2-should-not-appear" not in r.text


def test_a_listed_operator_can_pause_and_the_log_records_who(
        tmp_path, monkeypatch):
    c = _switch_client(tmp_path, monkeypatch)
    r = c.post("/admin/service/pause",
               data={"email": "  QUM@miamioh.edu ",
                     "password": "test-passphrase",
                     "note": "bad hours answer"},
               follow_redirects=False)
    assert r.status_code == 303
    assert ks.is_paused()
    flagged = ks.pause_reason()
    assert "qum@miamioh.edu" in flagged, "the operator is on the record"
    assert "bad hours answer" in flagged


def test_resuming_needs_the_same_credentials(tmp_path, monkeypatch):
    """Putting a misbehaving bot BACK is as consequential as stopping it;
    gating only the stop leaves the control half-open."""
    c = _switch_client(tmp_path, monkeypatch)
    ks.pause(who="qum@miamioh.edu", note="incident")
    assert ks.is_paused()

    r = c.post("/admin/service/resume", follow_redirects=False)
    assert r.status_code == 403
    assert ks.is_paused(), "an uncredentialled POST must not restore service"

    r = c.post("/admin/service/resume",
               data={"email": "qum@miamioh.edu", "password": "test-passphrase"},
               follow_redirects=False)
    assert r.status_code == 303
    assert not ks.is_paused()


def test_the_page_asks_for_both_credentials_in_both_states(
        tmp_path, monkeypatch):
    c = _switch_client(tmp_path, monkeypatch)
    up = c.get("/admin/service?key=k").text
    assert 'name="email"' in up and 'name="password"' in up

    ks.pause(who="qum@miamioh.edu", note="x")
    down = c.get("/admin/service?key=k").text
    assert 'name="email"' in down and 'name="password"' in down
