# SSO setup request — Libraries Smart Chatbot

TeamDynamix, System **10357 — Shibboleth**. Send the metadata as a **URL**,
not a file: it carries a short `validUntil` that a Shibboleth IdP refreshes
on its own.

---

**Subject:** SAML SSO setup for chatbot.lib.miamioh.edu

Hello,

We would like Miami SSO in front of the admin dashboard of the Libraries'
Smart Chatbot. Our SP is built and live; it needs registering on your side.
The dashboard is used by five library staff and shows raw patron
conversations — the public chat widget is separate, unauthenticated, and not
affected by this request.

Answering the six items in KB 138639:

1. **Our metadata** — https://chatbot.lib.miamioh.edu/admin/sso/metadata

2. **Attributes** — `uid` (`urn:oid:0.9.2342.19200300.100.1.1`) only. If your
   policy does not release bare `uid`, `eduPersonPrincipalName`
   (`urn:oid:1.3.6.1.4.1.5923.1.1.1.6`) works instead — either one alone is
   enough. We do not need mail, displayName, sn, givenName or department.
   We cannot use the NameID for this, since transient is anonymous.

3. **NameID format** — `urn:oasis:names:tc:SAML:2.0:nameid-format:transient`,
   your default.

4. **Login URL** — https://chatbot.lib.miamioh.edu/admin/

5. **Attribute Requester** — same as our EntityID,
   `https://chatbot.lib.miamioh.edu/admin/sso/metadata`

6. **SP-initiated**, as you recommend.

Also: ACS is `https://chatbot.lib.miamioh.edu/admin/sso/acs` (HTTP-POST),
AuthnRequests are signed, we require signed assertions, and we do not
implement Single Logout. Volume is five accounts, a few sign-ins a week.

Your article notes you can test on request — we would appreciate that. Our
side is deployed, so any time suits.

Meng Qu, Miami University Libraries — qum@miamioh.edu

---

## For us, not the ticket

**Before sending**, confirm the deployed metadata is the corrected one:

```bash
curl -s https://chatbot.lib.miamioh.edu/admin/sso/metadata | grep -c SingleLogoutService
```

Must print `0`. An earlier draft advertised an SLS endpoint that does not
exist; `1` means the fix is not deployed and IT would configure a dead
endpoint.

**When IT is done:** set `SSO_ENABLED=true` in `.env` and restart (~80s of
502 while it warms up). Nothing else changes.

**After all five have signed in once:** set
`SSO_ALLOW_TOKEN_FALLBACK=false`. Not before.

Access list is `SSO_ALLOWED_UIDS`: `qum, bomholmm, maderir, irwinkr,
yarnete`. Removals take effect on that person's next request. The kill
switch at `/admin/service` sits outside SSO and is unaffected throughout.
