# Developer Documentation

**Miami University Libraries Smart Chatbot**
**Last Updated:** 1 September 2026 — every file in this folder was read
and corrected on that date.

Everything in this folder describes the **current** system (the v2
rebuild — the only serving path since 2026-07-17). Anything describing
the retired v3.1 stack lives under [archive/](./archive/).

## Current docs — describe the system as it is now

| Doc | What it covers |
|---|---|
| [01-SYSTEM-OVERVIEW.md](./01-SYSTEM-OVERVIEW.md) | **Start here.** The whole system: what runs, one turn end to end, data stores, who can reach what, the schedule, the money. Chinese: [01-SYSTEM-OVERVIEW.zh.md](./01-SYSTEM-OVERVIEW.zh.md) |
| [09-TEAM-MAINTENANCE-GUIDE.md](./09-TEAM-MAINTENANCE-GUIDE.md) | **If you are on the team, start here instead.** Six scenarios, every command run on the box with its real output |
| [02-ENVIRONMENT-VARIABLES.md](./02-ENVIRONMENT-VARIABLES.md) | Every env var: model tiers, Springshare APIs, alerts, admin secrets |
| [03-SUBJECT-LIBRARIAN-SYSTEM.md](./03-SUBJECT-LIBRARIAN-SYSTEM.md) | Subject → librarian data layer (Postgres tables, course codes, fuzzy match) |
| [05-DEPLOYMENT-GUIDE.md](./05-DEPLOYMENT-GUIDE.md) | build.sh flow, schema changes, post-deploy checks, host-level pieces |
| [06-CORRECTION-TICKETS.md](./06-CORRECTION-TICKETS.md) | Librarian "wrong answer" report form + operator queue |
| [07-DATA-SOURCES.md](./07-DATA-SOURCES.md) | **Which single source owns each fact** (people, subjects, hours, corrections) + known data gaps |
| [08-WEBSITE-UPDATES-INTO-THE-BOT.md](./08-WEBSITE-UPDATES-INTO-THE-BOT.md) | For the web team: getting site changes into the bot, no terminal needed |
| [BUDGET.md](./BUDGET.md) | The spend ladder, the purses, and what happens at each rung |
| [OPS-BACKUP.md](./OPS-BACKUP.md) | Database backup: what runs, where it lands, how to restore |
| [OPEN-WORK.md](./OPEN-WORK.md) | Known failures after the real-traffic review, and the five measurement traps |
| [HANDOVER.md](./HANDOVER.md) | The **state** of things: numbers, what is unfinished, who to ask. Operating instructions live in 09 |
| [SSO-REQUEST-TO-IT.md](./SSO-REQUEST-TO-IT.md) | The Miami IT ticket, its outstanding correction, and where sign-on stands |
| [AWS-CAPACITY-REQUEST.md](./AWS-CAPACITY-REQUEST.md) | The memory measurements behind asking for a bigger box |
| [NOTES.md](./NOTES.md) | Loose ends: the Ask Us widget snippet, odds and sods |

### Partly superseded

| Doc | Trust it for | Not for |
|---|---|---|
| [04-SERVER-MONITORING.md](./04-SERVER-MONITORING.md) | the cron jobs, probes, log locations | the mail schedule — written 17 July, predates the 09:30 timer and the daily digest |
| [librarian-services-truthtable-ask.md](./librarian-services-truthtable-ask.md) | nothing operational | 20 May; predates the current subject-librarian system |

## Dated records — history, not instructions

Accurate for the day they were written. Read them to learn *why* something
is the way it is; do not follow them as procedure.

- [MAINTENANCE-2026-07-17-overnight.md](./MAINTENANCE-2026-07-17-overnight.md) — the post-legacy-removal audit
- [HANDOFF-2026-07-29-overnight.md](./HANDOFF-2026-07-29-overnight.md) — one night's work
- [STUDENT-SIM-2026-07-30.md](./STUDENT-SIM-2026-07-30.md), [REPORT-pre-launch-testing-2026-07-30.md](./REPORT-pre-launch-testing-2026-07-30.md) — pre-launch testing
- [FINDING-compound-questions-2026-07-30.md](./FINDING-compound-questions-2026-07-30.md) — why compound questions fail
- [STUDENT-TEST-2026-07.md](./STUDENT-TEST-2026-07.md) — the 10-question acceptance test and its rubric

## Deeper / adjacent

- [../README.md](../README.md) — repo-level entry point
- [../ai-core/docs/OPERATOR.md](../ai-core/docs/OPERATOR.md) — operator runbook (endpoints, day-to-day tasks, alerts)
- [../ai-core/docs/eval/](../ai-core/docs/eval/) — dated eval reports, triage docs, gold-hygiene history
- [programmer-guide/00-INDEX.md](./programmer-guide/00-INDEX.md) — architecture deep-dive written during the rebuild

## Archive (historical — do NOT follow for the current system)

- [archive/legacy-v31/](./archive/legacy-v31/) — v3.1-era docs: old system
  overview, setup guide, Weaviate-as-correction-pool design, clarification
  buttons, old deployment guide/checklist, router refactor design, the
  watchdog-based monitoring doc
- [archive/reports/](./archive/reports/) — dated snapshots: accuracy audit,
  beta readiness, June deploy reports
- [eval/2026-05-22-wired-baseline/](./eval/2026-05-22-wired-baseline/) — the
  original eval-baseline archive

## Quick starts

**Deploy a change**: [05-DEPLOYMENT-GUIDE.md](./05-DEPLOYMENT-GUIDE.md)
**A librarian reports a wrong answer**: [06-CORRECTION-TICKETS.md](./06-CORRECTION-TICKETS.md)
**Alerts stopped / server questions**: [04-SERVER-MONITORING.md](./04-SERVER-MONITORING.md)
**New developer orientation**: 01 → programmer-guide → OPERATOR.md

---

**Developer:** Meng Qu, Miami University Libraries
