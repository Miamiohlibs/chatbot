# SSO setup request — Miami University Libraries Smart Chatbot

Submit through TeamDynamix (System: **10357 — Shibboleth**). The body below
answers the six items Miami IT asks for in *Set up vendor single sign-on
(SSO) with Miami University / SAML* (KB 138639).

**Send the metadata as a URL, not a file.** The published document carries a
short `validUntil`, which a Shibboleth IdP refreshes automatically when it
holds a URL and cannot refresh when it holds a copy.

---

## Ticket body

**Subject:** SAML SSO setup for chatbot.lib.miamioh.edu (Libraries Smart
Chatbot admin dashboard)

Hello,

We would like to protect the administrative dashboard of the University
Libraries' Smart Chatbot with Miami single sign-on. The service is built and
running; our SAML SP is live and waiting to be registered on your side.

**What the service is.** An internal dashboard used by a small number of
library staff to review chatbot conversations, correct wrong answers, watch
spend, and take the bot out of service. It is not patron-facing — the public
chat widget is separate, unauthenticated, and is not affected by this
request. The pages behind SSO display raw patron questions, which is why we
want proven identity in front of them rather than the shared token we use
today.

Here is what your knowledge-base article asks for.

**1. Our metadata**

https://chatbot.lib.miamioh.edu/admin/sso/metadata

Served over TLS with a complete chain (leaf plus *InCommon RSA OV SSL CA 3*).

**2. Desired attributes**

We need exactly one, to identify the person:

| Attribute | OID | Why |
|---|---|---|
| `uid` | `urn:oid:0.9.2342.19200300.100.1.1` | Matched against our access list |

If your release policy does not include bare `uid` for this service,
`eduPersonPrincipalName` (`urn:oid:1.3.6.1.4.1.5923.1.1.1.6`) works equally
well — we take the local part. Either one alone is sufficient. We do not
need `mail`, `displayName`, `sn`, `givenName` or department, and would
rather not receive them.

Note that we cannot use the NameID for this. Your default is transient,
which is deliberately anonymous, so identification has to come from a
released attribute.

**3. Desired NameID format**

`urn:oasis:names:tc:SAML:2.0:nameid-format:transient` — your documented
default. We have no reason to ask for anything more identifying.

**4. Login URL for the service**

https://chatbot.lib.miamioh.edu/admin/

Staff land there; anyone without a session is redirected into the SP-initiated
flow at `/admin/sso/login`.

**5. Attribute Requester URL/URN**

Same as our EntityID — no separate value:

`https://chatbot.lib.miamioh.edu/admin/sso/metadata`

**6. SP-initiated or IdP-initiated**

**SP-initiated**, as you recommend. We do not need an IdP-initiated flow.

**Other details you may want**

| | |
|---|---|
| ACS (Assertion Consumer Service) | `https://chatbot.lib.miamioh.edu/admin/sso/acs`, HTTP-POST |
| Single Logout | Not implemented, and not advertised in our metadata |
| AuthnRequests | Signed (our signing certificate is in the metadata) |
| Assertions | We require them signed |
| Expected volume | Very low — five accounts, a handful of sign-ins per week |

**Testing.** Your article notes that test accounts are not provided but that
you are happy to test on request. We would appreciate that. Our side is
already deployed, so we can test whenever suits you.

**Contact.** Meng Qu, Miami University Libraries — qum@miamioh.edu

Thank you,
Meng

---

## Notes for us, not for the ticket

**Before sending**, confirm the metadata URL serves the current document:

```bash
curl -s https://chatbot.lib.miamioh.edu/admin/sso/metadata | grep -c SingleLogoutService
```

Must print `0`. An earlier draft advertised an SLS endpoint that did not
exist; if this prints `1`, the fix has not been deployed yet and IT would be
configuring a dead endpoint.

**When IT confirms they are done**, our side is one variable:

```
SSO_ENABLED=true      # in /opt/chatbot/.env, then restart
```

Nothing else changes. Expect roughly 80 seconds of warm-up after the
restart, during which the site returns 502.

**Then, and only then**, turn off the shared token:

```
SSO_ALLOW_TOKEN_FALLBACK=false
```

Do that once all five accounts have signed in successfully at least once —
not before. The kill switch at `/admin/service` is deliberately outside SSO
and is unaffected either way.

**The access list** is `SSO_ALLOWED_UIDS` in `.env`:
`qum, bomholmm, maderir, irwinkr, yarnete`. Removing a uid takes effect on
that person's next request.
