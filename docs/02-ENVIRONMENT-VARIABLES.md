# Environment Variables Reference

**Last Updated:** 1 September 2026

Reference for the environment variables the chatbot actually reads.

> **Corrected 1 Sep 2026, and worth knowing what was wrong.** This file
> claimed to be complete and was not. The template at the bottom named
> **ten variables that exist nowhere** — not in the code, not in `.env`:
> `WEAVIATE_API_KEY`, `GOOGLE_CSE_API_KEY`, `GOOGLE_CSE_CX`,
> `LIBGUIDES_SITE_ID`, `LIBGUIDES_API_KEY`, `LIBGUIDES_API_URL`,
> `LIBANSWERS_IID`, `LIBANSWERS_API_BASE_URL`, `LIBCAL_TOKEN_URL`,
> `LIBCAL_API_BASE_URL`. Standing up a new instance from it would have
> produced a bot that could not reach LibCal, LibGuides, LibAnswers,
> Weaviate or Google. Whole groups were missing too: everything that
> turns SSO on, everything about the budget, and every rate limit.
>
> **The template is now generated from the running `.env`, secrets
> stripped** — so it is right by construction rather than by somebody
> remembering to update it. Regenerate it the same way if it drifts.

---

## Operator Alerts & Admin Surfaces (added 2026-07)

### Email alerts (`ai-core/src/observability/alerting.py`)

Sends the operator an email on dependency down/recovered events; the
correction-ticket system uses the same transport. The AWS host blocks
outbound port 25, so an authenticated relay on 587 is required
(configured and verified working 2026-07-17 via a Gmail App Password).

```bash
ALERT_EMAIL_ENABLED=true                 # "false" silences alerts
ALERT_EMAIL_TO=qum@miamioh.edu           # operator inbox
ALERT_EMAIL_FROM=qum@miamioh.edu         # must equal ALERT_SMTP_USER for Gmail
ALERT_SMTP_HOST=smtp.gmail.com
ALERT_SMTP_PORT=587
ALERT_SMTP_STARTTLS=true
ALERT_SMTP_USER=qum@miamioh.edu
ALERT_SMTP_PASSWORD=<16-char Gmail App Password, no spaces>
```

Verify: `cd ai-core && .venv/bin/python -m src.observability.alerting`
(sends a test email).

### Admin & librarian surfaces (`ai-core/src/main.py`)

```bash
ADMIN_API_TOKEN=<secret>          # the ORIGINAL door to /admin/*. Since
                                  # 2026-09-01 it is refused unless
                                  # SSO_ALLOW_TOKEN_FALLBACK=true.
                                  # Unset = routes not mounted (fail-closed).
LIBRARIAN_TICKET_CODE=<secret>    # staff access code for /librarian/*.
                                  # Weaker secret by design: distributable
                                  # to library staff, exposes no patron
                                  # content -- see below.
```

**Why the weaker code stays weak.** `/librarian/` has three cards: report
a wrong answer, turn on test mode, and read what patrons actually asked.
The first two open with the shared code. **The third does not** — it
requires a Miami sign-in, and the page says so in those words. The reason
is the whole justification for the code being distributable at all: a
secret that every library staff member has is not a secret, and patron
conversations are patrons' own words. Verified 2026-09-01:
`/librarian/conversations?key=<code>` returns **401**; the card links to
`/admin/sso/login?next=/librarian/conversations` instead.

If that gate is ever loosened, `LIBRARIAN_TICKET_CODE` stops being a
distributable code and this note stops being true.

See [06-CORRECTION-TICKETS.md](./06-CORRECTION-TICKETS.md) for the ticket
workflow.

---

## Core Configuration

### OpenAI API
```bash
OPENAI_API_KEY=sk-...
# Model TIERS (OPENAI_MODEL is deprecated -- no longer read):
LLM_MODEL_BASIC=gpt-5.6-luna        # synthesizer / surface questions
LLM_MODEL_REASONING=gpt-5.6-terra   # agent loop, escalation, clarify
LLM_MODEL_CHEAP=gpt-5.6-luna        # eval judge, mechanical extraction
LLM_MODEL_EMBEDDING=text-embedding-3-large  # changing this invalidates the vector index
```
- **OPENAI_API_KEY**: Your OpenAI API key (required)
- Tier values above are the production settings as of 2026-09-01. **GPT-5.6
  only** — the operator ruling that day removed every older id from the code,
  the fallbacks and the rate card. `gpt-5.6-sol` is priced but not wired, so
  moving REASONING onto it is a one-line change that cannot silently bill
  $0. Swap
  models per tier without touching call sites (`src/config/models.py`).

