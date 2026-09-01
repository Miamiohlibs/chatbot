# Developer Documentation

**Miami University Libraries Smart Chatbot**
**Last Updated:** 1 September 2026 — every file in this folder was read and
corrected on that date, and everything that had been superseded was moved
into [archive/](./archive/).

Sixteen files at this level. All of them describe the system as it runs
today. Nothing here is history — history is in `archive/`, and it says so
on its first line.

> The numbering skips 03. That file was retired, and renumbering the rest
> would break every reference anybody has ever pasted into a ticket. A gap
> is cheaper than a renumber.

## Start here

| | |
|---|---|
| **You are on the team and something needs doing** | [09-TEAM-MAINTENANCE-GUIDE.md](./09-TEAM-MAINTENANCE-GUIDE.md) — six scenarios, every command run on the box with its real output |
| **You want to understand the whole thing** | [01-SYSTEM-OVERVIEW.md](./01-SYSTEM-OVERVIEW.md) · 中文 [01-SYSTEM-OVERVIEW.zh.md](./01-SYSTEM-OVERVIEW.zh.md) |
| **You are taking it over** | [HANDOVER.md](./HANDOVER.md) — the state of things: numbers, what is unfinished, who to ask |
| **You are a developer** | [programmer-guide/00-INDEX.md](./programmer-guide/00-INDEX.md) |

## Reference

| Doc | What it covers |
|---|---|
| [02-ENVIRONMENT-VARIABLES.md](./02-ENVIRONMENT-VARIABLES.md) | Every variable the code actually reads. The template is generated from the running `.env`. |
| [04-SERVER-MONITORING.md](./04-SERVER-MONITORING.md) | systemd, alerts, the four probe URLs, the two schedulers, logs |
| [05-DEPLOYMENT-GUIDE.md](./05-DEPLOYMENT-GUIDE.md) | build.sh, schema changes, post-deploy checks |
| [06-CORRECTION-TICKETS.md](./06-CORRECTION-TICKETS.md) | The "wrong answer" report form and the operator queue |
| [07-DATA-SOURCES.md](./07-DATA-SOURCES.md) | **Which single source owns each fact.** Read before touching people, subjects or building data. |
| [08-WEBSITE-UPDATES-INTO-THE-BOT.md](./08-WEBSITE-UPDATES-INTO-THE-BOT.md) | For the web team. No terminal needed. |
| [BUDGET.md](./BUDGET.md) | The $100 ceiling, the two purses, what happens at each rung |
| [OPS-BACKUP.md](./OPS-BACKUP.md) | Database backup and restore — and why the corpus has neither |
| [OPEN-WORK.md](./OPEN-WORK.md) | Known failures from the real-traffic review, and five measurement traps |
| [SSO-REQUEST-TO-IT.md](./SSO-REQUEST-TO-IT.md) | The Miami IT ticket, its outstanding correction, where sign-on stands |
| [AWS-CAPACITY-REQUEST.md](./AWS-CAPACITY-REQUEST.md) | The memory measurements behind asking for a bigger box |
| [NOTES.md](./NOTES.md) | Loose ends: the Ask Us widget snippet |

## Elsewhere

- [../ai-core/docs/OPERATOR.md](../ai-core/docs/OPERATOR.md) — operator runbook
- [../ai-core/docs/eval/](../ai-core/docs/eval/) — dated eval reports and gold-hygiene history
- [archive/](./archive/) — **historical. Do not follow it for the current
  system.** Retired docs, dated one-night records, the v3.1 stack, and the
  May 2026 eval baseline. Every file in there says so on its first line.

---

**Developer:** Meng Qu, Miami University Libraries
