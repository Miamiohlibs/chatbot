# Smart Chatbot — team maintenance guide

**Who this is for:** Ken and Jerry (web + content), Rachel (backend),
Mike (spend). Everything here is done in a browser, on the admin
dashboard. Nothing needs a server login unless a section says so.

**Where it lives:** <https://chatbot.lib.miamioh.edu/admin/>

**How you get in:** every admin URL needs `?key=<ADMIN_API_TOKEN>` on the
end. Ask Meng for the key and bookmark the dashboard *with* the key in
it — the links on the page carry it forward for you after that.

SSO for named accounts (qum, bomholmm, maderir, irwinkr, yarnete) has been
approved by IT but is **not connected yet**. Until it is, the key is the
only thing standing between the internet and this console: treat it like a
password, and do not paste it into a ticket or a shared doc.

Written 2026-08-27. If something here does not match what you see, the
page is right and this document is stale — tell Meng.

---

## Two consoles, not one

Since 2026-08-30 there are two.

**`/librarian/`** — for subject librarians. The report form, and the real
questions patrons asked. Nothing else: no spend, no stop button, no
rebuild. This is the link to hand out.

**`/admin/`** — for the five of us. Everything above, plus every
conversation *including our own testing*, the corpus gate, the cost
dashboard, the stop button and the audit log.

The split is by SSO account, so it needs two lists in `/opt/chatbot/.env`:

```
SSO_ALLOWED_UIDS=qum,bomholmm,maderir,irwinkr,yarnete   # operators (existing name, unchanged)
SSO_LIBRARIAN_UIDS=<the Advise & Instruct department>   # 12 subject librarians
```

The librarian list is **derived, not typed**: `staff-members.csv`,
`department == advise-instruct` — the same set the website's
"Advise & Instruct" filter shows. Re-derive it when somebody joins or
leaves rather than editing it by hand; the one-liner is in
[02-ENVIRONMENT-VARIABLES.md](./02-ENVIRONMENT-VARIABLES.md).

`SSO_ALLOWED_UIDS` still means "operators" — nothing to rename. Adding a
uid to `SSO_LIBRARIAN_UIDS` gives that person the librarian console and
nothing more. Somebody on both lists is an operator; the wider role wins,
so putting yourself on the librarian list to see what they see does not
quietly cost you the stop button.

**Until Miami IT finishes the SSO configuration none of this is live.**
Everyone arrives on the shared `?key=`, which is treated as an operator
and is asked for a passphrase — exactly as before. See "Passphrases"
below.

### Passphrases

Signed in through Miami SSO, the dangerous actions no longer ask for a
shared passphrase. Your identity came from the IdP, and what the action
is recorded against is your Miami account.

Arriving on the shared key, they still do. That key says nothing about
who you are, so a log line naming you would be worth nothing — and it is
also the path everybody falls back to if the IdP is down.

The foot of the sidebar always says which of the two you are on.

### The audit log

`/admin/audit` — every corpus rebuild, every send-back, and every use of
the stop button, newest first. Lines done with the shared key are marked
`unverified`, because the name on those is whatever was typed into the
form.

It is a file, not a database table: `ai-core/data/audit/actions-YYYY-MM.jsonl`.
That is deliberate — it is read after exactly the events that take the
database away. `tail -f` works when the console does not.

---

## Start here: the dashboard

`/admin/` is a hub of cards, grouped by what you came to do:

| Card | What it is | Mostly for |
|---|---|---|
| **Conversations by day** | Every conversation, one day or a date range | Ken, Jerry |
| **Search** | One keyword across every conversation ever held | everyone |
| **What went wrong** | Refusals, thumbs-down, low-confidence answers | Ken, Jerry, Rachel |
| **Correction tickets** | Staff reports of wrong answers, worked to done | Ken, Jerry |
| **Manual corrections** | Suppress / reword / pin a source, live, no deploy | Rachel |
| **Service control** | The stop button | Rachel |
| **Cost dashboard** | Daily spend, by model, all-time | Mike |
| **Health checks** | Dependency probes and an end-to-end smoke test | Rachel |
| **Corpus review** (`/admin/etl`) | Website updates into the bot | Ken, Jerry |
| **Audit log** (`/admin/audit`) | Who rebuilt the corpus, who stopped the bot | everyone |

---

## Ken and Jerry — web and content

Your two questions are *"is the bot saying the right thing about our
pages?"* and *"how do I get our updates into it?"*

### Getting website updates into the bot

Full instructions are in **[08-WEBSITE-UPDATES-INTO-THE-BOT.md](08-WEBSITE-UPDATES-INTO-THE-BOT.md)**.
The short version, at `/admin/etl`:

1. **Fetch the latest site content** — re-reads our public site, under a
   minute, costs nothing, changes nothing the bot is using yet.
2. **Read the report.** The section to actually read is **"Would be lost
   outright"** — a page you still need appearing there is the thing to
   catch. Everything else is usually routine.
3. **Approve, and make it live** — or **send it back** with a note if
   something is wrong.

Approving starts the rebuild immediately: **about seven minutes, during
which answers slow from ~7 seconds to ~25 seconds.** The bot keeps working
and keeps answering correctly from the old pages the whole time. If now is
a bad moment, come back later — the report waits.

### Checking what the bot actually said

**Search** (`/admin/search`) — one keyword across every conversation. You
can narrow it to *what patrons typed* or *what the bot said*; those are two
different questions. "Did anyone ask about Zotero?" and "did we ever tell
somebody the wrong loan period?" need different halves of the transcript.

**Conversations by day** (`/admin/conversations`) — pick a day, or a date
range with the *from / to* boxes. Tick **"only what went wrong"** to see
just the conversations with a refusal, a thumbs-down, or a low-confidence
answer. You can also filter to one of those on its own.

