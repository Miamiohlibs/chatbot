# System Overview

**Last updated:** 1 September 2026
**Chinese version:** [01-SYSTEM-OVERVIEW.zh.md](./01-SYSTEM-OVERVIEW.zh.md) —
the same document, kept in step. Change both or say which one is
authoritative.

This is the whole system in one place: what runs, how a question becomes
an answer, where the data lives, who can reach what, and what the money
does. Every number in it was measured on the box on the date above, not
recalled.

---

## 1. What this is

A chatbot for Miami University Libraries, on the library website since
**13 August 2026**. It answers questions about hours, spaces, borrowing,
subject librarians and room booking, and it hands anything else to Ask
Us.

It is a **navigator, not an answer generator**. Only API data and
long-stable policy are baked into the corpus; anything with a date on it
— events, exhibits, news — is answered by pointing at the page that owns
it. That rule exists because a corpus is a snapshot and a snapshot of an
events page is wrong within a week.

---

## 2. What runs on the box

A single AWS t4g.medium, **3,823 MB of RAM**. That number governs more
design decisions than any other.

```
chatbot.service    uvicorn src.main:app_sio  →  127.0.0.1:8081
                   ONE worker. Not an accident: the live-usage counter
                   is in-process, and a second worker makes it a
                   fraction of the truth.
nginx              TLS, static files, reverse proxy
docker             weaviate 1.28.6   vector store, :8080
                   postgres 15       relational store
```

Warm-up after a restart is **45–80 seconds**. During a corpus rebuild,
answers slow from ~7 s to ~25 s; uncapped, the box stops answering
entirely, which is why `apply` always runs under a memory cap
(`APPLY_MEMORY_CAP_MB = 1100`). Measured in
[AWS-CAPACITY-REQUEST.md](./AWS-CAPACITY-REQUEST.md).

---

## 3. Request routing (nginx)

| Path | Goes to |
|---|---|
| `/` | the static library site |
| `/smartchatbot/` | `client/dist/` — the built React widget |
| `/smartchatbot/socket.io/` | :8081 — **every patron question** |
| `/admin/` | :8081 — operator console |
| `/librarian/` | :8081 — staff console |
| `/askus-hours/status`, `/ticket/create` | :8081 |
| `/crowdindex`, `/argus` | other services on this host, unrelated |

---

## 4. One turn, end to end

`_v2_message` in `src/main.py` → `run_turn` in
`src/graph/new_orchestrator.py`, which is **75 numbered stages** in three
movements.

### Movement 1 — work out what was asked (stages 1 – 3.6)

Scope resolution (which campus, which library) → kNN intent
classification → a **prompt-injection gate** → then roughly thirty
**deterministic short-circuits**: room booking, subject librarians,
opening hours, finding a person, MakerSpace, Special Collections,
cross-campus comparison, equipment lending, and more.

**Most correct answers never reach a model.** They are looked up and
formatted. The LLM handles what is left. This is the single most
important thing to understand about the system: when an answer is wrong,
the first question is *which stage produced it*, and the answer is
usually a lookup or a rule, not the model.

### Movement 2 — run the agent (stage 4)

Ten tools:

```
read-only   search_kb   lookup_librarian   lookup_space
            get_hours   get_room_availability   validate_url
action      book_room   create_ticket   handoff_human
pointer     point_to_url        returns a URL; never acts for the patron
```

### Movement 3 — synthesise and record (stages 5 – 6)

Evidence goes to the synthesiser, and the turn is written to `Message`,
`ModelTokenUsage` and `ToolExecution`.

### Models

**GPT-5.6 only.** Operator ruling, 1 September 2026: nothing below 5.6 is
kept anywhere — not as a tier, not as a fallback, not in the rate card.

| Role | Model | Per 1M tokens (in / cached / out) |
|---|---|---|
| *(none — priced, not wired)* | `gpt-5.6-sol` | 4.00 / 0.40 / 20.00 |
| Reasoning | `gpt-5.6-terra` | 2.00 / 0.20 / 12.00 |
| Basic + cheap | `gpt-5.6-luna` | 0.20 / 0.02 / 1.20 |
| Embeddings | `text-embedding-3-large` | 0.13 — input only |

