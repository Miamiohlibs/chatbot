"""Tests for Miami SSO on the admin dashboard.

These are written against the failure modes that actually matter for a lock:
a forged cookie, an expired one, one belonging to somebody who has since
been removed, an assertion with no usable username, and an open redirect on
the login endpoint. A test that only proves "a valid login works" would pass
on a door that never closes.
"""

import time

import pytest

from src.api.admin.sso import (
    SSOConfig,
    display_name_from_attributes,
    is_allowed,
    issue_session,
    read_session,
    safe_next,
    saml_settings,
    uid_from_attributes,
)

SECRET = "x" * 40
UIDS = frozenset({"qum", "bomholmm", "maderir", "irwinkr", "yarnete"})


def cfg(**over) -> SSOConfig:
    base = dict(
        enabled=True,
        base_url="https://chatbot.lib.miamioh.edu",
        sp_entity_id="https://chatbot.lib.miamioh.edu/admin/sso/metadata",
        idp_entity_id="urn:mace:incommon:muohio.edu",
        idp_sso_url="https://muidp.miamioh.edu/idp/profile/SAML2/Redirect/SSO",
        idp_cert="MIIDcert",
        allowed_uids=UIDS,
        session_secret=SECRET,
        session_hours=8,
    )
    base.update(over)
    return SSOConfig(**base)


# --- the whitelist ---------------------------------------------------------


def test_all_five_operators_are_allowed():
    c = cfg()
    for uid in ("qum", "bomholmm", "maderir", "irwinkr", "yarnete"):
        assert is_allowed(uid, c), uid


def test_a_valid_miami_account_not_on_the_list_is_refused():
    # The whole point: authentication is not authorisation. Somebody with a
    # perfectly good Miami login is still not an operator.
    assert not is_allowed("wardtd", cfg())


def test_uid_match_ignores_case():
    assert is_allowed("QUM", cfg())


def test_empty_whitelist_lets_nobody_in():
    assert not is_allowed("qum", cfg(allowed_uids=frozenset()))


# --- reading the uid out of an assertion -----------------------------------


def test_uid_read_from_the_oid_form_shibboleth_sends():
    attrs = {"urn:oid:0.9.2342.19200300.100.1.1": ["qum"]}
    assert uid_from_attributes(attrs) == "qum"


def test_uid_read_from_a_friendly_name():
    assert uid_from_attributes({"uid": ["bomholmm"]}) == "bomholmm"


def test_uid_falls_back_to_the_local_part_of_eppn():
    # Miami releases eppn in every sample assertion in docs/SSO.pdf. If the
    # release policy omits bare uid, this is what keeps the door open.
    attrs = {"urn:oid:1.3.6.1.4.1.5923.1.1.1.6": ["maderir@miamioh.edu"]}
    assert uid_from_attributes(attrs) == "maderir"


def test_uid_falls_back_to_mail_last():
    attrs = {"urn:oid:0.9.2342.19200300.100.1.3": ["irwinkr@miamioh.edu"]}
    assert uid_from_attributes(attrs) == "irwinkr"


def test_uid_prefers_uid_over_eppn_when_both_are_released():
    attrs = {
        "urn:oid:0.9.2342.19200300.100.1.1": ["qum"],
        "urn:oid:1.3.6.1.4.1.5923.1.1.1.6": ["someoneelse@miamioh.edu"],
    }
    assert uid_from_attributes(attrs) == "qum"


def test_no_usable_attribute_yields_none_rather_than_a_guess():
    assert uid_from_attributes({"urn:oid:2.5.4.4": ["Ward"]}) is None


def test_display_name_is_optional():
    assert display_name_from_attributes({}) == ""
    assert display_name_from_attributes(
        {"urn:oid:2.16.840.1.113730.3.1.241": ["Meng Qu"]}) == "Meng Qu"


# --- the signed session cookie ---------------------------------------------


def test_a_freshly_issued_cookie_reads_back():
    c = cfg()
    assert read_session(issue_session("qum", c), c) == "qum"


def test_a_tampered_payload_is_rejected():
    c = cfg()
    good = issue_session("qum", c)
    body, sig = good.split(".", 1)
    forged = issue_session("wardtd", c).split(".", 1)[0] + "." + sig
    assert read_session(forged, c) is None


def test_a_cookie_signed_with_another_secret_is_rejected():
    a, b = cfg(), cfg(session_secret="y" * 40)
    assert read_session(issue_session("qum", a), b) is None


def test_an_expired_cookie_is_rejected():
    c = cfg()
    old = issue_session("qum", c, now=time.time() - (c.session_hours * 3600) - 60)
    assert read_session(old, c) is None


