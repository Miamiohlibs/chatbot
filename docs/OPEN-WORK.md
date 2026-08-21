# Open work — answer quality

Written 2026-08-20, from scoring **206 distinct real questions** (66 browser
conversations, 8/05–8/19) against gold rewritten from scratch. Not from the
eval suite: these are the questions people actually typed.

Scored three times as fixes landed, every run hand-scored against the same
gold, the last two against production:

| | good | weak | bad |
|---|---:|---:|---:|
| 2026-08-20, before any of it | 140 | 24 | **42** |
| after the P0/P1 routing fixes | 159 | 27 | 20 |
| **2026-08-21, current** | **171** | **28** | **7** |

The 35 fixes in between were each verified in production, not in-process --
in-process runs silently lose LibCal credentials and the booking path, which
is trap 1 and 2 below.

The eval suite scores the same build around 82%. The two numbers measure
different things and both are true — gold is constructed, real traffic has
typos, half-sentences, pasted paragraphs and mid-flow fragments. **Real
traffic is the harder and more honest number.**

---

## 1. The subject-term list is deliberately incomplete

`src/router/data/subject_exclusive_terms.json` — 12 subjects, 81 terms, plus
18 for Special Collections. Sent to Kevin Messner for review 2026-08-20.

The operator's own view: **it is certainly not enough.** The liaisons page
carries ~75 subjects and this covers 12. Missing entirely: Biology,
Nursing, Physics, Engineering (four separate departments), Economics,
Sociology, Anthropology, Philosophy, Religion, the language subjects,
Kinesiology, Neuroscience, Statistics, Computer Science.

Expanding it is safe in the same way the first pass was: a term may only go in
if it cannot mean anything else in a library. Anything that doubles as
ordinary English stays out, and a test enforces that.

Reversible by design: strike a term, or set a subject's `status` to
`rejected`, and the behaviour goes with it. Rejected terms stay in the file
with a reason so the next person can see it was already turned down.

---

## 2. Twenty answers still wrong, in three groups

### The 7 that remain

| Question | What happens |
|---|---|
| "My laptop is broken. how long can I check one out" | answers the broken half, never the loan period |
| "I have a question about interlibrary loan" | refused on some runs, answered on others — nondeterminism |
| "What time does the Gardner-Harvey Library open on August 21, 2026?" | swallowed by an open booking flow from three turns earlier |
| "Does the Gardner-Harvey Library have historical materials about the MUM campus?" | clarification chip, no destination |
| "I need to correct a book title that I requested from ILL today" | refused as out of scope |
| "Where could I find records of past event contracts…" | the staff-privacy guard replaces a good answer, intermittently |
| "OneSearch page keeps saying 404 not found" | catalogue guidance, no route to report the broken page |

### Group B — boundary questions, needing an operator decision (5)

Not routing bugs. They are all "does this belong to the library at all".

| Question | Today |
|---|---|
| "I need to digitize a piece of music" | out of scope |
| "I need the closing stock price of P&G on Sept 11 2001" | out of scope |
| "Mozart Piano Sonata K331 sheet music" | out of scope → **should be fixed by the Music terms; not yet re-measured** |
| the alum's genealogy question | out of scope → **should be fixed by the SCUA route; not yet re-measured** |
| "OneSearch page says 404 not found" | catalogue guidance, no report route |

**OneSearch, since it came up:** it is the OLD name for the discovery search,
now Primo. There is no OneSearch page — three plausible URLs all 404. But the
Libraries' own `/research/instruction/videos/` page still lists two videos
titled "Use OneSearch to Find Books and Articles…" as plain text. A patron
reads that, searches for OneSearch, and hits a 404. **That is a website
problem as much as a bot problem.** The bot should recognise the old name,
give the working route, and offer the feedback form.

### Group C — structural, should not be patched one by one (7)

- **Booking flow**: three questions untestable in-process (`NotConnectedError`
  — booking writes through Prisma and a non-root process cannot reach the
  query engine). The four-turn flow works over a real socket. The invitation
  wording now arms the flow, verified at unit level, **never verified in
  production**.
- **Classifier edges**: "How can I find information on events at Gardner-
  Harvey" gets a clarification chip; the same question with the words "and
  news" is answered well. Two words apart, two different outcomes.
- **Context follow-ups**: "is it normally open on Sundays?" after an Art
  Library question answers about King. Full history was replayed, so this is
  real.
- **Synthesizer nondeterminism**: R087 (event contracts) and R133 (lost book)
  each answered correctly on some runs and refused on others — 2 of 3 for
  R133, measured. **Any single-run measurement carries ±1–2 questions of
  noise**, and one "fix" in the 2026-08-20 report was really a lucky run.

### Remaining singles (8) — all fixed 2026-08-20, awaiting production proof

cat/pets, room number read as a course code, "Wall street jornal", MakerSpace
contact, all-campus room question, broken laptop + loan period, noise
complaint, "nothing there about Hamilton".

---

## 3. Measurement traps that cost real time

Recorded because each one nearly produced a false report:

- **In-process runs need `.env`.** Without it every hours question fails and
  looks like a regression. 18 questions, nearly reported as broken.
- **In-process runs cannot book** (Prisma engine path is root-only).
- **Manual corrections do not load in-process** — 6 are active, all with
  `fireCount = 0`, so no effect on any measurement to date. Worth knowing
  separately: **six corrections have never once fired.**
- **Replay the WHOLE conversation, not one prior turn.** Replaying one turn
  produced two booking "bugs" that do not exist.
- **Verify a fact before calling an answer invented.** "Who is the AI
  librarian?" was scored wrong on the assumption there was no such subject.
  The liaisons page lists "Artificial Intelligence Center: Anna Shaw".

---

## 4. Not started

- Re-run all 206 against production after the current commits deploy.
- The five corrections that never fire — either fix their matching or retire
  them; a mechanism that has never worked is worse than none, because it
  looks like coverage.


---

## 5. Why the pre-commit check keeps blocking eval results

Per-question eval output contains the bot's ANSWERS, and those answers quote
subject-librarian names, emails and desk numbers. The data check sees contact
details in bulk and blocks the commit. **Its caution is correct by default and
you should not work around it.**

What the details actually are, checked 2026-08-21: exactly the contacts the bot
publishes to any student who asks who their subject librarian is — e.g.
`boehmemv@miamioh.edu, (513) 529-1726` appears verbatim in today's answers.
Work contact details the Libraries publish and the bot hands out by design. No
passwords, no reader records, no student identifiers.

So: not a leak, and also not something to keep adding to a public repository
for no reason. Six eval files committed between July and August already carry
them (4–30 occurrences each). Current runs are written to
`/opt/chatbot-private-data/eval-runs/` and the shape is gitignored.

If you need to commit an eval report, commit the summary, not the per-question
answers.
