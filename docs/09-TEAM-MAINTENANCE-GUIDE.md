# Running the chatbot — a guide for the team

**Written 1 September 2026, for Ken, Jerry, Rachel and Mike.**

## How to read this

**Every command below was run on the production box on the date above,
and the output under it is copied, not written.** Run any of them
yourself; if what you get differs from what is printed here, this
document is wrong and I want to know.

That matters because the rest of the folder is prose you have no way to
check by running it. All 56 files in `docs/` were read line by line on the
date above and the wrong parts corrected — but an audit is a photograph,
not a guarantee, and the things that go stale here are small: a port, a
service name, a path, a dollar figure. **Section 8 says what the audit
found, what is still only partly true, and the two habits that keep this
from happening again.**

What this guide does **not** do is tell you every button. It explains how
the thing is put together well enough that you can work out an answer to
a question nobody wrote down.

---

## 1. The one thing to understand: what is read when

Rachel asked why changing a setting needs a restart. The answer is a
mental model rather than a rule, and once you have it you can predict the
rest.

**Anything designed to change while the bot is running is read on every
question. Anything else is read once, when the process starts.**

| You changed | It takes effect | Because |
|---|---|---|
| A correction (`/admin/corrections/view`) | **within 60 seconds** | `CACHE_TTL_SECONDS = 60.0` in `src/database/corrections_adapter.py` |
| The corpus, after an `apply` | **the next question** | the collection name is read with `os.getenv` at request time, not at import |
| The stop button | **the next question** | `is_paused()` checks for a file on every turn |
| `.env` | **restart required** | `load_dotenv` runs once at import, and constants are computed from it there |
| Any Python file | **restart required** | Python imports a module once per process |

So: corrections and the stop button were *built* to be live, because
somebody needs them to work at 3pm on a Tuesday without a deploy. `.env`
was not, because changing a budget or a password is a deliberate act that
can afford sixty seconds of downtime.

```bash
sudo systemctl restart chatbot        # ~45-80s before it answers again
```

*(That range is measured, not estimated. Confirmed again by an unplanned
restart on 1 Sep 2026 at 18:21 UTC — a stray `systemctl restart` in what
was meant to be a read-only check. It answered again in about 65 seconds,
came back clean, and lost nothing but the open sockets and the in-process
presence counter. Which is the point of this section: the cost of a
restart is real, bounded, and worth knowing before you cause one.)*

**Before you restart, check whether anybody is mid-conversation.** See
scenario E.

---

## 2. Scenario A — "Is the bot down?"

Ask the service, not a person. This endpoint is public and needs no
credentials:

```bash
curl -s https://chatbot.lib.miamioh.edu/health/service
```

```json
{"in_service":true,"paused":false,"since":null,"message":null,
 "ask_us_url":"https://www.lib.miamioh.edu/research/research-support/ask/"}
```

- `in_service: true` — it is answering.
- `paused: true` — somebody pressed the stop button. `since` and
  `message` say who and why.
- **No response at all** — the process is down. A watchdog checks every
  five minutes and restarts it if systemd has given up, so wait five
  minutes before doing anything. If it is still dead:

```bash
systemctl status chatbot --no-pager
sudo journalctl -u chatbot -n 50 --no-pager
```

**Students never see a blank page.** A paused bot still loads and answers
every question with a maintenance notice pointing at Ask Us.

---

## 3. Scenario B — "Are we going to blow the budget?"

```bash
sudo -u root bash -c 'set -a; . /opt/chatbot/.env; set +a; cd /opt/chatbot/ai-core && .venv/bin/python scripts/budget_guard.py --dry-run'
```

One line on purpose. A backslash-newline inside those single quotes is a
literal backslash, not a continuation, and the wrapped version of this
command does not run — which is the first thing I got wrong writing this
file.

```
budget purses in force: students $40.00, testing $60.00 (from 2026-09-01)
students  mtd $0.02/40.00   today $0.02/1.33
eval      mtd $0.00/60.00
level     0 (normal)  <- within budget
(dry run -- nothing written, nothing sent)
```

`--dry-run` changes nothing and sends nothing. It is safe to run at any
time and is the fastest honest answer to "where are we".

**Two purses, $100 a month total.** $40 for students, $60 for testing —
and "testing" is both the eval harness *and* a librarian trying the bot
through the staff-test link. They cannot spend each other's money.

The guard runs every 15 minutes on its own. At 85% of the student purse
it forces the cheap model; at 100% new conversations are declined with a
pointer to Ask Us and open ones are allowed to finish. **Mike gets an
email at each step change**; nothing silently degrades.

Full ladder: [BUDGET.md](./BUDGET.md).

---

## 4. Scenario C — "Did the overnight jobs run?"

Everything the bot mails runs at **09:30 Oxford time**, from one systemd
timer.

```bash
systemctl list-timers chatbot-morning.timer --no-pager
systemctl show -p ExecMainStatus --value chatbot-morning.service
```

