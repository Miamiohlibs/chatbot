# Getting website updates into the bot

**For the library web team.** Nothing here needs a server login, a
terminal, or anybody from the dev side.

Written 2026-08-27, when the web team asked for a way to do this themselves
after their Saturday content updates.

---

## The short version

Three things happen, in order, on one page — **`/admin/etl`**:

| | What it does | How long |
|---|---|---|
| **1. Fetch** | Re-reads our public website and writes a report of what changed | under a minute |
| **2. Read + sign** | You check the report and put your name to it | as long as you like |
| **3. It goes live** | Starts by itself the moment you sign | about seven minutes |

You need the shared passphrase and your `@miamioh.edu` address. The same
two the page already asks for.

---

## What each step actually does

### 1. Fetch the latest site content

Re-crawls our own public pages (about 410 of them) and writes a **diff
report** — what is new, what changed, what would be dropped.

It is safe to press. It costs nothing, and it does not touch what the bot
is currently answering from. Press it whenever you want a fresh picture.

One thing to know: it **replaces the report anybody else is currently
reading**. If a colleague is mid-review, let them finish.

### 2. Read the report, then sign

Two sections are worth your time before anything else:

- **Summary** — how many pages and chunks changed.
- **Would be lost outright** — this is the column to read. *A page you
  still need appearing in this list is the thing to catch.* Everything
  else is usually routine.

Then either:

- **Approve, and make it live** — you have read it and it should ship.
- **Send back without approving** — something is wrong, and you want it
  looked at. Say what, and name the pages. Nothing is applied.

- **Send back *and* stop crawling the pages I named** — for the common
  case: a page is being indexed that should not be. Those pages are
  skipped from the next fetch onward, with your name and your reason on
  the record.

  This does **not** change anything readers see on its own. Fetch again,
  read the new diff without those pages, and sign — the same three steps
  as always.

  Everything you have excluded is listed at the top of the page, and
  **putting a page back is one click**. It is meant to be easy to undo:
  hesitating is how a page that should not be in the corpus stays in it.

  One page at a time, by its full address. You cannot exclude a whole
  section this way — `/use/` would quietly take a quarter of the corpus
  with it, and a form is not a place to make a decision that big. If you
  really do need a whole section gone, that is a conversation with
  whoever maintains the crawl config.

You have to tick the box saying you read it. That is deliberate: your name
goes on the record, and it should only go on something you actually looked
at.

### 3. It goes live by itself

Approving starts the rebuild immediately. **This is the part with a real
cost, so it is worth understanding:**

- It takes **about seven minutes**.
- While it runs, the bot's answers slow from about **7 seconds to about
  25 seconds**. Those are measured numbers, not guesses.
- **The bot keeps working the whole time**, and keeps answering
  *correctly* — from the OLD pages, until the new ones land.
- When it finishes, the bot switches over on its own. Nothing to restart,
  nothing to run on the server.

If right now is a bad moment — a class visit, a busy afternoon — just come
back later. **The report waits.** Approving on Monday works exactly as
well as approving on Saturday.

Reload the page to see progress. It tells you what is running, how long it
has been going, and — if something goes wrong — what went wrong, on the
page, not buried in a log on the server.

---

## Questions you might have

**Do I have to do this every week?**
No. A crawl also runs by itself every Monday at 06:10 and emails the
maintainer if anything changed. The button is for when you do not want to
wait for Monday — which, after a Saturday update, is most of the time.

**What if I approve something by mistake?**
The old pages are not deleted. Fetch again and approve the corrected
report; seven minutes later the bot is back on the right content. Tell the
maintainer either way.

**Can two of us do this at once?**
No, and the page will say so rather than letting it happen. The machine is
small, and two rebuilds at once would take the bot down.

**Why does it take seven minutes?**
Every changed page has to be re-read and converted into something the bot
can search. That conversion is the slow part, and it is why the bot is
sluggish while it happens.

**Something failed and I do not understand the message.**
Copy what the page shows and send it to the maintainer. The page
deliberately shows the real error rather than "something went wrong",
because the real error is the part that gets it fixed.

---

## For whoever maintains this

The three phases are `scripts/etl/run_etl.py --phase prepare|apply|promote`
and the console runs exactly those, through `src/api/admin/etl_jobs.py`.
Nothing is duplicated, so the CLI stays the fallback.

Two constraints are load-bearing and are not decoration:

- **`apply` always runs under a memory cap** (`MemoryMax=1100M`). This is a
  t4g.medium with 3,823 MB. Uncapped, the reindex pushes the serving
  process into swap and patrons get *no answer within 30 seconds* — while
  `systemctl is-active` still reports `active`. Measured; see
  `AWS-CAPACITY-REQUEST.md`. Raising that cap is how you cause an outage
  that looks like a Weaviate problem.
- **One job at a time**, enforced by a module-level lock. A prepare racing
  an apply signs one report and applies a different one.

Promotion needs no restart because every read of the collection name on
the serving path is an `os.getenv` at request time. `promote_in_process()`
sets it in the live process; the `promote` phase also writes `.env` so a
later restart comes back to the same place. If either of those two stops
being true, the button silently stops working — a test covers each.