Rates read off OpenAI on 1 September 2026. **Sol is the top of the line and
sits above terra**, so our reasoning tier is the middle model, not the best
one. It is deliberately priced but not selected: the rate is in the table so
that switching to it can never bill $0 by surprise. Sol got *cheaper* on 21
August (was 5.00 / 0.50 / 30.00) and OpenAI calls that promotional through
at least 21 November.
| Embeddings | `text-embedding-3-large` | — |

Terra costs about **21× luna per call**. At 85% of the student purse the
budget guard forces reasoning down to luna: every feature still works,
hard questions get answered less well.

---

## 5. Data stores

### Postgres — facts and records

| Table | Rows | What it is |
|---|---:|---|
| `Message` | 7,114 | every turn, both sides |
| `Conversation` | 3,129 | one per socket, most with no question in them |
| `ModelTokenUsage` | 1,312 | what each call cost |
| `ToolExecution` | 1,208 | which tools the agent called |
| `UrlSeen` | 824 | the allowlist a citation must be on |
| `Subject` / `LibGuide` | 745 / 480 | subject ↔ guide ↔ librarian |
| `Librarian` | 74 | |

### Weaviate — semantic retrieval

Nine collections. The one being served is named by
`WEAVIATE_CHUNK_COLLECTION` — today `Chunk_vv20260830_0302`, 490 chunks.

**Every `apply` builds a NEW collection and then switches to it.** The old
one stays. Rolling back is an environment variable and a restart, not a
rebuild.

### Files

```
ai-core/data/audit/actions-YYYY-MM.jsonl   who did what (see §7)
ai-core/data/diffs/                        ETL diffs and signatures
/opt/chatbot/data/                         budget state, alert queue
```

---

## 6. The frontend

**27 files, 3,315 lines.** React + Vite + Tailwind v4, with shadcn-style
components (radix, cva, lucide).

```
SocketContextProvider   the socket.io connection; same-origin in production
MessageContextProvider  message state
ChatBotComponent        the chat window
FeedbackFormComponent   the rating dialog
HumanLibrarianWidget    handoff to a person
CitationChip            source markers
```

Built to two files in `client/dist/assets/`.

**The admin console is not this.** It is Python emitting HTML strings
through one shared shell (`src/api/admin/admin_ui.py`), with no build
step — changing console styling does not require `npm run build`. Every
colour there comes from a token; two tests fail the build if a router
hardcodes one or names a token the stylesheet does not define.

---

## 7. Who can reach what

Four doors.

| Door | Opens | Status |
|---|---|---|
| **Miami SSO** (SAML) | all of `/admin/*` and `/librarian/*` | on; IdP configuration with Miami IT in progress |
| **`ADMIN_API_TOKEN`** | the same, as an emergency fallback | **off** (`SSO_ALLOW_TOKEN_FALLBACK=false`) |
| **`LIBRARIAN_TICKET_CODE`** | `/librarian/` and the report form only | on |
| **nothing at all** | `/admin/service` (the stop button), the widget, `/health/service` | on |

**Two roles**, and operator is a superset of librarian:

- **operators** — 5 people, `SSO_ALLOWED_UIDS`. Everything.
- **librarians** — 8 people, `SSO_LIBRARIAN_UIDS`: the department heads
  and the dean's office. The report form, test mode, and real patron
  conversations. Nothing else.

The session cookie is issued at **two paths** — `/admin` and `/librarian`
— and deliberately not at `/`, because the widget is served from the same
host and a patron's page load must never carry an operator's session.

### The passphrase rule

Signed in through Miami, dangerous actions ask for **no passphrase**: the
IdP established who you are, and the action is recorded against your
account in the audit log. Arriving on the shared key, the passphrase still
applies — that caller is anonymous, and a log line naming an anonymous
caller records nothing worth having.

The stop button always asks, because it is reachable by anyone. That is
deliberate: it has to work when the IdP is the thing that is broken.

### The audit log

`/admin/audit`, backed by one JSONL file per month. A file rather than a
table because it is read after exactly the events that take the database
away. Lines done with the shared key are marked **unverified**.