def test_removing_somebody_takes_effect_on_their_next_request():
    # Their cookie is still perfectly signed and unexpired. It must stop
    # working the moment they leave the list, not whenever it happens to
    # lapse -- otherwise revoking access is a promise we cannot keep.
    issued = cfg()
    cookie = issue_session("qum", issued)
    revoked = cfg(allowed_uids=frozenset(UIDS - {"qum"}))
    assert read_session(cookie, revoked) is None


@pytest.mark.parametrize("junk", ["", None, "notacookie", "a.b.c", "...."])
def test_malformed_cookies_are_simply_absent(junk):
    assert read_session(junk, cfg()) is None


def test_no_secret_means_no_session_rather_than_an_unsigned_one():
    assert read_session("anything.at.all", cfg(session_secret="")) is None


# --- open redirect ---------------------------------------------------------


@pytest.mark.parametrize("bad", [
    "https://evil.example/steal",
    "//evil.example/steal",
    "/admin/../../etc/passwd\\x",
    "http://chatbot.lib.miamioh.edu.evil.example/admin/",
    None,
    "",
    "/patron/chat",
])
def test_login_next_never_leaves_the_admin_area(bad):
    assert safe_next(bad) == "/admin/"


def test_a_real_admin_path_is_preserved():
    assert safe_next("/admin/review?filter=thumbs_down") == \
        "/admin/review?filter=thumbs_down"


# --- SAML settings ---------------------------------------------------------


def test_assertions_must_be_signed():
    # An unsigned assertion is one anyone can write.
    assert saml_settings(cfg())["security"]["wantAssertionsSigned"] is True


def test_strict_mode_is_on():
    assert saml_settings(cfg())["strict"] is True


def test_nameid_is_transient_and_the_whitelist_does_not_use_it():
    s = saml_settings(cfg())
    assert s["sp"]["NameIDFormat"].endswith("transient")
    assert s["security"]["wantNameId"] is False


def test_idp_values_match_miamis_published_metadata():
    s = saml_settings(cfg())
    assert s["idp"]["entityId"] == "urn:mace:incommon:muohio.edu"
    assert s["idp"]["singleSignOnService"]["url"].startswith(
        "https://muidp.miamioh.edu/idp/profile/SAML2/")


def test_acs_url_is_https_and_under_admin():
    c = cfg()
    assert c.acs_url == "https://chatbot.lib.miamioh.edu/admin/sso/acs"


# --- config validation -----------------------------------------------------


def test_disabled_sso_reports_no_problems():
    assert cfg(enabled=False, base_url="", idp_cert="",
               allowed_uids=frozenset(), session_secret="").problems() == []


@pytest.mark.parametrize("over,fragment", [
    ({"base_url": "http://insecure.example"}, "https"),
    ({"idp_sso_url": ""}, "SSO_IDP_SSO_URL"),
    ({"idp_cert": ""}, "SSO_IDP_CERT"),
    ({"allowed_uids": frozenset()}, "nobody"),
    ({"session_secret": "short"}, "32 characters"),
])
def test_each_config_fault_is_named(over, fragment):
    problems = cfg(**over).problems()
    assert any(fragment in p for p in problems), problems


def test_a_complete_config_reports_no_problems():
    assert cfg().problems() == []


# --- the guard -------------------------------------------------------------


class _Req:
    def __init__(self, *, cookies=None, headers=None, path="/admin/review",
                 query=""):
        self.cookies = cookies or {}
        self.headers = headers or {}
        self.query_params = {}
        if query:
            for pair in query.split("&"):
                k, _, v = pair.partition("=")
                self.query_params[k] = v

        class _U:
            pass
        self.url = _U()
        self.url.path = path
        self.url.query = query


async def _run(guard, req):
    from fastapi import HTTPException
    try:
        await guard(req)
        return None
    except HTTPException as e:
        return e


@pytest.mark.asyncio
async def test_a_valid_sso_session_is_admitted():
    from src.api.admin.sso import SESSION_COOKIE
    from src.api.admin.sso_router import make_admin_guard
    c = cfg()
    g = make_admin_guard(cfg=c, token="tok")
    req = _Req(cookies={SESSION_COOKIE: issue_session("qum", c)})
    assert await _run(g, req) is None


@pytest.mark.asyncio
async def test_the_token_still_works_while_the_fallback_is_on():
    # This is what stops an IdP outage locking the operator out of the kill
    # switch.
    from src.api.admin.sso_router import make_admin_guard
    g = make_admin_guard(cfg=cfg(allow_token_fallback=True), token="tok")
    assert await _run(g, _Req(headers={"x-admin-token": "tok"})) is None


