"""Miami single sign-on (SAML 2.0 / Shibboleth) for the admin dashboard.

WHY SAML AND NOT CAS
    Miami's identity provider is a Shibboleth IdP in InCommon
    (`urn:mace:incommon:muohio.edu`), documented in docs/SSO.pdf. It speaks
    SAML 2.0. CAS is a different protocol and does not apply here.

WHAT THIS GUARDS
    The admin surfaces only -- /admin/review, /admin/corrections,
    /admin/cost, /admin/tickets, /admin/service. Nothing a patron touches
    goes near this module. The chat widget is unauthenticated by design and
    stays that way.

WHY A WHITELIST AND NOT "ANY MIAMI ACCOUNT"
    A valid Miami login proves you are a member of the university, which is
    tens of thousands of people. These pages show raw conversation logs --
    patron questions, typed verbatim, some of which contain personal
    details. Authentication answers "who are you"; it does not answer "may
    you read this". The whitelist is the second question, and it is keyed on
    uid because the operator listed people that way.

THE TWO-KEY ROLLOUT, AND THE LOCKOUT IT AVOIDS
    The kill switch (/admin/service) lives behind this same guard. If SSO
    were the only way in and the IdP went down -- or a certificate rolled,
    or a uid was mistyped -- nobody could stop the bot while it was
    answering badly. That is a worse failure than a weaker lock.

    So the token keeps working alongside SSO while
    `SSO_ALLOW_TOKEN_FALLBACK` is true (the default). Turn it off once SSO
    has been used successfully by every person on the list, and the token
    becomes dead weight rather than a hole. Turning it off is one env var,
    no deploy.

SESSIONS ARE SIGNED, NOT STORED
    A signed cookie carries {uid, expiry}. No server-side session table,
    because the alternative is another thing to back up and another thing
    that breaks a login when Postgres hiccups. The signature is HMAC-SHA256
    over the payload with `SSO_SESSION_SECRET`; a tampered cookie fails the
    comparison and is treated as absent.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# The cookie name is deliberately boring and scoped to /admin so it is never
# sent with a patron's chat request.
SESSION_COOKIE = "mu_admin_sso"

# TWO PATHS, NOT ONE, AND NOT "/".
#
# The console lives at /admin and the librarian console at /librarian.
# Scoped to /admin alone the cookie is simply never sent to /librarian,
# so a signed-in department head arrives there as a stranger -- which is
# what happened when the librarian console first started accepting a
# session instead of the shared code. Nothing in the sign-in was wrong;
# the browser had just never been told to send it there.
#
# The obvious repair is path "/", and it is the wrong one: the widget is
# served from the same host at /smartchatbot/, so every patron's page
# load and socket handshake would then carry an operator's session
# cookie. It is HttpOnly and Secure and nothing reads it there, but the
# blast radius of a credential is where it travels, not where it is used.
#
# The two prefixes do not overlap, so exactly one is ever sent, and
# neither reaches a patron. Same name and same signed value: the token is
# re-validated against the allowlist on every request either way, so this
# is two deliveries of one credential rather than two credentials.
COOKIE_PATHS = ("/admin", "/librarian")

# The single path the cookie used to have. Kept because deleting a cookie
# requires naming the path it was set on, and a deployment upgrading from
# before 2026-09-01 has live sessions sitting at exactly this one.
COOKIE_PATH = "/admin"

# Attribute OIDs Miami's IdP releases (read off the sample assertions in
# docs/SSO.pdf). Shibboleth sends the OID form; some deployments also send a
# friendly name, so both are accepted rather than assuming one shape.
_UID_KEYS = (
    "urn:oid:0.9.2342.19200300.100.1.1",   # uid
    "uid",
)
_EPPN_KEYS = (
    "urn:oid:1.3.6.1.4.1.5923.1.1.1.6",    # eduPersonPrincipalName
    "eduPersonPrincipalName",
    "eppn",
)
_MAIL_KEYS = (
    "urn:oid:0.9.2342.19200300.100.1.3",   # mail
    "mail",
)
_NAME_KEYS = (
    "urn:oid:2.16.840.1.113730.3.1.241",   # displayName
    "displayName",
)


def _env(name: str, default: str = "") -> str:
    return (os.getenv(name, default) or "").strip()


def _env_bool(name: str, default: bool) -> bool:
    raw = _env(name)
    if not raw:
        return default
    return raw.lower() in ("1", "true", "yes", "on")


def _hours(name: str, default: int) -> int:
    """Never raise on a typo.

    load_config() is read before the kill switch is mounted, because the
    switch asks it who is calling. A ValueError here would therefore stop
    the whole app from importing -- and the one thing the kill switch must
    survive is everything else being misconfigured.
    """
    try:
        return int(_env(name) or default)
    except ValueError:
        logger.error("%s is not a number; using %d", name, default)
        return default


def _uid_set(name: str) -> set:
    """Parse one of the allowlists. Commas or semicolons, case-insensitive."""
    return {
        u.strip().lower()
        for u in _env(name).replace(";", ",").split(",")
        if u.strip()
    }


# --- the two audiences -----------------------------------------------------
#
# One console served two jobs that have nothing to do with each other. A
# subject librarian wants to know what students asked her subject this week
# and to report an answer that was wrong. Nobody on the library staff needs
# the spend ladder, the kill switch, or a button that rebuilds the index for
# seven minutes -- and the conversation list they do need is the real one,
# not ours: most of what is in there is us testing the bot.
#
# So: two roles, and the operator role is a superset. Not a permission
# matrix -- there are five people in this group and a matrix would be five
# people maintaining a table about five people.
ROLE_OPERATOR = "operator"
ROLE_LIBRARIAN = "librarian"

ROLE_LABELS = {
    ROLE_OPERATOR: "operator",
    ROLE_LIBRARIAN: "librarian",
}


@dataclass(frozen=True)
class SSOConfig:
    """Everything the SP needs, read once at startup."""

    enabled: bool = False
    base_url: str = ""
    sp_entity_id: str = ""
    idp_entity_id: str = ""
    idp_sso_url: str = ""
    idp_slo_url: str = ""
    idp_cert: str = ""
    sp_cert: str = ""
    sp_key: str = ""
    allowed_uids: frozenset = field(default_factory=frozenset)
    operator_uids: frozenset = field(default_factory=frozenset)
    librarian_uids: frozenset = field(default_factory=frozenset)
    session_secret: str = ""
    session_hours: int = 8
    allow_token_fallback: bool = True

    @property
    def acs_url(self) -> str:
        return f"{self.base_url}/admin/sso/acs"

    @property
    def sls_url(self) -> str:
        return f"{self.base_url}/admin/sso/sls"

    @property
    def metadata_url(self) -> str:
        return f"{self.base_url}/admin/sso/metadata"

    def problems(self) -> list[str]:
        """Config faults, in the order an operator should fix them.

        Returned rather than raised: a half-configured SP must not stop the
        service from booting, because the chat widget does not depend on it
        and taking the whole bot down over an admin-login setting would be
        the wrong trade.
        """
        out: list[str] = []
        if not self.enabled:
            return out
        if not self.base_url.startswith("https://"):
            out.append("SSO_BASE_URL must be set and start with https://")
        if not self.idp_sso_url:
            out.append("SSO_IDP_SSO_URL is unset")
        if not self.idp_cert:
            out.append("SSO_IDP_CERT is unset (the IdP signing certificate)")
        if not self.allowed_uids:
            out.append("SSO_ALLOWED_UIDS is empty -- nobody could sign in")
        if len(self.session_secret) < 32:
            out.append("SSO_SESSION_SECRET must be at least 32 characters")
        return out


def load_config() -> SSOConfig:
    base = _env("SSO_BASE_URL").rstrip("/")
    # SSO_ALLOWED_UIDS is what the list was called when there was one list,
    # and it is what is in .env today. It keeps meaning "the operators", so
    # nothing breaks by upgrading; SSO_OPERATOR_UIDS is the name to use in
    # new deployments and the two are merged rather than one winning.
    operators = _uid_set("SSO_ALLOWED_UIDS") | _uid_set("SSO_OPERATOR_UIDS")
    librarians = _uid_set("SSO_LIBRARIAN_UIDS")
    # Being on both lists is not an error and is not worth refusing over: an
    # operator is already allowed everything a librarian is, so the operator
    # role simply wins in role_for().
    uids = operators | librarians
    return SSOConfig(
        enabled=_env_bool("SSO_ENABLED", False),
        base_url=base,
        sp_entity_id=_env("SSO_SP_ENTITY_ID") or (f"{base}/admin/sso/metadata" if base else ""),
        idp_entity_id=_env("SSO_IDP_ENTITY_ID", "urn:mace:incommon:muohio.edu"),
        idp_sso_url=_env("SSO_IDP_SSO_URL",
                         "https://muidp.miamioh.edu/idp/profile/SAML2/Redirect/SSO"),
        idp_slo_url=_env("SSO_IDP_SLO_URL",
                         "https://muidp.miamioh.edu/idp/profile/SAML2/Redirect/SLO"),
        idp_cert=_env("SSO_IDP_CERT"),
        sp_cert=_env("SSO_SP_CERT"),
        sp_key=_env("SSO_SP_KEY"),
        allowed_uids=frozenset(uids),
        operator_uids=frozenset(operators),
        librarian_uids=frozenset(librarians),
        session_secret=_env("SSO_SESSION_SECRET"),
        session_hours=_hours("SSO_SESSION_HOURS", 8),
        allow_token_fallback=_env_bool("SSO_ALLOW_TOKEN_FALLBACK", True),
    )


# --- whitelist -------------------------------------------------------------


def uid_from_attributes(attrs: dict) -> str | None:
    """The uid this assertion is about, or None.

    Order matters. `uid` is what the operator's list is written in, so it is
    tried first. eppn is the documented fallback because Miami releases it in
    every sample assertion and its local part IS the uid
    ("wardtd@miamioh.edu" -> "wardtd"); without that fallback a release
    policy that omits bare uid would lock everyone out for no good reason.
    """
    def first(keys):
        for k in keys:
            v = attrs.get(k)
            if isinstance(v, (list, tuple)):
                v = v[0] if v else None
            if v:
                return str(v).strip()
        return None

    uid = first(_UID_KEYS)
    if uid:
        return uid.lower()
    eppn = first(_EPPN_KEYS)
    if eppn:
        return eppn.split("@", 1)[0].strip().lower() or None
    mail = first(_MAIL_KEYS)
    if mail:
        return mail.split("@", 1)[0].strip().lower() or None
    return None


def display_name_from_attributes(attrs: dict) -> str:
    for k in _NAME_KEYS:
        v = attrs.get(k)
        if isinstance(v, (list, tuple)):
            v = v[0] if v else None
        if v:
            return str(v).strip()
    return ""


def is_allowed(uid: str | None, cfg: SSOConfig) -> bool:
    return bool(uid) and uid.lower() in cfg.allowed_uids


@dataclass(frozen=True)
class Caller:
    """Who is making this request, as far as the console can tell.

    WHY THE GUARD RETURNS THIS RATHER THAN None
        Two things need it. The console has to know which role it is
        drawing for, and every dangerous action has to be able to write
        down who did it -- which is only worth writing down if somebody
        else established the name. `via` is that distinction, and it is
        the whole reason a passphrase can be dropped in one case and not
        the other:

          via="sso"    Miami's IdP says this is qum@miamioh.edu. The name
                       in the log is evidence.
          via="token"  Somebody has the shared URL key. The name in the
                       log would be whatever they typed in the box, which
                       is not evidence of anything.

        So `authenticated` gates the passphrase, not `enabled` and not a
        setting. A console with SSO configured but a caller arriving on
        the fallback key is still asked for the passphrase, because that
        caller is still anonymous.
    """

    role: str = ""
    uid: str = ""
    via: str = ""

    @property
    def authenticated(self) -> bool:
        """Somebody other than the caller vouched for this name."""
        return self.via == "sso" and bool(self.uid)

    @property
    def is_operator(self) -> bool:
        return self.role == ROLE_OPERATOR

    @property
    def is_librarian(self) -> bool:
        return self.role in (ROLE_LIBRARIAN, ROLE_OPERATOR)

    def may(self, role: str) -> bool:
        """Operators may do anything a librarian may. Not the reverse."""
        if self.role == ROLE_OPERATOR:
            return True
        return self.role == role

    @property
    def display(self) -> str:
        """What to put on the screen and in the log."""
        if self.authenticated:
            return self.uid
        return "shared key (unauthenticated)"


def role_for(uid: str | None, cfg: SSOConfig) -> "str | None":
    """Which console this person gets, or None if they get neither.

    Operator wins when somebody is on both lists. The alternative -- the
    narrower role winning, or refusing the sign-in -- would mean adding
    yourself to the librarian list to see what librarians see quietly locks
    you out of the kill switch, and you would find out during an incident.
    """
    if not uid:
        return None
    u = uid.lower()
    if u in cfg.operator_uids:
        return ROLE_OPERATOR
    if u in cfg.librarian_uids:
        return ROLE_LIBRARIAN
    # On the old single list and neither of the new ones. That list granted
    # the whole console before roles existed, so operator is what it has
    # always meant -- and reading it here rather than only in load_config()
    # is what stops a config built any other way from locking out everyone
    # who has not been re-sorted into a role yet.
    if u in cfg.allowed_uids:
        return ROLE_OPERATOR
    return None


# --- signed session cookie -------------------------------------------------


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64d(txt: str) -> bytes:
    pad = "=" * (-len(txt) % 4)
    return base64.urlsafe_b64decode(txt + pad)


def issue_session(uid: str, cfg: SSOConfig, *, now: float | None = None) -> str:
    """A signed `payload.signature` string for the cookie value."""
    now = time.time() if now is None else now
    payload = {
        "uid": uid.lower(),
        "iat": int(now),
        "exp": int(now + cfg.session_hours * 3600),
    }
    body = _b64e(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    sig = hmac.new(cfg.session_secret.encode(), body.encode(), hashlib.sha256).digest()
    return f"{body}.{_b64e(sig)}"


def read_session(cookie: str | None, cfg: SSOConfig,
                 *, now: float | None = None) -> str | None:
    """The uid a valid, unexpired, still-whitelisted cookie names, or None.

    Re-checking the whitelist on every request (rather than trusting the
    cookie because it was signed) is what makes removing someone take effect
    immediately. Otherwise a revoked operator keeps their access until the
    session happens to expire.
    """
    if not cookie or not cfg.session_secret:
        return None
    try:
        body, sig = cookie.split(".", 1)
    except ValueError:
        return None
    expected = hmac.new(cfg.session_secret.encode(), body.encode(),
                        hashlib.sha256).digest()
    if not hmac.compare_digest(_b64e(expected), sig):
        return None
    try:
        payload = json.loads(_b64d(body))
    except Exception:  # noqa: BLE001 -- any malformed cookie is simply absent
        return None
    now = time.time() if now is None else now
    if float(payload.get("exp", 0)) < now:
        return None
    uid = str(payload.get("uid") or "").lower()
    if not is_allowed(uid, cfg):
        return None
    return uid


# --- python3-saml plumbing -------------------------------------------------


def saml_settings(cfg: SSOConfig) -> dict:
    """The settings dict python3-saml expects.

    `wantAssertionsSigned` and `wantMessagesSigned` are on: an unsigned
    assertion is an assertion anyone can forge, and the whole point of this
    module is that the identity is proven rather than claimed.
    """
    # NO singleLogoutService. Advertising SAML Single Logout would put an
    # endpoint in the metadata that Miami IT would then configure, and this
    # SP does not implement one -- /admin/sso/sls returned 404 while the
    # metadata claimed it existed. A dead endpoint in published metadata is
    # worse than an absent one: it fails at logout time, in production, for
    # somebody who has no idea why.
    #
    # Local sign-out at /admin/sso/logout drops this service's session,
    # which is the whole of what an operator needs. SLS would additionally
    # end their Miami session everywhere, and SAML SLS is notoriously
    # unreliable at that. If it is ever wanted, implement the route FIRST
    # and re-send the metadata.
    sp: dict = {
        "entityId": cfg.sp_entity_id,
        "assertionConsumerService": {
            "url": cfg.acs_url,
            "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST",
        },
        # Transient is Miami's default and is deliberately anonymous -- it
        # cannot identify anyone, which is why the whitelist reads an
        # ATTRIBUTE (uid) and never the NameID.
        "NameIDFormat": "urn:oasis:names:tc:SAML:2.0:nameid-format:transient",
        "x509cert": cfg.sp_cert,
        "privateKey": cfg.sp_key,
    }
    return {
        "strict": True,
        "debug": False,
        "sp": sp,
        "idp": {
            "entityId": cfg.idp_entity_id,
            "singleSignOnService": {
                "url": cfg.idp_sso_url,
                "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect",
            },
            "singleLogoutService": {
                "url": cfg.idp_slo_url,
                "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect",
            },
            "x509cert": cfg.idp_cert,
        },
        "security": {
            "authnRequestsSigned": bool(cfg.sp_key),
            "wantAssertionsSigned": True,
            "wantMessagesSigned": False,
            "wantNameId": False,
            "requestedAuthnContext": False,
            "signatureAlgorithm":
                "http://www.w3.org/2001/04/xmldsig-more#rsa-sha256",
            "digestAlgorithm": "http://www.w3.org/2001/04/xmlenc#sha256",
            # NO EXPIRY ON OUR METADATA.
            #
            # python3-saml defaults `validUntil` to now + 2 days and
            # recomputes it on every request, so this URL was handing Miami
            # IT a document that expired within 48 hours of being fetched.
            # For an IdP that saves a static copy -- which is how this
            # integration is being set up -- that is a login that stops
            # working on a date nobody wrote down, with no failure until
            # the day it happens.
            #
            # It also disagreed with its own cacheDuration: cache this for
            # a week, and it expires in two days.
            #
            # validUntil is OPTIONAL in SAML 2.0 metadata. Our SP details
            # change only when the certificate is rotated, and that is an
            # event we would tell them about rather than something a clock
            # should discover. An empty string omits the attribute; None
            # would restore the default. Asked for by Miami IT, 2026-08-27.
            "metadataValidUntil": "",
        },
        # contactPerson is included ONLY with a real address. python3-saml
        # rejects the whole settings dict with "contact_not_enought_data"
        # when the block exists but the email is blank -- which would take
        # out the metadata endpoint entirely, in exchange for an optional
        # courtesy field. An unset SSO_CONTACT_EMAIL must cost the contact
        # line, not the login.
        **({"contactPerson": {
            "technical": {
                "givenName": _env("SSO_CONTACT_NAME",
                                  "Miami University Libraries"),
                "emailAddress": _env("SSO_CONTACT_EMAIL"),
            },
        }} if _env("SSO_CONTACT_EMAIL") else {}),
        "organization": {
            "en-US": {
                "name": "Miami University Libraries",
                "displayname": "Miami University Libraries Smart Chatbot",
                "url": "https://www.lib.miamioh.edu/",
            },
        },
    }


def safe_next(target: str | None) -> str:
    """Where to land after login.

    Only same-site admin paths are honoured. A `next` that an attacker
    controls is an open redirect, and an open redirect on a login endpoint is
    how a convincing credential-phishing link gets built out of a trusted
    domain.
    """
    if not target or not target.startswith("/admin"):
        return "/admin/"
    if target.startswith("//") or "\\" in target:
        return "/admin/"
    return target


__all__ = [
    "COOKIE_PATH",
    "SESSION_COOKIE",
    "SSOConfig",
    "display_name_from_attributes",
    "is_allowed",
    "issue_session",
    "load_config",
    "read_session",
    "safe_next",
    "saml_settings",
    "uid_from_attributes",
]
