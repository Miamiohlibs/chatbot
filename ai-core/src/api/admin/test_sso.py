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
    """The guard's answer: a Caller when it admits, the HTTPException when
    it does not. It used to return None on success -- it returns who the
    caller is now, because the console has two roles to draw for and every
    dangerous action has a name to write down."""
    from fastapi import HTTPException
    try:
        return await guard(req)
    except HTTPException as e:
        return e


@pytest.mark.asyncio
async def test_a_valid_sso_session_is_admitted():
    from src.api.admin.sso import SESSION_COOKIE
    from src.api.admin.sso_router import make_admin_guard
    c = cfg()
    g = make_admin_guard(cfg=c, token="tok")
    req = _Req(cookies={SESSION_COOKIE: issue_session("qum", c)})
    who = await _run(g, req)
    assert who.uid == "qum"
    assert who.authenticated
    assert who.is_operator, "the pre-roles allowlist has always meant operator"


@pytest.mark.asyncio
async def test_the_token_still_works_while_the_fallback_is_on():
    # This is what stops an IdP outage locking the operator out of the kill
    # switch.
    from src.api.admin.sso_router import make_admin_guard
    g = make_admin_guard(cfg=cfg(allow_token_fallback=True), token="tok")
    who = await _run(g, _Req(headers={"x-admin-token": "tok"}))
    assert who.is_operator, "the emergency key opens the whole console"
    assert not who.authenticated, "...but it does not establish a name"


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
    assert (await _run(g, _Req(query="key=tok"))).is_operator
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


def test_metadata_advertises_no_endpoint_that_does_not_exist():
    """Everything in the published metadata must be a route we serve.

    The first draft advertised /admin/sso/sls, which 404'd. Miami IT
    configures their side FROM this document, so a phantom endpoint becomes
    their configuration and fails in production later.
    """
    from onelogin.saml2.settings import OneLogin_Saml2_Settings

    xml = OneLogin_Saml2_Settings(
        saml_settings(cfg()), sp_validation_only=True).get_sp_metadata()
    xml = xml.decode() if isinstance(xml, bytes) else xml

    import re
    advertised = set(re.findall(r'Location="https://[^"]*(/admin/sso/[\w-]+)"', xml))

    from src.api.admin.sso_router import build_sso_router
    served = {getattr(r, "path", "") for r in build_sso_router(cfg()).routes}

    missing = {p for p in advertised if p not in served}
    assert not missing, f"metadata advertises unserved endpoint(s): {missing}"


def test_single_logout_is_not_advertised():
    from onelogin.saml2.settings import OneLogin_Saml2_Settings
    xml = OneLogin_Saml2_Settings(
        saml_settings(cfg()), sp_validation_only=True).get_sp_metadata()
    xml = xml.decode() if isinstance(xml, bytes) else xml
    assert "SingleLogoutService" not in xml


def test_metadata_still_builds_with_no_contact_email(monkeypatch):
    # An optional courtesy field must never be able to take out the login.
    monkeypatch.delenv("SSO_CONTACT_EMAIL", raising=False)
    from onelogin.saml2.settings import OneLogin_Saml2_Settings
    s = OneLogin_Saml2_Settings(saml_settings(cfg()), sp_validation_only=True)
    assert s.get_sp_metadata()


def test_the_metadata_does_not_expire():
    """python3-saml defaults validUntil to now + 2 days and recomputes it
    on every request, so this endpoint was handing Miami IT a document
    that expired within 48 hours of being fetched. For an IdP that saves a
    static copy -- which is how this integration is being set up -- that
    is a login that stops working on a date nobody wrote down, with no
    warning until the day it happens.

    It also disagreed with its own cacheDuration: cache for a week, expire
    in two days.

    Asked for by Miami IT, 2026-08-27.
    """
    import os

    from src.api.admin import sso

    for k, v in {
        "SSO_BASE_URL": "https://chatbot.lib.miamioh.edu",
        "SSO_IDP_ENTITY_ID": "https://idp.example.edu/idp",
        "SSO_IDP_SSO_URL": "https://idp.example.edu/idp/SSO",
        "SSO_IDP_CERT": "MIIBfake",
    }.items():
        os.environ.setdefault(k, v)

    cfg = sso.load_config()
    settings = sso.saml_settings(cfg)
    assert settings["security"]["metadataValidUntil"] == "", (
        "an empty string omits the attribute; None restores the 2-day default"
    )


# --- two audiences ---------------------------------------------------------
#
# One console served two jobs. A subject librarian wants the questions
# students asked and a way to report a wrong answer; nobody on the library
# staff needs the spend ladder, the kill switch, or a button that rebuilds
# the index for seven minutes.