---

## Database

### PostgreSQL
```bash
DATABASE_URL=postgresql://<user>:<pw>@127.0.0.1/smartchatbot?sslmode=disable
```
- Postgres runs in a Docker container **on this host**, so the connection
  never leaves the box and `sslmode=disable` is correct. This file said
  `sslmode=require` against a remote host, which is neither what runs nor
  what would work.

---

## Weaviate (the website corpus)

Not Weaviate Cloud, and not a correction pool — both were true under v3.1
and neither is true now. Weaviate runs in a **Docker container on this
host**, unauthenticated on the loopback interface, and holds the ETL'd
website. Hand-written corrections live in Postgres `ManualCorrection`.

```bash
WEAVIATE_ENABLED=true
WEAVIATE_HOST=127.0.0.1
WEAVIATE_SCHEME=http
WEAVIATE_HTTP_PORT=8080
WEAVIATE_GRPC_PORT=50051
WEAVIATE_CHUNK_COLLECTION=Chunk_vv20260830_0302
WEBSITE_EVIDENCE_COLLECTION=WebsiteEvidence_2026_01_12_22_36_49
```

- **WEAVIATE_CHUNK_COLLECTION** — **the one that matters.** It names the
  collection being served. Every `apply` mints a new dated collection and
  leaves the old ones in place, so this value changes without anyone
  editing a file, and **rolling back a bad corpus is this variable plus a
  restart** — not a rebuild. It is read with `os.getenv` at request time,
  so a corpus swap takes effect on the next question. Never trust a
  collection name written in a document, this one included: `grep
  WEAVIATE_CHUNK_COLLECTION /opt/chatbot/.env`.
- There is no API key because there is no authentication. Nothing outside
  the host can reach :8080.

---

## LibCal API (Hours & Room Booking)

```bash
LIBCAL_OAUTH_URL=https://muohio.libcal.com/api/1.1/oauth/token
LIBCAL_CLIENT_ID=560
LIBCAL_CLIENT_SECRET=<secret>
LIBCAL_GRANT_TYPE=client_credentials
LIBCAL_HOUR_URL=https://muohio.libcal.com/api/1.1/hours
LIBCAL_SEARCH_AVAILABLE_URL=https://muohio.libcal.com/api/1.1/space/search/hourly
LIBCAL_ROOM_INFO_URL=https://muohio.libcal.com/api/1.1/space/items
LIBCAL_RESERVATION_URL=https://muohio.libcal.com/api/1.1/space/reserve
LIBCAL_BOOKING_INFO_URL=https://muohio.libcal.com/api/1.1/space/booking
LIBCAL_CANCEL_URL=https://muohio.libcal.com/api/1.1/space/cancel
LIBCAL_ASKUS_ID=8876
```

One full URL per operation rather than a base URL — the host is
`muohio.libcal.com`, not `miamioh.libcal.com`.

### Where the location and building IDs actually live

**Not in the environment.** This file used to list eight variables —
`LIBCAL_KING_LOCATION_ID`, `LIBCAL_HAMILTON_BUILDING_ID` and so on — and
**none of them are read by anything.** Setting them has no effect.

The real arrangement:

| | Where |
|---|---|
| Campus, library and space records, with their LibCal ids | **Postgres**, seeded by `scripts/seed_library_locations.py` and `scripts/seed_library_spaces_v2.py` |
| King as the fallback building | hardcoded, `DEFAULT_BUILDING = "2047"` in `src/tools/libcal_comprehensive_tools.py` |

So a new or renumbered space is a **seed-script change and a database
write**, not an `.env` edit. The values themselves are unchanged and
still correct: King 8113/2047, Art 8116/4089, Hamilton 9226/4792,
Middletown 9227/4845.

---

## LibGuides API (Research Guides)

Singular `LIBGUIDE_`, not `LIBGUIDES_`.

```bash
LIBGUIDE_OAUTH_URL=https://lgapi-us.libapps.com/1.2/oauth/token
LIBGUIDE_CLIENT_ID=719
LIBGUIDE_CLIENT_SECRET=<secret>
LIBGUIDE_GRANT_TYPE=client_credentials
```

MyGuide, the Libraries' own subject service, is separate:

```bash
MYGUIDE_API_URL=https://myguidedev.lib.miamioh.edu/api/subjects
MYGUIDE_ID=<id>
MYGUIDE_API_KEY=<secret>
```

Note that URL is a **dev** hostname, on a production host. Recorded, not
changed — swapping it is a deployment decision.

---

