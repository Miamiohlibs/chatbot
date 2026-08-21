# Handover — Miami University Libraries Smart Chatbot

**For:** Rachel (admin surfaces) · 小马哥 (oversight) · Ken (engineering)
**Written:** 2026-08-21 · **Live since:** 2026-08-13 18:00 EDT

Every number in this document was read out of the running system or the
database on 2026-08-21. Where something is unmeasured, unknown or broken, it
says so. Nothing here is estimated unless the word "estimate" appears.

---

## 1. What it is, in one paragraph

A chat widget on the Libraries' website that answers questions about hours,
locations, borrowing, study rooms, subject librarians, printing, interlibrary
loan, the MakerSpace and Special Collections. It is deliberately built as a
**navigator, not an answer generator**: anything that would mean searching the
catalogue, a database or Primo is *routed to the right place*, never answered.
That is a decision by the subject librarians, and it is the single most
important thing to preserve.

---

## 2. How a question is actually answered

Five stages. Most questions stop before the LLM.

| # | Stage | LLM? | What it does |
|---|---|---|---|
| 1 | **Scope** | no | Which campus and building the question is about. Falls back to Oxford/King. |
| 2 | **Intent** | no | Nearest-neighbour match against 5,645 real example questions. |
| 3 | **Short-circuits** | **no** | About 70 hard-coded answers for facts we know exactly — hours, addresses, phone numbers, loan periods, policy pointers. **Zero cost, cannot hallucinate.** |
| 4 | **Agent** | yes | Only if nothing above matched. Calls tools: LibCal hours, room booking, librarian lookup, website search. |
| 5 | **Post-processor** | no | Checks every citation. Can throw the answer away and refuse instead. |

**Why this matters for trust:** a large share of answers never reach a
language model at all. When you see `model: (none -- close_today_short_circuit)`
on a ticket, that answer was produced by code, not by a model, and it is
reproducible.

---

## 3. The numbers, including the bad ones

### Real usage since launch

| | |
|---|---|
| Real (browser) conversations | 66 |
| Answers in them | 265 |
| Thumbs up / down / unrated | **10 / 12 / 243** |
| Correction tickets filed by librarians | 4 |

**More thumbs-down than thumbs-up.** The sample is tiny — 22 of 265 answers
were rated at all — so it is not a quality measurement, but it is not
flattering either and should not be presented as if it were.

### Two quality numbers, and why both exist

| Measured against | Result | What it is good for |
|---|---|---|
| **Gold set** — 234 constructed test cases, LLM judge | 82.1% judged correct (2026-08-18) | Catching regressions. Comparable run to run. |
| **Real traffic** — 206 distinct questions people actually typed, scored by hand | **171 good / 28 weak / 7 bad** (2026-08-21) | What a patron actually experiences. |

They measure different things. Gold is constructed and clean; real traffic has
typos, half sentences, pasted paragraphs and mid-conversation fragments. **The
real-traffic number is the honest one**, and on 2026-08-20 it started the day
at 140 good / 42 bad. The improvement came from fixing 35 specific routing
faults, each verified in production.

### Cost, month to date

| | |
|---|---|
| **Total** | **$15.72** |
| — evaluation runs | $7.04 |
| — scripted testing (no browser) | $5.92 |
| — **real users** | **$2.76** |
| Monthly purse for serving | $45.00 |

Real student traffic is costing about **6% of its budget**. Most of this
month's spend is us testing it.

---

## 4. Who can do what

### Rachel — admin surfaces, no code

| You can | Where |
|---|---|
| Read every conversation, with intent, scope, confidence, citations and which links were shown | `/admin/review` |
| See which model answered — or that **no model did** | the model chip on each ticket |
| Work the correction queue when a librarian reports a wrong answer | `/admin/tickets/view` |
| See spend by day and by model | `/admin/cost` |
| **Pause the bot** and bring it back | kill switch, below |

All admin routes need `ADMIN_API_TOKEN`. **The token travels in the URL query
string, so it is written to the web-server access log** — checked on
2026-08-21: `key=` appears 203 times in the current log. It is not a secret
once it has been used. Treat it as rotatable, and do not paste an admin URL
into a ticket or an email.

### Ken — engineering

Everything Rachel can do, plus the code. Read in this order:

1. `docs/programmer-guide/00-INDEX.md` — architecture
2. `ai-core/src/graph/new_orchestrator.py` — the turn pipeline. Long, and
   heavily commented: nearly every rule carries the date and the real question
   that caused it. **Read the comments before changing a matcher.**
3. `docs/OPEN-WORK.md` — what is still wrong and the traps in measuring it

### 小马哥 — oversight

The decisions that are yours, not the code's:

- **Scope.** Whether the bot may ever answer holdings questions rather than
  routing them. Today it may not, by the librarians' decision.
- **Budget.** The ladder tightens the bot's behaviour as spend rises and can
  stop it entirely. Current purses: serving $45/month, evaluation $75/month.
- **The subject-referral vocabulary.** A list of terms that let the bot
  volunteer a subject librarian. It is with Kevin Messner for review.
- **Staff testing.** Testing traffic is now the majority of spend and it
  pollutes the quality sample. It needs a convention.

