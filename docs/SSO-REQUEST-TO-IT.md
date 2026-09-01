# SSO setup request — Libraries Smart Chatbot

TeamDynamix, System **10357 — Shibboleth**. Send the metadata as a **URL**,
not a file, so their IdP re-reads it when we change it. Ours advertises
`cacheDuration="PT604800S"` (7 days) and deliberately carries **no
`validUntil`** — an expiry we forget to bump is an outage nobody can
diagnose.

> **Correction outstanding (1 Sep 2026).** The message below was sent with
> the line *"AuthnRequests are signed"*. **That is false and always was.**
> Our metadata says `AuthnRequestsSigned="false"` and publishes **zero
> certificates** — we have no signing key. If Miami IT configured their
> side to require a signed AuthnRequest, every sign-in fails, which is
> consistent with what we are seeing. Corrected wording is in §"What to
> send instead" below; send it before debugging anything else.

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

*(Above is the message as sent, kept verbatim as the record. The signing
claim in the second-to-last paragraph is wrong — see the correction.)*

---

## What to send instead

Two things changed since that message: the signing claim was wrong, and the
console grew a second, larger group of users.

> Two corrections to my earlier ticket.
>
> **We do not sign AuthnRequests.** Our metadata publishes
> `AuthnRequestsSigned="false"` and no certificate. We do require signed
> assertions (`WantAssertionsSigned="true"`). If your side was configured
> to expect a signed request from us, that would explain the failures.
>
> **Scope is larger than five accounts.** The same SP now also protects
> `/librarian/*`, a read-only console for department heads and the dean's
> office. Thirteen accounts total, still only a few sign-ins a week. No
> change to attributes, bindings or endpoints — the ACS, EntityID and
> metadata URL are all unchanged.

---

## For us, not the ticket

**Before sending**, confirm the deployed metadata matches what the ticket
claims. Checked 1 Sep 2026:

```bash
curl -s https://chatbot.lib.miamioh.edu/admin/sso/metadata | grep -Eo 'AuthnRequestsSigned="[a-z]+"|WantAssertionsSigned="[a-z]+"'; curl -s https://chatbot.lib.miamioh.edu/admin/sso/metadata | grep -c SingleLogoutService
```

```
AuthnRequestsSigned="false"
WantAssertionsSigned="true"
0
```

`SingleLogoutService` must be `0`. An earlier draft advertised an SLS
endpoint that does not exist; `1` means the fix is not deployed and IT
would configure a dead endpoint.

### Current state (1 Sep 2026)

- `SSO_ENABLED=true` — **done**, deployed.
- `SSO_ALLOW_TOKEN_FALLBACK=false` — **done**. The original plan here was
  to flip this only after all five had signed in once; it was flipped
  first, deliberately, so Miami IT tests against pure SSO with no second
  door open. The consequence is real and current: **nobody can reach
  `/admin/*` until IT finishes.** Setting it back to `true` and
  restarting reopens the shared key in about a minute — no deploy.
- **Nobody has ever completed a sign-in**, so nothing about the IdP side
  is confirmed working.

### Who is on the list

| Variable | Who | Reaches |
|---|---|---|
| `SSO_ALLOWED_UIDS` | `qum, bomholmm, maderir, irwinkr, yarnete` | everything |
| `SSO_LIBRARIAN_UIDS` | 8 department heads / dean's office | `/librarian/*` only |

Operator is a superset of librarian. Removals take effect on that person's
next request. The kill switch at `/admin/service` sits outside SSO and is
unaffected throughout.