## LibAnswers API (Chat Handoff)

Abbreviated `LIBANS_`, not `LIBANSWERS_` — except the two widget URLs,
which do use the long form.

```bash
LIBANS_OAUTH_URL=https://libanswers.lib.miamioh.edu/api/1.1/oauth/token
LIBANS_CLIENT_ID=1286APP-001
LIBANS_CLIENT_SECRET=<secret>
LIBANS_GRANT_TYPE=client_credentials
LIBANS_QUEUE_ID=<id>
LIBANSWERS_WIDGET_URL=https://libanswers.lib.miamioh.edu/chat/widget/<hash>
TEST_LIBANSWERS_WIDGET_URL=https://libanswers.lib.miamioh.edu/chat/widget/<hash>
```

---

## Google Custom Search Engine

```bash
GOOGLE_API_KEY=<secret>
GOOGLE_LIBRARY_SEARCH_CSE_ID=<cse-id>
DISABLE_GOOGLE_SITE_SEARCH=0
GOOGLE_SEARCH_DAILY_LIMIT=10000
GOOGLE_SEARCH_CACHE_TTL_SECONDS=604800
```

- **DISABLE_GOOGLE_SITE_SEARCH** — `1` switches site search off entirely.
- **GOOGLE_SEARCH_CACHE_TTL_SECONDS** — 604800 is a week.

---

## Removed Variables (Version 3.0)

These variables are **no longer used** and can be removed from `.env`:

```bash
# ❌ REMOVED - Primo catalog search disabled
PRIMO_SCOPE=MyInst_and_CI
PRIMO_API_KEY=...
PRIMO_SEARCH_URL=https://api-na.hosted.exlibrisgroup.com/primo/v1/search?
PRIMO_VID=01OHIOLINK_MU:MU
```

---

## Single sign-on

What actually turns SSO on. The uid lists are further down in the
template, with the note on how the librarian list was chosen.

```bash
SSO_ENABLED=true                 # default false
SSO_ALLOW_TOKEN_FALLBACK=false   # DEFAULT IS TRUE -- see below
SSO_BASE_URL=https://chatbot.lib.miamioh.edu
SSO_SP_ENTITY_ID=https://chatbot.lib.miamioh.edu/admin/sso/metadata
SSO_IDP_ENTITY_ID=urn:mace:incommon:muohio.edu
SSO_IDP_SSO_URL=https://muidp.miamioh.edu/idp/profile/SAML2/Redirect/SSO
SSO_IDP_SLO_URL=https://muidp.miamioh.edu/idp/profile/SAML2/Redirect/SLO
SSO_IDP_CERT=<secret>
SSO_SESSION_SECRET=<secret>
```

- **SSO_ALLOW_TOKEN_FALLBACK defaults to `true`.** Omit it and the shared
  `ADMIN_API_TOKEN` still opens the console — which is the safe default
  for a box where SSO is not configured, and the wrong one everywhere
  else. Set it explicitly. It is `false` in production since 2026-09-01,
  which is why nobody can reach `/admin/*` while Miami IT finishes.
- **SSO_SESSION_HOURS** is not set, so sessions last **8 hours**.
- **SSO_SP_CERT and SSO_SP_KEY are not set, deliberately.** We have no
  signing key, so our metadata publishes `AuthnRequestsSigned="false"`
  and zero certificates. If the IdP is configured to require a signed
  AuthnRequest, every sign-in fails. See
  [SSO-REQUEST-TO-IT.md](./SSO-REQUEST-TO-IT.md).
- **SSO_ALLOWED_UIDS** and **SSO_OPERATOR_UIDS** mean the same thing and
  are merged. Miami uids, not email addresses.

---

## Money

```bash
BUDGET_MONTHLY_SERVING_USD=40    # students
BUDGET_MONTHLY_EVAL_USD=60       # testing, incl. librarians via staff-test
BUDGET_EVAL_RUN_ESTIMATE_USD=6   # what one eval run is assumed to cost
BUDGET_TIGHTENED_RATE_MAX=6      # the 95% rung
BUDGET_TIGHTENED_MAX_TURNS=20    # the 95% rung
BUDGET_RECOVERY_MARGIN=0.10      # step back down only past a 10% margin
BUDGET_LAUNCH_AT=2026-08-13T18:00
```

**Changing a purse is two edits, not one.** These variables set what the
purse is *from now on*; `PURSE_HISTORY` in `src/config/budget.py` records
what it *was*. Skip the second and nothing breaks today — only the history
of the month you just left stops being true, because the cost page reports
each month against its own purse. The ladder is in
[BUDGET.md](./BUDGET.md).