```
NEXT                        LEFT  LAST                        UNIT
Wed 2026-09-02 13:30:00 UTC  20h  Tue 2026-09-01 13:30:01 UTC chatbot-morning.timer
0
```

`13:30 UTC` **is** 09:30 in Oxford — the box runs UTC and systemd does the
conversion, including daylight saving. `ExecMainStatus 0` means the last
run finished cleanly.

To see what it would do without sending anything:

```bash
sudo -u root bash /opt/chatbot/ai-core/scripts/morning_jobs.sh --dry-run
```

**It exits non-zero on a dry run and that is correct** — the jobs
underneath treat a suppressed send as a failed send.

**A morning with no data-health email means the job did not run**, not
that everything is fine. That report is sent every day, all-clear
included, precisely so its absence means something.

---

## 5. Scenario D — "A patron says it answered wrong"

You need the conversation before you need an opinion. Through the console
it is Conversations → the day → the turn. From the shell, when the
console is not available to you:

```bash
sudo -u root /opt/chatbot/ai-core/.venv/bin/python - <<'PY'
import os, sys, asyncio, logging
sys.path.insert(0, '/opt/chatbot/ai-core')
for line in open('/opt/chatbot/.env'):
    line = line.strip()
    if line and not line.startswith('#') and '=' in line:
        k, v = line.split('=', 1); os.environ.setdefault(k, v.strip().strip('"'))
logging.disable(logging.CRITICAL)
from src.database.prisma_client import get_prisma_client, connect_database

WORD = 'ebook'          # <- change this

async def go():
    await connect_database(); db = get_prisma_client()
    rows = await db.query_raw("""
      SELECT to_char(m."timestamp" AT TIME ZONE 'UTC' AT TIME ZONE
                     'America/New_York', 'MM-DD HH24:MI') AS t,
             m.type, left(m.content, 62) AS text
      FROM "Message" m WHERE m.content ILIKE $1
      ORDER BY m."timestamp" DESC LIMIT 10""", f'%{WORD}%')
    for r in rows:
        print(f"{r['t']}  {r['type']:<9} {r['text']}")
asyncio.run(go())
PY
```

```
08-30 20:41  assistant To find a specific book, article, journal, or DVD at Miami Uni
08-30 20:41  assistant I can point you to the right starting place:
08-30 20:41  assistant If this is a research question you should consult a librarian
```

### Then pick the cheapest layer that fixes it

**Most wrong answers are not the model's fault.** Roughly thirty
deterministic short-circuits answer the common questions by lookup before
any model runs, so the first question is *which layer produced this*.

| Layer | Use when | Cost | Who |
|---|---|---|---|
| **Correction** — `/admin/corrections/view` | The answer is wrong and you know what it should say | **live in 60s, no deploy** | any operator |
| **Corpus** — `/admin/etl` | A page on our website changed | rebuild, ~7 min of slower answers | operator signs |
| **Code** | The logic is wrong | deploy + restart | Meng / Rachel |

Try them in that order. A correction that solves it today buys time to do
the code fix properly, and corrections expire on their own after 180 days
so they do not silently become permanent.

---

## 6. Scenario E — "I want to deploy. Is anyone using it?"

A restart drops every open connection and the bot cannot answer for about
a minute.

**The number lives inside the running process**, so this only works
through the console — `/admin/` shows it at the top, and
`/admin/presence.json` returns it as JSON. Running `presence.snapshot()`
from a shell always prints zero, because a fresh Python process has its
own empty copy. That is a trap, not a reading.

> **Which means that today you cannot do this check at all.** The console
> needs a sign-in that does not work yet (§7), and there is no other way
> to read the number. Until SSO completes, deploying means picking a quiet
> hour and accepting the risk — or asking Meng to reopen the shared key
> for a minute. Say which one you did; do not record the check as done.

Three numbers, and they do **not** mean the same thing:

| | What a restart costs them |
|---|---|
| `waiting` | Their question is lost with nothing shown. **Wait.** |
| `in_conversation` | Their thread ends and the bot is unreachable ~60s. |
| `open` | Nothing — the widget reconnects on its own. |

Most open sockets are nobody: the widget connects when a library page
*loads*, so a background tab is in `open` and would not notice.

---

## 7. Scenario F — "I cannot get into the console"

**This is the expected state today, not a fault.** Single sign-on is
switched on and Miami IT has not finished configuring their side, and the
shared key has been switched off. So:

| | |
|---|---|
| `/admin/*` | redirects to Miami sign-in, which cannot complete yet |
| `/librarian/` | still works with the shared access code |
| `/admin/service` (stop button) | **always reachable, no credentials** |
| the chat widget | unaffected |

The stop button is deliberately outside all of this: it has to work when
the identity provider is the thing that is broken.

If the console is needed before SSO is finished, the shared key can be
switched back on — it is one line and a restart, not a deploy:

```
SSO_ALLOW_TOKEN_FALLBACK=true      # in /opt/chatbot/.env
sudo systemctl restart chatbot
```

