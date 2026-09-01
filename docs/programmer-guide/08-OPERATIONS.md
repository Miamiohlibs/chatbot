# 08 — Operations

> Ongoing care and feeding. Monitoring, librarian-facing workflows, scheduled jobs, weekly digests.

## What ops looks like, day to day

The bot is mostly self-running. The work you do is:
1. **Watch monitoring** — Sentry alerts, smoketest pinger, cost rollups
2. **Process librarian feedback** — when a librarian flags a wrong answer, file a `ManualCorrection`
3. **Maintain the weekly ETL** — review the diff before it auto-applies
4. **Rotate credentials** — periodic OpenAI / LibCal / LibGuides key refresh
5. **Re-run eval** when prompts or tools change

If you're doing more than that, something is going wrong. See [05-TROUBLESHOOTING.md](05-TROUBLESHOOTING.md).

---

## Monitoring stack

| Signal | Tool | What to watch |
|---|---|---|
| Backend exceptions | Sentry | Any new error type, especially in `v2_serving` or `new_orchestrator` |
| Synthetic uptime | `/smoketest` + UptimeRobot/BetterStack | 5-min pinger; alert if 3 consecutive fails |
| Health endpoints | `/health/ready` from load balancer | Should return 200; if not, route traffic away |
| Per-day costs | `DailyCost` Postgres table | Alert if >1.5× the 7-day average |
| User-facing bad answers | `ManualCorrection` Postgres table | If filings spike, the bot is degrading |
| Cache efficiency | `ModelTokenUsage.cached_input_tokens / input_tokens` | ≥60% steady-state |

### Useful Postgres queries

```sql
-- New ManualCorrection rows in last 24h
SELECT created_at, created_by, scope, target, action, reason
FROM "ManualCorrection"
WHERE created_at > NOW() - INTERVAL '24 hours'
ORDER BY created_at DESC;

-- Cache hit rate last 24h
SELECT
  SUM("cached_input_tokens")::float / NULLIF(SUM("input_tokens"), 0) * 100 AS cache_hit_pct,
  COUNT(*) AS turns
FROM "ModelTokenUsage"
WHERE "createdAt" > NOW() - INTERVAL '24 hours';

-- Refusal rate last 24h (v2 only)
SELECT
  COUNT(*) FILTER (WHERE "refusal_trigger" IS NOT NULL)::float / COUNT(*) * 100 AS refusal_rate_pct,
  COUNT(*) AS turns
FROM "Message"
WHERE created_at > NOW() - INTERVAL '24 hours';

-- Top refusal triggers
SELECT "refusal_trigger", COUNT(*) AS n
FROM "Message"
WHERE created_at > NOW() - INTERVAL '7 days' AND "refusal_trigger" IS NOT NULL
GROUP BY 1 ORDER BY n DESC LIMIT 20;

-- Daily cost trend (last 30 days)
SELECT date, model, ROUND(usd::numeric, 2) AS usd
FROM "DailyCost"
WHERE date >= CURRENT_DATE - INTERVAL '30 days'
ORDER BY date DESC, model;
```

---

## ManualCorrection workflow (librarian-facing)

This is the bot's safety net. When a librarian sees the bot give a wrong answer, they file a row in `ManualCorrection` and the bot honors it on the next turn — no deploy required.

### Schema

```sql
SELECT column_name, data_type FROM information_schema.columns
WHERE table_name = 'ManualCorrection';
```

```
id              SERIAL PRIMARY KEY
scope           TEXT    -- "url" | "chunk" | "intent" | "global"
target          TEXT    -- url, chunk_id, intent name, or "*"
action          TEXT    -- "suppress" | "replace" | "pin" | "blacklist_url"
replacement     TEXT    -- for action=replace: the corrected text
query_pattern   TEXT    -- for action=pin: regex matching user questions
reason          TEXT    -- required, no anonymous corrections
created_by      TEXT    -- librarian email
created_at      TIMESTAMP
expires_at      TIMESTAMP   -- forced 6-month review; default NOW()+180d
active          BOOLEAN     -- default true
```