@pytest.mark.asyncio
async def test_the_token_stops_working_once_the_fallback_is_off():
    from src.api.admin.sso_router import make_admin_guard
    g = make_admin_guard(cfg=cfg(allow_token_fallback=False), token="tok")
    e = await _run(g, _Req(headers={"x-admin-token": "tok"}))
    assert e is not None and e.status_code == 401


@pytest.mark.asyncio
async def test_a_browser_with_no_session_is_sent_to_the_idp():
    from src.api.admin.sso_router import make_admin_guard
    g = make_admin_guard(cfg=cfg(allow_token_fallback=False), token="")
    e = await _run(g, _Req(headers={"accept": "text/html"},
                           path="/admin/review", query="filter=rated"))
    assert e is not None and e.status_code == 307
    loc = e.headers["Location"]
    assert loc.startswith("/admin/sso/login?next=")
    assert "%2Fadmin%2Freview" in loc


@pytest.mark.asyncio
async def test_a_json_caller_with_no_session_gets_401_not_a_redirect():
    from src.api.admin.sso_router import make_admin_guard
    g = make_admin_guard(cfg=cfg(allow_token_fallback=False), token="")
    e = await _run(g, _Req(headers={"accept": "application/json"}))
    assert e is not None and e.status_code == 401


@pytest.mark.asyncio
async def test_a_session_for_a_removed_uid_does_not_open_the_door():
    from src.api.admin.sso import SESSION_COOKIE
    from src.api.admin.sso_router import make_admin_guard
    cookie = issue_session("qum", cfg())
    revoked = cfg(allowed_uids=frozenset(UIDS - {"qum"}),
                  allow_token_fallback=False)
    g = make_admin_guard(cfg=revoked, token="")
    e = await _run(g, _Req(cookies={SESSION_COOKIE: cookie},
                           headers={"accept": "application/json"}))
    assert e is not None and e.status_code == 401


@pytest.mark.asyncio
async def test_with_sso_off_the_guard_is_the_old_token_check():
    from src.api.admin.sso_router import make_admin_guard
    g = make_admin_guard(cfg=cfg(enabled=False), token="tok")
    assert await _run(g, _Req(query="key=tok")) is None
    e = await _run(g, _Req(query="key=wrong"))
    assert e is not None and e.status_code == 401


# --- through a REAL app, not a stub ----------------------------------------
#
# Every guard test above calls `guard(fake_request)` directly. That proves
# the logic and proves nothing about whether FastAPI can WIRE it, which is a
# separate failure with the same symptom: a dashboard that returns 422 to
# everyone. It shipped exactly that way on 2026-08-21, with all 49 unit
# tests green, because `Request` was imported inside the factory and
# `from __future__ import annotations` left FastAPI resolving the name
# against module globals where it did not exist.
#
# These go through TestClient so the wiring is exercised too.


def _app_with_guard(c, token="tok"):
    from fastapi import Depends, FastAPI

    from src.api.admin.sso_router import make_admin_guard

    app = FastAPI()
    g = make_admin_guard(cfg=c, token=token)

    @app.get("/admin/thing")
    async def thing(_u=Depends(g)):
        return {"ok": True}

    from starlette.testclient import TestClient
    return TestClient(app, raise_server_exceptions=False)


def test_a_guarded_route_is_wired_and_never_returns_422():
    # 422 means FastAPI could not resolve the dependency's annotations and
    # treated the Request as a request body. It is the signature of this bug.
    client = _app_with_guard(cfg(allow_token_fallback=False))
    r = client.get("/admin/thing", headers={"accept": "application/json"})
    assert r.status_code != 422, "the guard is mis-wired: Request read as a body"
    assert r.status_code == 401


def test_the_token_opens_a_real_route():
    client = _app_with_guard(cfg(allow_token_fallback=True))
    r = client.get("/admin/thing?key=tok")
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True}


def test_a_real_sso_session_opens_a_real_route():
    from src.api.admin.sso import SESSION_COOKIE
    c = cfg(allow_token_fallback=False)
    client = _app_with_guard(c, token="")
    client.cookies.set(SESSION_COOKIE, issue_session("qum", c))
    r = client.get("/admin/thing")
    assert r.status_code == 200, r.text


def test_a_browser_is_redirected_by_a_real_route():
    client = _app_with_guard(cfg(allow_token_fallback=False), token="")
    r = client.get("/admin/thing", headers={"accept": "text/html"},
                   follow_redirects=False)
    assert r.status_code == 307
    assert r.headers["location"].startswith("/admin/sso/login?next=")