That switch exists for exactly this. Ask Meng before flipping it.

---

## 8. How much to trust the rest of the docs

All **56** files under `docs/` were read and corrected on 1 September 2026.
This section is what you still need to know afterwards.

### The one that matters most: `programmer-guide/`

**Ten files, and its operational half was unusable until 1 September.** It
is not in `archive/`, the README lists it as a reference, and 00-INDEX
tells you to send 03-DEPLOYMENT to Rachel and 08-OPERATIONS to whoever is
on call. What was in it:

| | |
|---|---|
| the service name | `smartchatbot-backend`, five times. The unit is `chatbot.service`. |
| the deploy path | `/opt/chatbot/current/`, thirty times. It has never existed. |
| Weaviate's port | 8888. It is 8080. |
| the models | `gpt-5.4-mini` / `gpt-5.2`. Neither has been called in thirty days. |
| a healthy daily spend | "$5–30/day, concerning above $100". The students' purse is **$40 a month**. |
| the cron jobs | a file, a path and a script that none exist — and it omitted the backup, the watchdog, the budget guard and the 09:30 timer. |

All fixed. The reason it is called out here rather than left in the log:
**every command in `05-TROUBLESHOOTING.md` named the wrong service**, and
that is the file you open when production is down at 4pm. If you had
reached for it before today it would have failed on the first line and you
would have had no way to tell whether that meant the doc was wrong or the
box was.

### Still only partly true

| File | Where you stand |
|---|---|
| `04-SERVER-MONITORING.md` | Written 17 July. Cron jobs, probes and log paths are right; the mail schedule predates the 09:30 timer. Banner at the top. |
| `06-CORRECTION-TICKETS.md` | How a ticket works is accurate. Its URLs still say `?key=…`, which is switched off — see §7. |
| `librarian-services-truthtable-ask.md` | The *ask* is a 20 May draft and historical. **The mechanism is live** — `services_offered` is populated for all seven buildings and the bot still refuses rather than guesses. Do not dismiss it; an earlier banner did, wrongly. |
| The dated files, and everything in `archive/` and `eval/` | **History, deliberately left as written.** Each now says so on its first line. Do not follow them as procedure. |

### Two corrections worth knowing even if you never open the file

- **`SSO-REQUEST-TO-IT.md`** — the ticket we sent Miami IT states that we
  sign AuthnRequests. **We do not**, and never did: `SSO_SP_CERT` and
  `SSO_SP_KEY` are unset, so we have no signing key. If their side was
  configured to require it, that alone would explain why nobody has ever
  signed in. A corrected message is drafted in that file, unsent.
- **`OPS-BACKUP.md`** — named a Weaviate collection three rebuilds out of
  date. It now tells you to ask the box. **Treat any collection name
  written in any document the same way, including in this one.**

### What to do with all this

Do not read "corrected on 1 September" as "correct forever". The failure
mode here was never one big lie — it was thirty small paths that stopped
resolving while nobody was looking. Two habits are worth more than any
audit:

- **Check the box, not the doc**, for anything with a name in it — a
  collection, a port, a service, a path, a dollar figure.
- **When a documented command fails, suspect the document first.** It was
  right more often than the box was, this time.

Where two files disagree, [01-SYSTEM-OVERVIEW.md](./01-SYSTEM-OVERVIEW.md)
and this one win — they were measured, not remembered.

---

## 9. What has never been tested

Stated because the alternative is you finding out during an incident.

- **Single sign-on has never completed once**, end to end, by anybody.
- **The restore half of the backup.** Backups run nightly and verify
  their own dump; nobody has restored one into a running system.
- **The stop button in anger.** It has been tested; it has never been
  needed.
- **A corpus rebuild under real traffic.** Every `apply` so far has been
  at a quiet hour.
- **The corpus has no backup at all** — not an untested restore, an
  absent one. Weaviate's backup module is switched off on our container
  (`ENABLE_MODULES=` is empty), so the backup endpoint refuses the call.
  `07-DATA-PIPELINE.md` printed a command for it until 1 September; it
  returns 422. What protects you instead is that every `apply` builds a
  NEW collection and leaves the old ones: rolling back is
  `WEAVIATE_CHUNK_COLLECTION` plus a restart. That is a rollback, not a
  backup — it does not survive losing the disk.

[OPEN-WORK.md](./OPEN-WORK.md) carries the rest.

---

## 10. Who to ask

| | |
|---|---|
| Anything in this file | Meng first |
| The bot is down and Meng is not answering | Rachel — scenario A, then the stop button if it is answering *wrongly* rather than not at all |
| Money | Mike gets the emails automatically; the numbers are in scenario B |
| A page on our site is wrong in the bot | Ken and Jerry — scenario D, correction layer |

**When something is on fire, the order is: stop the bot, then work out
why.** A paused bot is not an outage — patrons get a real sentence
pointing at Ask Us. A bot confidently telling students the wrong opening
hours is worse than a bot that is politely unavailable.
