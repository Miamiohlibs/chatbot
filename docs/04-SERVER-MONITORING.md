# Server Monitoring & Alerts

**Last Updated:** 1 September 2026 (written 18 July; the scheduling
section below was the part that had gone stale and is now complete)
**Describes the CURRENT stack.** The pre-migration watchdog era
(`server_monitor.py`, local MTA on :25) is archived at
[archive/legacy-v31/09-SERVER-MONITORING.md](./archive/legacy-v31/09-SERVER-MONITORING.md).

## Process supervision

- **systemd** owns the process: `chatbot.service`, `Restart=on-failure`,
  uvicorn on port 8081.
- Useful commands:
  ```bash
  sudo systemctl status chatbot.service
  sudo journalctl -u chatbot.service --since "1 hour ago"   # TWO dashes
  sudo systemctl restart chatbot.service
  ```

## Email alerts (dependency down / recovered)

`ai-core/src/observability/alerting.py` emails the operator on health
state changes. Configured 2026-07-17 via an authenticated Gmail relay on
port 587 (AWS blocks outbound 25 — this is why alerts silently died for
three days after the migration). Env: the `ALERT_*` block in
[02-ENVIRONMENT-VARIABLES.md](./02-ENVIRONMENT-VARIABLES.md).

Re-verify anytime:
```bash
cd ai-core && .venv/bin/python -m src.observability.alerting   # sends a test email
```

## Probes (wire these to an external pinger)

| URL | What it proves |
|---|---|
| `/health/live` | process is up |
| `/health/ready` | Postgres, Weaviate, OpenAI, LibCal, LibGuides all reachable |
| `/smoketest` | a full turn answers WITH a citation under the latency budget |
| `/metrics` | Prometheus exposition (if prometheus-client installed) |

**`/health/ready` is callable from a browser on another Miami page.**
Since 2026-09-01 that ONE endpoint answers CORS for `https://*.miamioh.edu`,
so a library page can `fetch()` it to show whether the bot is up:

```js
fetch("https://chatbot.lib.miamioh.edu/health/ready")
  .then(r => r.json()).then(d => console.log(d.status));
```

The other three stay closed, deliberately. `/health` fans out to six
external probes on every call, so a browser polling loop would spend our
upstream quota; `/health/live` and `/health/service` nobody asked for.
Opening endpoints "while we are here" is how a surface grows without
anyone deciding to grow it — add to `_ALLOWED_PATHS` on purpose.

And never with credentials. Widening the app-wide CORS list instead would
have let any allowed origin make credentialed calls to `/admin/*` and read
raw patron conversations with the visitor's session cookie. See
`src/api/health_cors.py`.

All also linked from the operator hub at `/admin/`. Reaching it needs a
Miami sign-in since 2026-09-01 (see the banner at the top of this file);
the four probe URLs themselves are unaffected and need no credentials.
Verified 2026-09-01: `/health/live` and `/health/ready` both 200.

## Logs

`ai-core/logs/`: `app.log` (JSON, rotated), `errors.log`, `access.log`.
Grep `alert email` in app.log to audit alert deliveries/failures.

## Scheduled work — two schedulers

**Everything the bot MAILS runs at 09:30 America/New_York**, from one
systemd timer (`chatbot-morning.timer` → `ai-core/scripts/morning_jobs.sh`):
the daily data-health report, the daily alert digest, the Monday website
watch, and the budget report on Mondays and the 1st.

Not cron: this box runs UTC, and Ubuntu's cron cannot schedule in another
timezone, so a fixed UTC time would drift an hour at daylight saving.
`Persistent=true` also catches up after downtime.

```bash
systemctl list-timers chatbot-morning.timer --no-pager
```

**Everything that must not wait for business hours stays on the root
crontab**: the liveness watchdog every 5 minutes, the budget guard every
15, the cost rollup at 02:00, the database backup at 03:30.

A morning with no data-health email means the job did not run — that
report is sent every day, all-clear included, so its absence is a signal.

---

## Cost monitoring

Nightly cron (root crontab, 02:00) runs `scripts/cost_rollup.py` →
`DailyCost` table → `/admin/cost` dashboard. Model prices live at the
top of that script — update them when models change.
