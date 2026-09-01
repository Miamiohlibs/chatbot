"""Tests for cross-origin access to /health/ready.

The thing these are really guarding is a NEGATIVE: that granting Ken's page
a cross-origin read of /health/ready did not also hand any miamioh.edu page
a credentialed read of /admin/*. Most of the file is that boundary.
"""
from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_AI_CORE = _HERE.parent.parent
sys.path.insert(0, str(_AI_CORE))

import pytest  # noqa: E402

fastapi = pytest.importorskip("fastapi")
from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src.api.health_cors import (  # noqa: E402
    HealthCorsMiddleware,
    is_cors_path,
    origin_allowed,
)

MIAMI = "https://www.lib.miamioh.edu"


def _app(*, credentialed_origin: str = "https://chatbot.lib.miamioh.edu"):
    """The real shape: an app-wide CREDENTIALED CORS layer, with the
    health layer registered after it so it ends up outermost."""
    app = FastAPI()

    @app.get("/health/ready")
    async def ready():
        return {"status": "healthy"}

    @app.get("/health")
    async def health():
        return {"status": "healthy", "probes": "six external calls"}

    @app.get("/health/live")
    async def live():
        return {"status": "alive"}

    @app.get("/admin/conversations")
    async def admin():
        return {"secret": "patron transcripts"}

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[credentialed_origin],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(HealthCorsMiddleware)
    return TestClient(app)


# --- the boundary that matters -------------------------------------------

def test_a_miami_page_cannot_read_admin_cross_origin():
    """The whole reason this middleware is path-scoped. /admin/* carries
    the mu_admin_sso cookie and shows raw patron conversations."""
    r = _app().get("/admin/conversations", headers={"Origin": MIAMI})
    assert "access-control-allow-origin" not in r.headers


def test_health_never_answers_with_allow_credentials():
    """The app-wide layer sets this header. On a public endpoint it implies
    a contract we do not want, so it is stripped."""
    r = _app().get("/health/ready", headers={"Origin": MIAMI})
    assert r.headers["access-control-allow-origin"] == MIAMI
    assert "access-control-allow-credentials" not in r.headers


def test_the_widget_origin_keeps_its_credentialed_access_elsewhere():
    """Scoping health CORS must not have cost the real frontend anything."""
    own = "https://chatbot.lib.miamioh.edu"
    r = _app().get("/admin/conversations", headers={"Origin": own})
    assert r.headers["access-control-allow-origin"] == own
    assert r.headers["access-control-allow-credentials"] == "true"


# --- origins --------------------------------------------------------------

@pytest.mark.parametrize("origin", [
    "https://miamioh.edu",
    "https://lib.miamioh.edu",
    "https://www.lib.miamioh.edu",
    "https://new.lib.miamioh.edu",
])
def test_miami_https_origins_allowed(origin):
    assert origin_allowed(origin)


@pytest.mark.parametrize("origin", [
    "https://miamioh.edu.evil.com",   # anchoring: suffix attack
    "https://notmiamioh.edu",
    "http://www.lib.miamioh.edu",     # http downgrade
    "https://miamioh.edu:8080",       # port is a different origin
    "null",
    "",
])
def test_hostile_or_odd_origins_refused(origin):
    assert not origin_allowed(origin)


def test_localhost_is_off_unless_explicitly_enabled(monkeypatch):
    """It used to ride on NODE_ENV, which production sets to
    "development" -- so production was allowing http://localhost."""
    monkeypatch.delenv("CORS_ALLOW_LOCALHOST", raising=False)
    assert not origin_allowed("http://localhost:5173")
    monkeypatch.setenv("CORS_ALLOW_LOCALHOST", "true")
    assert origin_allowed("http://localhost:5173")
    assert origin_allowed("http://127.0.0.1:3000")


# --- paths ----------------------------------------------------------------

@pytest.mark.parametrize("path,expected", [
    ("/health/ready", True),
    ("/health/ready/", True),     # FastAPI redirects; the browser follows
    ("/health", False),           # six external probes per call
    ("/health/live", False),
    ("/health/service", False),
    ("/healthcheck", False),
    ("/healthz", False),
    ("/admin/health", False),
    ("/", False),
])
def test_only_health_ready_is_open(path, expected):
    """One path, not the /health/ prefix. Ken asked for /health/ready."""
    assert is_cors_path(path) is expected


def test_the_heavy_health_endpoint_stays_closed():
    """/health fans out to six external probes. A browser polling loop
    must not be able to drive it cross-origin."""
    r = _app().get("/health", headers={"Origin": MIAMI})
    assert "access-control-allow-origin" not in r.headers


def test_health_live_stays_closed_too():
    """Nobody asked for it. Opening endpoints "while we are here" is how
    the surface grows without anyone deciding to grow it."""
    r = _app().get("/health/live", headers={"Origin": MIAMI})
    assert "access-control-allow-origin" not in r.headers


# --- preflight ------------------------------------------------------------

def test_preflight_is_answered_before_the_credentialed_layer_rejects_it():
    """CORSMiddleware answers OPTIONS itself and 400s an unknown origin.
    If it saw this first, Ken's fetch would fail at preflight."""
    r = _app().options("/health/ready", headers={
        "Origin": MIAMI,
        "Access-Control-Request-Method": "GET",
    })
    assert r.status_code == 204
    assert r.headers["access-control-allow-origin"] == MIAMI
    assert "GET" in r.headers["access-control-allow-methods"]


def test_preflight_from_a_stranger_is_refused():
    r = _app().options("/health/ready", headers={
        "Origin": "https://evil.example",
        "Access-Control-Request-Method": "GET",
    })
    assert r.status_code == 403
    assert "access-control-allow-origin" not in r.headers


def test_a_plain_request_with_no_origin_is_untouched():
    """curl, the watchdog, uptime probes -- none send Origin."""
    r = _app().get("/health/ready")
    assert r.status_code == 200
    assert "access-control-allow-origin" not in r.headers


def test_response_varies_on_origin():
    """Otherwise a shared cache can serve one origin's headers to another."""
    r = _app().get("/health/ready", headers={"Origin": MIAMI})
    assert "origin" in r.headers.get("vary", "").lower()