---

## 8. Scheduled work

**One time for everything the bot mails: 09:30 America/New_York**, run by
`chatbot-morning.timer` → `ai-core/scripts/morning_jobs.sh`.

| | When |
|---|---|
| Data-health report (sent every morning, all-clear included) | daily |
| Daily digest — every other queued alert, including a failed backup | daily |
| Website-change watch | Mondays |
| Budget report | Mondays, and the 1st |

Not cron, because this box runs UTC and Ubuntu's cron cannot schedule in
another timezone — a fixed UTC time would be 09:30 in summer and 08:30 in
winter. `Persistent=true` also catches up after downtime, which cron never
did.

**Still on cron**, because they must not wait for business hours or must
not run during them:

```
*/5   liveness watchdog   (restarts the service if systemd gave up)
*/15  budget guard
02:00 cost rollup         must finish before the morning reports read it
03:30 database backup     a pg_dump, kept out of the hours students ask
```

---

## 9. Money

Two purses that **cannot** spend each other's money, reset by the
calendar month in Oxford time. The reset is a `WHERE createdAt >= <1st>`
in a query — there is no job to run and nothing to clear.

**From 1 September 2026: $100/month, fixed.**

| Purse | Per month | Covers |
|---|---:|---|
| Students | **$40** | real patron traffic |
| Testing | **$60** | the eval harness, scripted runs, **and librarians testing through `/librarian/staff-test`** |

That last clause was wrong until 1 September: a librarian testing arrives
in a real browser from our own host, so her spend was charged to the
students' purse — $0.38 of $2.30, 17% of that purse, and growing as the
eight department heads start using the console. Three call-site labels
now feed one purse (`v2_turn_dev`, `legacy_dev`, `v2_turn_staff`), kept
apart so the cost page can still say how much was developing versus
checking.

### The ladder

Whichever fires first, a slow month-long creep or one runaway afternoon:

| At | What changes |
|---|---|
| 70% | email only; nothing changes for students |
| 85% | reasoning model forced to the cheap one |
| 95% | per-client rate limit and turn cap tightened |
| 100% | new conversations declined, pointing at Ask Us; open ones finish |

Escalation is immediate. Recovery steps down **one rung at a time** and
only past a 10% margin, so the guard cannot flap and mail on every
crossing. Walking back from *refuse* to *normal* takes about an hour.

### Changing the purse is two edits

Change the numbers in `.env`, **and** add a row to `PURSE_HISTORY` in
`src/config/budget.py` recording what the purse was until that day. Skip
the second and nothing breaks today — only the history of the month you
just left stops being true, and the cost page reports each month as a
percentage of its own purse.

| In force from | Students | Testing |
|---|---:|---:|
| the build period | $25 | $75 |
| 13 Aug 2026 (beta opened) | $45 | $75 |
| **1 Sep 2026** | **$40** | **$60** |

---

## 10. Scale

```
ai-core/src       242 files    87,639 lines
ai-core/scripts   115 files    31,611 lines
client/src         27 files     3,315 lines
tests             2,687 passing, 2 failing
```

The two failures are missing asyncio markers in
`scripts/test_library_spaces.py`, a standalone script. They predate this
document and are unrelated to anything above.

---

## 11. Where to look next

| Question | Document |
|---|---|
| What every setting does | [02-ENVIRONMENT-VARIABLES.md](./02-ENVIRONMENT-VARIABLES.md) |
| How a colleague uses the console | [09-TEAM-MAINTENANCE-GUIDE.md](./09-TEAM-MAINTENANCE-GUIDE.md) |
| Getting website updates into the bot | [08-WEBSITE-UPDATES-INTO-THE-BOT.md](./08-WEBSITE-UPDATES-INTO-THE-BOT.md) |
| Deploying | [05-DEPLOYMENT-GUIDE.md](./05-DEPLOYMENT-GUIDE.md) |
| The spend ladder in detail | [BUDGET.md](./BUDGET.md) |
| What is still unfinished | [OPEN-WORK.md](./OPEN-WORK.md) |