### The 4 action types

#### `suppress` — drop a chunk from retrieval

When: a specific chunk has bad data, the underlying page is right but the chunk extracted poorly.

```sql
INSERT INTO "ManualCorrection" (scope, target, action, reason, created_by, expires_at, active)
VALUES (
  'chunk', 'c-abc123', 'suppress',
  'Chunk text says "open 24 hours" but King is not 24 hours — extraction error',
  'librarian@miamioh.edu',
  NOW() + INTERVAL '180 days', true
);
```

Effect: that `chunk_id` is excluded from `search_kb` results until the next ETL re-extracts and replaces.

#### `replace` — substitute chunk text

When: the page is wrong (and the website team is fixing it), but in the meantime you want the bot to give the right answer.

```sql
INSERT INTO "ManualCorrection" (scope, target, action, replacement, reason, created_by, expires_at, active)
VALUES (
  'chunk', 'c-def456', 'replace',
  'The ILL turnaround for journal articles is 2-3 business days, not 5-7 as the page currently states.',
  'Page is out of date; web team fixing in PR #123',
  'librarian@miamioh.edu',
  NOW() + INTERVAL '60 days', true
);
```

Effect: retrieval still returns the chunk, but with the replacement text + a "librarian-corrected" provenance marker shown in the citation chip.

#### `blacklist_url` — never cite a URL

When: a URL is dead, redirects to spam, or the page has wrong information that we can't get fixed.

```sql
INSERT INTO "ManualCorrection" (scope, target, action, reason, created_by, expires_at, active)
VALUES (
  'url', 'https://www.lib.miamioh.edu/about/old-page/', 'blacklist_url',
  'Page deleted by web team; should not be cited',
  'librarian@miamioh.edu',
  NOW() + INTERVAL '180 days', true
);
```

Effect: `UrlSeen.isBlacklisted = true`. The post-processor refuses any answer mentioning that URL.

#### `pin` — force a specific page at rank 1 for matching queries

When: bot keeps missing the canonical page for a common question.

```sql
INSERT INTO "ManualCorrection" (scope, target, action, query_pattern, reason, created_by, expires_at, active)
VALUES (
  'url', 'https://libguides.lib.miamioh.edu/citation/apa', 'pin',
  '(?i)\b(apa|cite|citation).*\b(format|style)\b',
  'Bot was returning generic citation guide; pin the APA-specific page',
  'librarian@miamioh.edu',
  NOW() + INTERVAL '180 days', true
);
```

Effect: when the user's question matches the regex, the pinned chunk is injected at rank 1 in `search_kb` results.

Use sparingly — over-pinning fights the retrieval system. If you're pinning often, the retrieval is broken; fix that instead.

### Review cycle

All corrections default to `expires_at = NOW() + 180 days`. When they expire:
- A weekly cron (TODO if not yet built) emails the `created_by` librarian: "your correction X is expiring; confirm or extend?"
- If not confirmed within 7 days, `active` flips to false (correction stops firing)

This prevents stale corrections from accumulating forever.

### Audit / fire counts

Every time a correction fires (suppresses / replaces / pins something during a turn), it's logged to the `Message` table's `fired_corrections` array. Periodic report:

```sql
-- Top-firing corrections last 7 days
SELECT
  c.id, c.target, c.action, c.reason, c.created_by,
  COUNT(*) AS fire_count
FROM "ManualCorrection" c
JOIN "Message" m ON c.id = ANY(m.fired_corrections)
WHERE m.created_at > NOW() - INTERVAL '7 days'
GROUP BY c.id, c.target, c.action, c.reason, c.created_by
ORDER BY fire_count DESC
LIMIT 20;
```

If one URL is being suppressed/replaced very often, the underlying page is the problem — escalate to the web team.

---

## Subject-librarian review queue

Reading every conversation the bot has is impossible. Instead, librarians review a filtered queue of conversations that touched their subject area.