from src.api.admin.sso import (  # noqa: E402
    Caller, ROLE_LIBRARIAN, ROLE_OPERATOR, load_config, role_for,
)


def _roles(**over):
    return cfg(**over)


def test_an_operator_gets_the_operator_role():
    assert role_for("qum", _roles(operator_uids=frozenset({"qum"}))) \
        == ROLE_OPERATOR


def test_a_librarian_gets_the_librarian_role():
    assert role_for("wardtd", _roles(librarian_uids=frozenset({"wardtd"}))) \
        == ROLE_LIBRARIAN


def test_somebody_on_neither_list_gets_no_role():
    assert role_for("stranger", _roles(allowed_uids=frozenset())) is None


def test_operator_wins_when_somebody_is_on_both_lists():
    """Adding yourself to the librarian list to see what librarians see must
    not quietly cost you the kill switch -- you would find out during an
    incident."""
    c = _roles(operator_uids=frozenset({"qum"}),
               librarian_uids=frozenset({"qum"}))
    assert role_for("qum", c) == ROLE_OPERATOR


def test_the_old_single_list_still_means_operator():
    """SSO_ALLOWED_UIDS granted the whole console before roles existed, and
    it is what is in .env today. Upgrading must not lock out five people."""
    c = _roles(allowed_uids=frozenset({"qum"}),
               operator_uids=frozenset(), librarian_uids=frozenset())
    assert role_for("qum", c) == ROLE_OPERATOR


def test_the_role_lists_merge_rather_than_one_winning(monkeypatch):
    monkeypatch.setenv("SSO_ALLOWED_UIDS", "qum")
    monkeypatch.setenv("SSO_OPERATOR_UIDS", "bomholmm")
    monkeypatch.setenv("SSO_LIBRARIAN_UIDS", "wardtd, yarnete")
    c = load_config()
    assert c.operator_uids == frozenset({"qum", "bomholmm"})
    assert c.librarian_uids == frozenset({"wardtd", "yarnete"})
    assert "wardtd" in c.allowed_uids, "a librarian must be able to sign in"


def test_a_librarian_may_not_do_operator_things():
    who = Caller(role=ROLE_LIBRARIAN, uid="wardtd", via="sso")
    assert who.may(ROLE_LIBRARIAN)
    assert not who.may(ROLE_OPERATOR)


def test_an_operator_may_do_librarian_things():
    who = Caller(role=ROLE_OPERATOR, uid="qum", via="sso")
    assert who.may(ROLE_LIBRARIAN) and who.may(ROLE_OPERATOR)


def test_the_shared_key_is_never_a_name():
    """It opens the console -- it is our emergency key -- but a log line
    naming whoever typed it in a box is not evidence of anything."""
    who = Caller(role=ROLE_OPERATOR, via="token")
    assert who.is_operator
    assert not who.authenticated
    assert "unauthenticated" in who.display


@pytest.mark.asyncio
async def test_a_librarian_reaching_an_operator_page_is_told_why():
    """Not a bare 403. They clicked a link, and "Forbidden" invites them to
    conclude the console is broken."""
    from src.api.admin.sso import SESSION_COOKIE
    from src.api.admin.sso_router import make_admin_guard

    c = cfg(allowed_uids=frozenset({"wardtd"}),
            librarian_uids=frozenset({"wardtd"}))
    g = make_admin_guard(cfg=c, token="tok", require=ROLE_OPERATOR)
    e = await _run(g, _Req(cookies={SESSION_COOKIE: issue_session("wardtd", c)}))
    assert e.status_code == 403
    assert "/librarian/" in e.detail
    assert "wardtd" in e.detail


@pytest.mark.asyncio
async def test_a_librarian_is_admitted_to_a_librarian_page():
    from src.api.admin.sso import SESSION_COOKIE
    from src.api.admin.sso_router import make_admin_guard

    c = cfg(allowed_uids=frozenset({"wardtd"}),
            librarian_uids=frozenset({"wardtd"}))
    g = make_admin_guard(cfg=c, token="tok", require=ROLE_LIBRARIAN)
    who = await _run(g, _Req(cookies={SESSION_COOKIE: issue_session("wardtd", c)}))
    assert who.uid == "wardtd" and who.authenticated
    assert not who.is_operator


# --- the sidebar signature, everywhere -----------------------------------