---

## Limits, and who may stop the bot

```bash
CORS_ALLOW_LOCALHOST=            # unset. "true" adds http://localhost:5173
                                 # and :3000 as CREDENTIALED origins.
CHAT_RATE_MAX=20                 # messages per window, per client
CHAT_RATE_WINDOW_S=60
CHAT_MAX_TURNS_PER_CONVERSATION=80
CHAT_MAX_MESSAGE_CHARS=4000
BOOKING_MAX_PER_CONVERSATION=2
BOOKING_MAX_PER_EMAIL_PER_DAY=2
CANCEL_FAIL_MAX=5
CANCEL_FAIL_WINDOW_S=3600
HEALTH_PROBE_TTL_S=30
SERVICE_PAUSE_OPERATORS=<uid>@miamioh.edu,...
SERVICE_PAUSE_PASSWORD=<secret>
```

**`CORS_ALLOW_LOCALHOST` replaced a `NODE_ENV=="development"` check.** That
check was live on this box — the production `.env` sets
`NODE_ENV=development` — so production was accepting `http://localhost:5173`
and `:3000` as credentialed cross-origin callers on **every** path,
`/admin/*` included. Nobody chose that; it fell out of a dev convenience
keyed to a variable nobody flipped. It is off unless set explicitly now.

The same variable still decides socket.io's origin policy, where it
currently evaluates to `"*"` — see the note in `src/main.py`. That one is
**not** fixed; narrowing the patron-facing socket is an operator decision.

The booking caps are the ones with real-world consequences: they are what
stops a loop, or a bored student, from filling the room calendar.

`SERVICE_PAUSE_OPERATORS` plus `SERVICE_PAUSE_PASSWORD` govern the stop
button at `/admin/service`, which sits **outside SSO on purpose** — it has
to work when the identity provider is the thing that is broken. That is
also why it still asks for a passphrase when nothing else does.

---

## Complete .env Template

**Generated from the running `.env` on 1 September 2026**, secrets
replaced with `<secret>`. Every name below is one the code actually reads.

