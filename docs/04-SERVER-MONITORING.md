# Server Monitoring & Alerts

> **Partly out of date, 2026-09-01.** Written 17 July. The cron facts
> in it are still true, but it predates the 09:30 systemd timer and
> the daily digest, so it is not the whole picture of what runs.
> See [09-TEAM-MAINTENANCE-GUIDE.md](./09-TEAM-MAINTENANCE-GUIDE.md) §4.


**Last Updated:** July 18, 2026
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

All also linked from the operator hub at `/admin/`. Reaching it needs a
Miami sign-in since 2026-09-01 (see the banner at the top of this file);
the four probe URLs themselves are unaffected and need no credentials.
Verified 2026-09-01: `/health/live` and `/health/ready` both 200.

## Logs

`ai-core/logs/`: `app.log` (JSON, rotated), `errors.log`, `access.log`.
Grep `alert email` in app.log to audit alert deliveries/failures.

## Cost monitoring

Nightly cron (root crontab, 02:00) runs `scripts/cost_rollup.py` →
`DailyCost` table → `/admin/cost` dashboard. Model prices live at the
top of that script — update them when models change.