def test_the_shell_signs_itself_for_a_signed_in_caller():
    from src.api.admin import admin_ui as ui

    body = ui.page("x", "y", who=Caller(role=ROLE_OPERATOR, uid="qum",
                                        via="sso"))
    assert "Signed in as" in body and "qum" in body
    assert "/admin/sso/logout" in body


def test_the_shell_says_when_the_caller_is_only_a_key():
    """Which console mode you are in decides whether the next dangerous
    action asks for a passphrase. Deducing that from whether a password
    box appeared is not a design."""
    from src.api.admin import admin_ui as ui

    body = ui.page("x", "y", who=Caller(role=ROLE_OPERATOR, via="token"))
    assert "shared key" in body
    assert "passphrase" in body


def test_every_operator_surface_passes_the_caller_to_the_shell():
    """Read from source, because the failure is silent.

    A page that renders the shell without `who` still works -- it just
    draws a sidebar with no signature on it, so the console tells you who
    you are on six pages and not on the seventh. That is exactly the kind
    of inconsistency this whole rebuild was about.

    `chrome=False` is the deliberate exception: pages shared outside the
    group get no sidebar at all, so there is nothing to sign.
    """
    import pathlib
    import re

    here = pathlib.Path(__file__).resolve().parent
    offenders = []
    for path in sorted(here.glob("*_router.py")):
        text = path.read_text(encoding="utf-8")
        # Each ui.page( / admin_ui.page( call, up to its closing paren.
        for m in re.finditer(r"\b(?:ui|admin_ui)\.page\(", text):
            i, depth = m.end(), 1
            while depth and i < len(text):
                depth += (text[i] == "(") - (text[i] == ")")
                i += 1
            call = text[m.end():i]
            if "who=" not in call and "chrome=False" not in call:
                line = text[:m.start()].count("\n") + 1
                offenders.append(f"{path.name}:{line}")
    assert not offenders, (
        "these render the console shell without saying who is looking: "
        + ", ".join(offenders))


# --- light / dark --------------------------------------------------------

def test_the_theme_choice_is_applied_before_anything_paints():
    """In <head> and inline. The alternative is the page rendering in the
    system theme and then flipping -- a flash on every navigation, on every
    page, for the reader who chose the other one."""
    from src.api.admin import admin_ui as ui

    body = ui.page("x", "y")
    head = body[:body.index("</head>")]
    assert "localStorage.getItem('mu-admin-theme')" in head
    assert "data-theme" in head


def test_reading_the_stored_theme_can_never_break_the_page():
    """localStorage throws outright in some privacy modes. A console that
    will not render because a colour preference could not be read is worse
    than one that ignores the preference."""
    from src.api.admin import admin_ui as ui

    head = ui.page("x", "y").split("</head>")[0]
    boot = head[head.index("localStorage") - 200:]
    assert "try{" in boot and "catch(e){}" in boot


def test_the_stylesheet_answers_all_three_theme_states():
    """Three, not two: an explicit choice stamps data-theme on the root,
    and the default 'follow my system' stamps nothing. A media query alone
    cannot serve a reader who picked dark on a light machine -- which is
    exactly what the toggle does."""
    from src.api.admin import admin_ui as ui

    assert "@media (prefers-color-scheme: dark)" in ui.STYLE
    assert ':root:not([data-theme="light"])' in ui.STYLE
    assert ':root[data-theme="dark"]{' in ui.STYLE


def test_the_two_dark_blocks_carry_the_same_tokens():
    """They are written twice because CSS cannot share a block. A token
    that lands in one and not the other is a theme that half applies."""
    import re

    from src.api.admin import admin_ui as ui

    def tokens(block: str) -> set:
        return set(re.findall(r"(--[a-z-]+):\s*([^;]+);", block))

    media = ui.STYLE.split('@media (prefers-color-scheme: dark){')[1]
    media = media.split(":root:not([data-theme=\"light\"]){")[1].split("\n  }")[0]
    explicit = ui.STYLE.split(':root[data-theme="dark"]{')[1].split("\n}")[0]
    assert tokens(media) == tokens(explicit)


def test_the_switch_is_hidden_until_its_own_script_shows_it():
    """No JavaScript, no control -- it would be a button that does
    nothing. The page still follows the system theme there."""
    from src.api.admin import admin_ui as ui

    body = ui.page("x", "y")
    assert "id='theme-switch' role='group' hidden" in body
    assert "g.hidden=false" in body


def test_both_themes_are_on_screen_at_once():
    """The first version showed one icon and the name of the theme you
    were in. It looked exactly like a nav item, and the operator read the
    whole sidebar and reported there was no toggle -- with it on screen.
    Reported 2026-08-31. What it is and what it would do have to be the
    same glance."""
    from src.api.admin import admin_ui as ui

    body = ui.page("x", "y")
    assert "data-theme-set='light'" in body
    assert "data-theme-set='dark'" in body
    assert ">Light<" in body and ">Dark<" in body