```bash
OPENAI_ORGANIZATION_ID=<org-id>
OPENAI_API_KEY=<secret>
LLM_MODEL_BASIC=gpt-5.6-luna
LLM_MODEL_REASONING=gpt-5.6-terra
LLM_MODEL_CHEAP=gpt-5.6-luna
LLM_MODEL_EMBEDDING=text-embedding-3-large
LLM_ALLOW_TEMPERATURE_CHEAP=0
DATABASE_URL=<secret>
WEAVIATE_ENABLED=true
WEAVIATE_HOST=127.0.0.1
WEAVIATE_SCHEME=http
WEAVIATE_HTTP_PORT=8080
WEAVIATE_GRPC_PORT=50051
WEAVIATE_CHUNK_COLLECTION=Chunk_vv20260830_0302
WEBSITE_EVIDENCE_COLLECTION=WebsiteEvidence_2026_01_12_22_36_49
GOOGLE_LIBRARY_SEARCH_CSE_ID=<cse-id>
GOOGLE_API_KEY=<secret>
DISABLE_GOOGLE_SITE_SEARCH=0
GOOGLE_SEARCH_DAILY_LIMIT=10000
GOOGLE_SEARCH_CACHE_TTL_SECONDS=604800
LIBCAL_OAUTH_URL=https://muohio.libcal.com/api/1.1/oauth/token
LIBCAL_CLIENT_ID=560
LIBCAL_CLIENT_SECRET=<secret>
LIBCAL_GRANT_TYPE=client_credentials
LIBCAL_SEARCH_AVAILABLE_URL=https://muohio.libcal.com/api/1.1/space/search/hourly
LIBCAL_ROOM_INFO_URL=https://muohio.libcal.com/api/1.1/space/items
LIBCAL_RESERVATION_URL=https://muohio.libcal.com/api/1.1/space/reserve
LIBCAL_BOOKING_INFO_URL=https://muohio.libcal.com/api/1.1/space/booking
LIBCAL_CANCEL_URL=https://muohio.libcal.com/api/1.1/space/cancel
LIBCAL_HOUR_URL=https://muohio.libcal.com/api/1.1/hours
LIBCAL_ASKUS_ID=8876
LIBGUIDE_OAUTH_URL=https://lgapi-us.libapps.com/1.2/oauth/token
LIBGUIDE_CLIENT_ID=719
LIBGUIDE_CLIENT_SECRET=<secret>
LIBGUIDE_GRANT_TYPE=client_credentials
LIBANS_CLIENT_ID=1286APP-001
LIBANS_CLIENT_SECRET=<secret>
LIBANS_OAUTH_URL=https://libanswers.lib.miamioh.edu/api/1.1/oauth/token
LIBANS_GRANT_TYPE=client_credentials
LIBANS_QUEUE_ID=<id>
MYGUIDE_API_URL=https://myguidedev.lib.miamioh.edu/api/subjects
MYGUIDE_ID=<id>
MYGUIDE_API_KEY=<secret>
NODE_ENV=development
FRONTEND_URL=https://chatbot.lib.miamioh.edu
BACKEND_PORT=8000
FRONTEND_PORT=5173
SOCKET_PATH=/smartchatbot
TEST_LIBANSWERS_WIDGET_URL=https://libanswers.lib.miamioh.edu/chat/widget/a24a929728c7ee2cfdef2df20cbbc2ee
LIBANSWERS_WIDGET_URL=https://libanswers.lib.miamioh.edu/chat/widget/48597dfc1078556815ee78d6e99e7a7b
VITE_BACKEND_URL=https://chatbot.lib.miamioh.edu
VITE_BACKEND_PORT=8000
VITE_FRONTEND_PORT=5173
VITE_FRONTEND_DOMAIN=chatbot.lib.miamioh.edu
VITE_BASE_PATH=/smartchatbot
VITE_SOCKET_DOMAIN=
ADMIN_API_TOKEN=<secret>
LIBRARIAN_TICKET_CODE=<secret>
ALERT_EMAIL_ENABLED=true
ALERT_EMAIL_TO=qum@miamioh.edu
ALERT_EMAIL_FROM=qum@miamioh.edu
ALERT_SMTP_HOST=smtp.gmail.com
ALERT_SMTP_PORT=587
ALERT_SMTP_STARTTLS=true
ALERT_SMTP_USER=qum@miamioh.edu
ALERT_SMTP_PASSWORD=<secret>
BUDGET_MONTHLY_SERVING_USD=40
BUDGET_MONTHLY_EVAL_USD=60
BUDGET_EVAL_RUN_ESTIMATE_USD=6
BUDGET_TIGHTENED_RATE_MAX=6
BUDGET_TIGHTENED_MAX_TURNS=20
BUDGET_RECOVERY_MARGIN=0.10
BOOKING_MAX_PER_CONVERSATION=2
BOOKING_MAX_PER_EMAIL_PER_DAY=2
CANCEL_FAIL_MAX=5
CANCEL_FAIL_WINDOW_S=3600
CHAT_RATE_MAX=20
CHAT_RATE_WINDOW_S=60
CHAT_MAX_TURNS_PER_CONVERSATION=80
CHAT_MAX_MESSAGE_CHARS=4000
HEALTH_PROBE_TTL_S=30
SERVICE_PAUSE_OPERATORS=<uid>@miamioh.edu,...
SERVICE_PAUSE_PASSWORD=<secret>
BUDGET_LAUNCH_AT=2026-08-13T18:00
SSO_ENABLED=true
SSO_ALLOW_TOKEN_FALLBACK=false
SSO_BASE_URL=https://chatbot.lib.miamioh.edu
SSO_SP_ENTITY_ID=https://chatbot.lib.miamioh.edu/admin/sso/metadata
SSO_IDP_ENTITY_ID=urn:mace:incommon:muohio.edu
SSO_IDP_SSO_URL=https://muidp.miamioh.edu/idp/profile/SAML2/Redirect/SSO
SSO_IDP_SLO_URL=https://muidp.miamioh.edu/idp/profile/SAML2/Redirect/SLO
SSO_IDP_CERT=<secret>
SSO_ALLOWED_UIDS=qum,bomholmm,maderir,irwinkr,yarnete
SSO_LIBRARIAN_UIDS=abneykl,conleyj,henlear,johnsoj,kirschb,messnekr,millarj,shrimpak
SSO_SESSION_SECRET=<secret>
```

Not set, and therefore at their defaults: `SSO_SESSION_HOURS` (8),
`SSO_SP_CERT` / `SSO_SP_KEY` (absent — we do not sign), `ADMIN_AUDIT_DIR`
(`ai-core/data/audit`), `BUDGET_STATE_PATH`
(`/opt/chatbot/data/budget_state.json`).

Two oddities in the live file, recorded rather than tidied away because
changing them is a deployment decision, not a documentation one:

- `NODE_ENV=development` on a production host.
- `MYGUIDE_API_URL` points at `myguidedev.lib.miamioh.edu` — a **dev**
  hostname, in production.