---

## 5. What you can change without a developer

| Change | How | Takes effect |
|---|---|---|
| Correct a wrong answer | Correction ticket in the admin UI | next question |
| Pause / resume the bot | kill switch | immediately |
| Subject-librarian referral vocabulary | `ai-core/src/router/data/subject_exclusive_terms.json` — set a term's subject to `status: "rejected"` | next restart |
| Who gets alert emails | `ALERT_*` in `.env` | next restart |
| Budget ceilings | `BUDGET_*` in `.env` | next restart |

---

## 6. What you must not do

1. **Do not let it answer "do we have X?"** It has no catalogue access. Every
   such answer would be a guess wearing a citation.
2. **Do not add everyday words to the subject-term list.** `business`, `art`,
   `design`, `health` are subject names *and* ordinary English. A test fails
   if anyone adds one; that test is the guard rail, not a formality.
3. **Do not run the full test suite or the full eval in one process on this
   host.** 4 GB of RAM, of which the service holds about 1.0 GB and roughly 0.9 GB is free. The full eval
   hangs; the full test suite has been OOM-killed. Run the eval per category
   (`ai-core/scripts/run_eval_safely.sh`) and the tests in halves.
4. **Do not trust one measurement run.** The LLM path is not deterministic:
   the same question has answered correctly twice out of three tries and
   refused on the third. A one-case difference is noise, not a trend.
5. **Do not commit anything under `docs/eval/` that contains answer text.**
   Bot answers quote librarian names, emails and desk numbers, and this
   repository is public. The pre-commit hook blocks it; do not use
   `--no-verify` to get around it.

---

## 7. Five things that will bite you when you measure it

Each of these produced a wrong conclusion during the 2026-08-20 review before
it was caught:

1. **Running the bot in-process without loading `.env`** — every hours
   question fails and looks exactly like a code regression. 18 questions were
   nearly reported as broken this way.
2. **Running it in-process as a non-root user** — room booking cannot reach
   the database engine and errors out. Those are not failures.
3. **Replaying one prior turn instead of the whole conversation** — invented
   two booking bugs that did not exist.
4. **Testing with a paraphrase of the question instead of the real text** —
   a fix looked verified when the actual patron wording still failed.
5. **Judging an answer wrong from intuition** — "Who is the AI librarian?"
   was scored as a hallucination until the liaisons page turned out to list
   *Artificial Intelligence Center: Anna Shaw*. Open the page first.

---

## 8. If something breaks

| Symptom | Do this |
|---|---|
| Bot answering nonsense, or a bad deploy | **Pause it**: the kill switch, or `touch /opt/chatbot/ai-core/data/SERVICE_PAUSED`. Users then see an out-of-service notice instead of answers, and the three big buttons show it too. |
| Service down | A watchdog checks every 5 minutes and restarts it. systemd also restarts on failure. |
| Need yesterday's data | Backups run nightly at 03:30 to `/opt/chatbot-private-data/backups/` — **12 dumps** on hand, most recent `smartchatbot-20260820-033001.dump`. Restore procedure: [OPS-BACKUP.md](./OPS-BACKUP.md). |
| Dependency down (Weaviate, Postgres, LibCal, OpenAI) | Email alerts are configured and have been verified working. |
| Spend climbing | `/admin/cost`, and the budget guard runs every 15 minutes. |

**Deploy**, after pushing to GitHub:

```bash
cd /opt/chatbot && sudo git push origin main && sudo systemctl restart chatbot \
  && sleep 30 && bash ai-core/scripts/post_deploy_check.sh
```

The push needs `sudo` — the GitHub deploy key belongs to root, not to your
user. The post-deploy check holds a **two-turn** conversation on purpose: a
past failure only appeared on the second message, so a single-turn smoke test
passed while every real user was broken.

---

## 9. What is unfinished

Full detail in [OPEN-WORK.md](./OPEN-WORK.md). The short version:

- **7 of 206 real questions still answer badly.** Named, with causes.
- **The subject-referral vocabulary covers 12 of ~75 subjects.** Deliberately
  started small; Biology, Nursing, Physics, Engineering and the languages are
  all still missing.
- **The LLM path is nondeterministic.** Until that is understood, every
  quality number carries about ±2 questions of noise.
- **Six manual corrections have never fired once.** A mechanism that has never
  worked is worse than none, because it looks like coverage.
- **Four budget-ladder tests have never run against the deployed
  configuration.** They were written against the default purses.
- **Never tested:** a real screen reader, the widget embedded on the live
  library page, a dependency dying mid-conversation, session continuity after
  a refresh, more than ~40 concurrent users.

---

## 10. The honest summary

It is good at what it was built for: hours, locations, people, policies,
borrowing, room booking, and pointing people at the right page. On the 206
real questions people actually asked, 171 are answers a librarian would let
stand.

It is not a reference librarian and was not built to be one. Ask it whether
the library holds a particular book and the best it can do — by design — is
tell you where to look.

The failures that remain are known, written down, and each has a name and a
cause. That is the part worth trusting: not that it is always right, but that
where it is wrong, we can say exactly how and why.