Each row shows the first question, how many were asked, what the bot
classified it as, and the patron's star rating and comment if they left
one. Click through for the full transcript, including which pages the
answer cited.

### When the bot says something wrong about your pages

Two ways, and the difference matters:

- **The page itself is wrong or out of date** → fix the page, then use
  *Fetch* above. The bot only knows what the website says.
- **The page is right and the bot got it wrong** → file a correction
  ticket.

**Filing a ticket the easy way:** open the conversation, find the bad
answer, click **"Report this answer"** underneath it. The form arrives
prefilled with the question and the answer, and — this is the part that
matters — the ticket keeps a link back to the conversation, so whoever
picks it up can see the whole exchange rather than a retyped summary.

The bare form at `/librarian/ticket` is for something a patron told you at
the desk, where there is no conversation to link.

**Working the queue** at `/admin/tickets/view`: filter by Open / In
progress / Done. Opening a ticket shows the transcript it came from, how
many times that same question has been asked, and a form to write a
correction that takes effect on the next message with no deploy.

---

## Rachel — backend

### Is it up?

- **`/health/ready`** and **`/smoketest`** are public, no key. Point an
  external monitor at them.
- **`/admin/`** shows service state at a glance.
- **A daily digest email lands at 13:30 UTC (9:30am Oxford)** and is sent
  *every day, pass or fail*. A morning with no mail means the cron is
  broken, not that everything is fine — that is deliberate. It covers:
  dependencies, memory and OOM kills, the librarian roster, stale subject
  links, what real patrons disliked in the last 24h, corpus age, and
  LibCal entries that cannot be true.

### The stop button

**Service control** (`/admin/service`). Pausing does **not** kill the
process — the bot keeps answering, with a maintenance notice, so the
widget never shows a broken page. It survives a restart, and recovery is
one click. Use it when something is badly wrong and you need it to stop
saying things while you look.

### Fixing an answer without a deploy

**Manual corrections** (`/admin/corrections/view`). Four kinds:

| Action | What it does | Use it when |
|---|---|---|
| `suppress` | Drops one chunk from retrieval | A passage is wrong or out of context |
| `replace` | Substitutes librarian-written text for a chunk | The page is right but reads badly |
| `pin` | Boosts one chunk to the top for matching questions | The right page exists but ranks low |
| `blacklist_url` | Drops a whole page | A stale page keeps surfacing |

Two things to know:

- **A `pin` boosts, it does not inject.** If retrieval never returns that
  chunk, pinning it does nothing at all. Check the conversation's cited
  sources first — if the page you want is not there, a pin will not help
  and the fix is elsewhere.
- **Corrections expire after 180 days, on purpose**, so nobody inherits a
  rule nobody remembers. When one lapses the old behaviour returns. That
  is the reminder to fix the underlying page.

The **fire count** column tells you which rules are actually doing
anything. It was broken until 2026-08-27 and showed 0 for everything, so
**ignore any count from before then** — it means "not measured", not
"never fired".

### The parts that need a shell

Only these:

- Deploying code (`git pull && bash build.sh`, then restart)
- Restoring a database backup (nightly at 03:30 UTC)
- Anything in `scripts/`

Corpus refresh does **not** need a shell any more — see Ken and Jerry's
section. That was the point of building it.

---

## Mike — spend

**Cost dashboard** (`/admin/cost`), and `/admin/cost.json` if you want to
pull it into a spreadsheet.

It shows spend by day with the number of turns, every model ever used with
its all-time total, and the rate card in dollars per million tokens. Cost
is rolled up nightly at 02:00 UTC.

What moves the number:

- **Traffic.** Cost is roughly per answer, so a busy week costs more.
- **Which model answers.** The rate card shows the spread. A change of
  default model moves the total far more than a change in traffic.
- **Corpus rebuilds.** Each one re-embeds the changed pages. Fetching a
  diff is free; approving one is not. Now that Ken and Jerry can approve
  without waiting for anyone, expect this to happen more often than the
  old once-a-week-if-someone-remembered rhythm — a line item that used to
  be rare is now routine, and that is the change to watch for.

If a day looks wrong, `/admin/conversations` for that day tells you
whether it was traffic or something else.

---

## Things everyone should know

**The bot is a navigator, not an encyclopedia.** It is built to send
people to the right page, not to memorise the site. If an answer is wrong,
the first question is almost always *"what does the page say?"* — not
*"what should the bot know?"*

**It will not answer from memory about the building.** Floor numbers,
lifts, toilets: if no page says it, it sends the patron to the front desk
rather than guessing. That is an operator ruling from 2026-08-17, not a
gap.

**Some pages say two different things.** Where our own website contradicts
itself, somebody has had to pick a side, and that decision is recorded in
`docs/OPEN-WORK.md`. If you find a fresh contradiction, that file is where
it should be written down — fixing the pages is better than teaching the
bot which page to believe.

**Star ratings and comments are patron feedback**, and they are the only
signal in the console that comes from the person who was actually helped
or not. There are not many — a few dozen — so each one is worth reading.
They show inline on the conversation rows, and you can filter to them.

---

## Who to ask

| Problem | Ask |
|---|---|
| A page in the corpus is wrong or missing | Ken, Jerry |
| The bot is down, slow, or saying something alarming | Rachel |
| The spend looks wrong | Mike |
| Anything about how the bot decides what to say | Meng |
| You need the admin key | Meng |

**If the bot is saying something harmful, do not wait for anybody.** Open
`/admin/service` and pause it. It is one click, it is reversible, and the
widget stays up with a maintenance notice. Then tell the group.
