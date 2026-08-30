"""The kill switch must stay reachable when SSO is not.

These tests exist because the failure they guard against is silent. If
somebody later mounts this router inside the admin block again "for
consistency", nothing breaks in an obvious way -- until the day the IdP is
down, the bot is misbehaving, and the one control that was supposed to stop
it asks for a login it cannot get.
"""

import os

import pytest

from src.api.admin.killswitch_router import (
    attempt_key,
    build_killswitch_router,
    note_failed_attempt,
    reset_attempts,
)


class _Headers(dict):
    def get(self, k, default=None):  # case-insensitive, like Starlette's
        return super().get(k.lower(), default)


class _Req:
    def __init__(self, headers=None, peer=None):
        self.headers = _Headers({k.lower(): v for k, v in (headers or {}).items()})

        class _C:
            host = peer
        self.client = _C() if peer else None


# --- it stands alone -------------------------------------------------------


def test_the_router_builds_with_no_guard_at_all():
    # `{}` is how main.py mounts it. If this ever needs a guard again, the
    # kill switch has been put back behind the thing it must outlive.
    router = build_killswitch_router({})
    paths = {getattr(r, "path", "") for r in router.routes}
    assert "/admin/service" in paths
    assert "/admin/service/pause" in paths
    assert "/admin/service/resume" in paths


def test_a_guard_is_still_accepted_for_deployments_that_want_one():
    async def _g() -> None:
        return None
    router = build_killswitch_router({"guard": _g})
    assert any(getattr(r, "path", "") == "/admin/service" for r in router.routes)


def test_main_mounts_the_kill_switch_outside_the_admin_block():
    """Read from source, so the test fails if the mount MOVES.

    Asserting on behaviour would not catch this: a kill switch mounted
    inside the admin block behaves identically right up until SSO is on and
    broken, which is exactly when no test is running.
    """
    import pathlib
    src = pathlib.Path(__file__).resolve().parents[2] / "main.py"
    text = src.read_text(encoding="utf-8")

    mount = text.index("app.include_router(build_killswitch_router(")
    # The block itself, not the line that reads the token. The switch now
    # asks the SSO config who is calling -- only to decide whether the
    # passphrase is still worth asking for, never whether to answer -- so
    # that read sits above the mount, and using it as the marker made this
    # test fail on a change that did exactly what it is here to protect.
    admin_block = text.index("if _admin_token or _sso_cfg.enabled:")
    assert mount < admin_block, (
        "build_killswitch_router is mounted after the admin/SSO block began "
        "-- it must be mounted standalone, before it."
    )


def test_the_flag_file_escape_hatch_is_still_documented():
    # The last resort when every web surface is unreachable. If this line
    # goes, the runbook's final fallback has gone with it.
    import pathlib
    src = pathlib.Path(__file__).resolve().parent / "killswitch_router.py"
    text = src.read_text(encoding="utf-8")
    assert "SERVICE_PAUSED" in text
    assert "needs no web page" in text or "without this router" in text


# --- the throttle that replaced the removed guard --------------------------


def test_five_failures_are_allowed_then_the_sixth_is_throttled():
    key = "test-addr-1"
    reset_attempts(key)
    assert [note_failed_attempt(key) for _ in range(5)] == [True] * 5
    assert note_failed_attempt(key) is False


def test_addresses_are_throttled_independently():
    reset_attempts("a"), reset_attempts("b")
    for _ in range(5):
        note_failed_attempt("a")
    assert note_failed_attempt("a") is False
    assert note_failed_attempt("b") is True


def test_a_successful_switch_clears_the_counter():
    # An operator who mistypes twice and then gets it right must not be four
    # failures away from being locked out of their own kill switch.
    key = "test-addr-2"
    reset_attempts(key)
    note_failed_attempt(key)
    note_failed_attempt(key)
    reset_attempts(key)                      # what the handler does on success
    assert [note_failed_attempt(key) for _ in range(5)] == [True] * 5


# --- which address the throttle counts against -----------------------------


def test_the_throttle_key_comes_from_x_real_ip():
    assert attempt_key(_Req({"X-Real-IP": "203.0.113.7"})) == "203.0.113.7"


def test_x_forwarded_for_is_ignored_because_it_is_forgeable():
    # Proven forgeable through the real nginx path on 2026-08-12. Keying a
    # throttle on a value the attacker supplies is not a throttle.
    r = _Req({"X-Forwarded-For": "1.2.3.4", "X-Real-IP": "203.0.113.7"})
    assert attempt_key(r) == "203.0.113.7"


def test_x_forwarded_for_alone_does_not_become_the_key():
    r = _Req({"X-Forwarded-For": "1.2.3.4"}, peer="10.0.0.9")
    assert attempt_key(r) == "10.0.0.9"


def test_the_peer_address_is_the_fallback():
    assert attempt_key(_Req({}, peer="10.0.0.9")) == "10.0.0.9"


def test_a_request_with_nothing_identifiable_still_gets_a_key():
    # It must not crash, and every such caller must share one bucket rather
    # than each getting a fresh quota.
    assert attempt_key(_Req({})) == "unknown"
    assert attempt_key(None) == "unknown"


# --- end to end through the real app -------------------------------------


@pytest.fixture
def client(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from starlette.testclient import TestClient

    monkeypatch.setenv("SERVICE_PAUSE_FLAG", str(tmp_path / "SERVICE_PAUSED"))
    monkeypatch.setenv("SERVICE_PAUSE_OPERATORS", "qum@miamioh.edu")
    monkeypatch.setenv("SERVICE_PAUSE_PASSWORD", "correct horse")
    import importlib

    import src.api.admin.killswitch_router as ks
    importlib.reload(ks)
    app = FastAPI()
    app.include_router(ks.build_killswitch_router({}))
    return TestClient(app), ks


def test_the_page_opens_with_no_session_and_no_token(client):
    c, _ = client
    assert c.get("/admin/service").status_code == 200


def test_an_operator_can_stop_the_bot_with_no_session_and_no_token(client):
    c, ks = client
    assert not ks.is_paused()
    r = c.post("/admin/service/pause",
               data={"email": "qum@miamioh.edu", "password": "correct horse",
                     "note": "idp is down and the bot is wrong"},
               follow_redirects=False)
    assert r.status_code == 303
    assert ks.is_paused()
    assert "idp is down" in ks.pause_reason()


def test_a_stranger_still_cannot_stop_it(client):
    c, ks = client
    r = c.post("/admin/service/pause",
               data={"email": "someone@example.com", "password": "correct horse"})
    assert r.status_code == 403
    assert not ks.is_paused()


def test_repeated_guessing_is_throttled_end_to_end(client):
    c, ks = client
    codes = []
    for _ in range(7):
        r = c.post("/admin/service/pause",
                   data={"email": "qum@miamioh.edu", "password": "wrong"},
                   headers={"X-Real-IP": "198.51.100.5"})
        codes.append(r.status_code)
    assert codes[:5] == [403] * 5
    assert codes[5] == 429 and codes[6] == 429
    assert not ks.is_paused()