The match logic (when implemented in the admin UI):
- Bot cited a `source_url` whose owning subject matches a `Librarian.subjects` row
- OR user message contains a course / dept / major code in this librarian's subjects
- OR conversation's `scope.campus` matches this librarian's `campus` (regional librarians see their campus's traffic by default)

### There is an admin console now — use it

**This section described a Metabase/spreadsheet workaround "for phase-1 ops
before a real admin UI exists". That UI has existed since June 2026, and
the SQL printed here referenced five columns `Message` does not have
(`created_at`, `user_message`, `bot_answer`, `cited_chunk_ids`,
`refusal_trigger`) — it could only ever have errored.**

The real columns are `type`, `content`, `timestamp`, `intent`,
`scopeCampus`, `modelUsed`, `isPositiveRated`. A worked query against them
is in [../09-TEAM-MAINTENANCE-GUIDE.md](../09-TEAM-MAINTENANCE-GUIDE.md)
§5, with its real output.

Where to go instead:

| You want | Go to |
|---|---|
| Every conversation, filterable by day | `/admin/conversations` |
| What patrons asked, for a department head | `/librarian/` → "What patrons asked" (needs a Miami sign-in) |
| The correction queue | `/admin/corrections/view` |
| Spend | `/admin/cost` |

Access is Miami single sign-on since 2026-09-01; see
[../02-ENVIRONMENT-VARIABLES.md](../02-ENVIRONMENT-VARIABLES.md).

### Weekly digest email

`ai-core/scripts/digest_email.py` (run Monday 8 AM via cron):
- Per subject librarian: "you have N unreviewed conversations in your area this week; M had thumbs-down ratings; click [link]"
- Per regional librarian: same but filtered by `Librarian.campus`

If this isn't running on your prod, set up the cron.

---

## Scheduled jobs

**Rewritten 1 September 2026. What was here before described a file that
does not exist (`/etc/cron.d/smart-chatbot`), under a path that does not
exist (`/opt/chatbot/`), running a script that does not exist
(`expire_corrections.py`), at times none of the real jobs use — while
omitting every job that actually runs, including the backup and the
watchdog.** Verified below against `crontab -l` and `systemctl`.

There are two schedulers, deliberately.

### 1. Everything the bot MAILS — one systemd timer, 09:30 America/New_York

`chatbot-morning.timer` → `ai-core/scripts/morning_jobs.sh`.

| Job | When |
|---|---|
| `scripts.data_health --quiet` | daily — sent every morning, all-clear included |
| `scripts.alert_digest` | daily — every other queued alert, including a failed backup |
| `scripts.etl_watch` | Mondays — website-change watch |
| `scripts.budget_report --email` | Mondays, and again on the 1st |

Not cron, because the box runs UTC and Ubuntu's cron cannot schedule in
another timezone — a fixed UTC time would be 09:30 in summer and 08:30 in
winter. `Persistent=true` also catches up after downtime.

```bash
systemctl list-timers chatbot-morning.timer --no-pager
sudo -u root bash /opt/chatbot/ai-core/scripts/morning_jobs.sh --dry-run
```

The dry run **exits non-zero and that is correct** — the jobs underneath
treat a suppressed send as a failed send.

**A morning with no data-health email means the job did not run**, not
that everything is fine.

### 2. Everything that must NOT wait for business hours — root crontab

```cron
*/5  * * * *   scripts.liveness_watchdog --try-restart   # restarts if systemd gave up
*/15 * * * *   scripts.budget_guard                      # decide the spend level
0 2  * * *     scripts.cost_rollup                       # must finish before the morning reports read it
30 3 * * *     scripts.backup_db --quiet                 # pg_dump, out of the hours students ask
```

Each is wrapped so it loads `/opt/chatbot/.env` first and appends to
`ai-core/logs/<name>.log`. To see them exactly as installed:

```bash
sudo crontab -l
```

**Note:** `scripts/digest_email.py` exists but nothing schedules it;
`scripts.alert_digest` is the one that runs.

---

## Credential rotation

### OpenAI

1. Generate new key in OpenAI dashboard
2. Update `OPENAI_API_KEY` in `/opt/chatbot/.env`
3. Restart backend: `sudo systemctl restart chatbot`
4. Verify with a smoke test
5. After confirming new key works, revoke old key

### LibCal / LibGuides OAuth

1. Get new client_id/client_secret from Springshare admin
2. Update `LIBCAL_CLIENT_*` / `LIBAPPS_CLIENT_*` in `.env`
3. Restart backend (OAuth tokens are cached in-process)
4. Verify with `curl http://localhost:8081/health` — LibCal section should be `"healthy"`

### Postgres password

1. Change password in Postgres
2. Update `DATABASE_URL` in `.env`
3. Restart backend

### .env file permissions

```bash
chmod 600 /opt/chatbot/.env
chown <service-user>:<service-user> /opt/chatbot/.env
```

Only the service user should be able to read it.

---

## Performance benchmarks (what's normal)

| Metric | Healthy range | Concerning if |
|---|---|---|
| `/health/live` p50 | <10ms | >50ms |
| `/health/live` p99 | <50ms | >200ms |
| Chat turn p50 | ~7s | >15s |
| Chat turn p99 | 15-25s | >40s |
| OpenAI input tokens / turn | 1.5k-3k | >5k |
| Cache hit rate | 70-85% | <60% |
| Refusal rate | 15-25% | >40% |
| Per-day OpenAI cost (real student traffic) | **$0.05–0.20** | **>$1.33** |
| New `ManualCorrection`/week | <10 | >30 |

**The cost row was `$5-30/day, concerning above $100` until 2026-09-01.
That was never true of this deployment and is now actively misleading:
the students' purse is $40 for the WHOLE MONTH, so the guard's daily line
is $1.33 and it starts throttling above it.** Real traffic runs about
$3/month. If you see $5 in a day, something is wrong — that is not a
healthy range, it is four days of the month's money.

Turn latency: ~7s is normal and ~25s is normal *during a corpus apply*,
which is memory-bound on this box. See
[../AWS-CAPACITY-REQUEST.md](../AWS-CAPACITY-REQUEST.md).

If you're outside the healthy range, the next step depends:
- High latency → check Weaviate health, LibCal latency, OpenAI rate limits
- Low cache hit → prompt prefix is drifting; check `prompts/builder.py` byte-stability assertion
- High refusal rate → either the corpus is missing content, OR a recent prompt change made the bot too conservative
- High cost → check for prompt regression, tool-call retry loops, or traffic spike. `budget_guard.py --dry-run` prints the live position and is safe to run any time; the ladder is in [../BUDGET.md](../BUDGET.md)
- High correction count → bot quality is degrading; investigate which categories are misfiring

---

## Rolling back a bad day

If "everything is broken" on a Tuesday morning:

1. **Don't panic.** Symlink swap is always available (Option 1 in [03-DEPLOYMENT.md](03-DEPLOYMENT.md)).
2. **Roll back to last known good build:** `sudo ln -sfn /opt/chatbot/builds/<previous>/ /opt/chatbot && sudo systemctl restart chatbot`.
3. **Verify:** `/smoketest` + sanity-check a few questions in the browser.
4. **Then debug:** what changed in the bad build? `git log` between the two timestamps.

Most "everything is broken" days are actually "one specific service is broken" days (OpenAI down, LibCal flaky, etc.). Distinguish:
- If `curl /health` shows a specific service as unhealthy → that's the issue, not our bot
- If `curl /health` is healthy but bot still misbehaves → it IS our bot, roll back

---

## Long-term operational TODOs

These are aspirational; some may already be done:

- [ ] Build the librarian admin UI (currently MVP via Metabase + spreadsheet)
- [ ] Cron the weekly digest email
- [ ] Cron the ManualCorrection expiry check
- [ ] Wire `/health/ready` into load balancer
- [ ] Set up Prometheus scrape of `/metrics` (if exposed)
- [ ] Per-month cost report email to project lead
- [ ] Quarterly eval suite refresh (re-run, compare to baseline, file regressions)
- [ ] Adversarial prompt-injection red-team pass
- [ ] Multi-tenant isolation (when we share infra with other apps)
- [ ] Per-user rate limiting (if abuse becomes an issue)