def test_the_active_theme_is_announced_not_just_drawn():
    """`aria-pressed` on each half, so a screen reader hears which one is
    on rather than being told about a filled background."""
    from src.api.admin import admin_ui as ui

    body = ui.page("x", "y")
    assert "aria-pressed" in body
    assert "aria-pressed" in ui.STYLE, "and the fill follows that state"


def test_the_red_splits_into_a_fill_and_an_ink():
    """One token was doing both jobs and they want opposite things: white
    sitting ON the red wants it dark, the red sitting on the page wants it
    light. Tuned for the text case, the fill was glaring -- reported
    2026-08-31. They agree on white and split in dark."""
    from src.api.admin import admin_ui as ui

    light = ui.STYLE.split(":root{")[1].split("\n}")[0]
    dark = ui.STYLE.split(':root[data-theme="dark"]{')[1].split("\n}")[0]
    assert "--primary-ink:354 72% 42%" in light, "same as the fill on white"
    assert "--primary:354 58% 40%" in dark
    assert "--primary-ink:354 42% 66%" in dark
    # The ink is the LESS saturated of the two in dark mode. That is the
    # whole point: glare is saturation, not contrast.
    assert 42 < 58


def test_the_red_is_never_used_as_text_from_the_fill_token():
    """Every text-role use has to read --primary-ink, or dark mode gets a
    hard-to-read red on a dark ground again."""
    from src.api.admin import admin_ui as ui

    for line in ui.STYLE.splitlines():
        stripped = line.strip()
        if stripped.startswith("border-color") or "border-color:hsl(var(--primary))" in stripped:
            continue
        assert "color:hsl(var(--primary));" not in stripped.replace(
            "border-color:hsl(var(--primary));", ""), stripped


# --- nothing paints outside the token system -----------------------------

def _admin_sources():
    import pathlib
    here = pathlib.Path(__file__).resolve().parent
    for path in sorted(here.glob("*_router.py")):
        # sso_router's refusal page is deliberately standalone: it has to
        # render when the console it belongs to has refused to admit you,
        # so it carries its own colours and its own dark-mode block.
        if path.name == "sso_router.py":
            continue
        yield path, path.read_text(encoding="utf-8")


def _css_blocks(text: str):
    """The strings in a router that end up inside a <style> tag.

    Inline `<style>...</style>` and module-level stylesheet constants.
    Comments explaining the CSS are not CSS.
    """
    import re

    for block in re.findall(r"<style>(.*?)</style>", text, re.S):
        yield block
    for const in re.findall(r"^_STYLE = \((.*?)^\)", text, re.S | re.M):
        yield "\n".join(ln for ln in const.splitlines()
                         if not ln.strip().startswith("#"))


def test_no_router_uses_a_token_the_stylesheet_does_not_define():
    """The stylesheet was rebuilt on 2026-08-30 and the token names
    changed. Three routers kept referring to the old ones from inline
    <style> blocks -- `var(--miami)`, `var(--line)`, `var(--muted)` used
    as a colour -- so those rules silently stopped applying. Nothing threw;
    the page just quietly looked wrong, which is the only way CSS ever
    fails.
    """
    import re

    from src.api.admin import admin_ui as ui

    defined = set(re.findall(r"(--[a-z-]+)\s*:", ui.STYLE))
    bad = []
    for path, text in _admin_sources():
        # Only what actually reaches a browser. Scanning whole files
        # flagged the comments that explain which names went away.
        for block in _css_blocks(text):
            for name in set(re.findall(r"var\((--[a-z-]+)", block)):
                if name not in defined:
                    bad.append(f"{path.name}: var({name})")
    assert not bad, "undefined tokens: " + ", ".join(sorted(bad))


def test_no_router_hardcodes_a_colour_in_an_inline_stylesheet():
    """A hex in an inline style is a colour that cannot follow the theme.
    `.convs tr.needs td{background:#fffaf5}` was a gentle tint in light
    mode and a white block in dark. Reported 2026-08-31.
    """
    import re

    bad = []
    for path, text in _admin_sources():
        for block in _css_blocks(text):
            for hexcode in re.findall(r"#[0-9a-fA-F]{3,8}\b", block):
                bad.append(f"{path.name}: {hexcode}")
    assert not bad, "hardcoded colours: " + ", ".join(sorted(set(bad)))
