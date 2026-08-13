"""`/health/service` -- the endpoint that lets the widget SAY the bot is off.

WHY THESE TESTS EXIST
    The kill switch was drilled for the first time on 2026-08-13. It worked:
    zero messages written, zero tokens spent. But the operator's verdict was
    that it was useless to a patron -- the widget looked completely healthy,
    the launcher's three buttons looked live, and the only way to find out
    the bot was out of service was to type a question and read the reply.

    This endpoint is what the widget polls instead. If it regresses, the
    fault is silent in the worst way: the bot goes down and the UI keeps
    claiming everything is fine. So it is tested rather than eyeballed.

WHAT IS DELIBERATELY ASSERTED
    * the operator's EMAIL never appears in the response -- it is in the flag
      file, and this endpoint is public
    * `in_service` and `paused` never contradict each other
    * a broken flag file reads as IN SERVICE, not paused (fail open)
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))


@pytest.fixture()
def ks(tmp_path, monkeypatch):
    """The killswitch module with its flag pointed at a scratch file.

    Re-imported per test because `_FLAG_PATH` is read from the environment at
    import time -- pointing it at tmp_path only works if the module is loaded
    after the env var is set.
    """
    monkeypatch.setenv("SERVICE_PAUSE_FLAG", str(tmp_path / "SERVICE_PAUSED"))
    mod = importlib.import_module("src.api.admin.killswitch_router")
    mod = importlib.reload(mod)
    yield mod
    # Leave the module in its normal state for anything importing it later.
    monkeypatch.delenv("SERVICE_PAUSE_FLAG", raising=False)
    importlib.reload(mod)


def _client(ks_mod):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(ks_mod.build_service_status_router())
    return TestClient(app)


def test_in_service_when_no_flag(ks):
    body = _client(ks).get("/health/service").json()
    assert body["in_service"] is True
    assert body["paused"] is False
    assert body["since"] is None
    assert body["message"] is None


def test_paused_when_flag_present(ks):
    ks.pause(who="qum@miamioh.edu", note="drill")
    body = _client(ks).get("/health/service").json()
    assert body["paused"] is True
    assert body["in_service"] is False
    assert "maintenance" in body["message"].lower()
    # An ISO stamp the client can show; not asserting the exact value.
    assert body["since"] and body["since"].startswith("20")


def test_operator_email_is_never_public(ks):
    """The flag file records WHO paused it. That is an internal record."""
    ks.pause(who="qum@miamioh.edu", note="never leak this")
    raw = _client(ks).get("/health/service").text
    assert "qum@miamioh.edu" not in raw
    assert "never leak this" not in raw
    # ...while still being in the flag file, i.e. the test is meaningful.
    assert "qum@miamioh.edu" in ks.pause_reason()


def test_resume_flips_it_back(ks):
    ks.pause(who="qum@miamioh.edu")
    assert _client(ks).get("/health/service").json()["paused"] is True
    ks.resume(who="qum@miamioh.edu")
    assert _client(ks).get("/health/service").json()["paused"] is False


def test_unreadable_flag_file_reads_as_in_service(ks, monkeypatch):
    """Fail OPEN. A stat that raises must not paint a working bot as down."""
    monkeypatch.setattr(ks, "is_paused", lambda: False)
    body = _client(ks).get("/health/service").json()
    assert body["in_service"] is True


def test_flag_with_no_timestamp_still_reports_paused(ks):
    """Somebody ran `touch data/SERVICE_PAUSED` from a shell.

    The docstring on the module promises that escape hatch works, so an
    empty flag file has to be honoured -- paused, just with no `since`.
    """
    from pathlib import Path as _P

    flag = _P(os.environ["SERVICE_PAUSE_FLAG"])
    flag.parent.mkdir(parents=True, exist_ok=True)
    flag.write_text("", encoding="utf-8")
    body = _client(ks).get("/health/service").json()
    assert body["paused"] is True
    assert body["since"] == ""


def test_ask_us_url_matches_the_one_in_the_paused_message(ks):
    """One URL, two places. They must not drift apart."""
    ks.pause(who="qum@miamioh.edu")
    body = _client(ks).get("/health/service").json()
    assert body["ask_us_url"] in body["message"]
    assert body["ask_us_url"].startswith("https://www.lib.miamioh.edu/")
