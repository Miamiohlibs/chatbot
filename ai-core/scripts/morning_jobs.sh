#!/usr/bin/env bash
# Everything that mails on a schedule, at ONE time: 09:30 America/New_York.
#
# WHY THIS EXISTS
#     Operator, 2026-08-30: "其他时间一律改成New York时区早上九点半,统一
#     一下时间". Five separate cron lines had drifted to five different
#     times between 06:10 and 13:30 -- so "when do I hear from the bot?"
#     had five answers and nobody could hold them all.
#
# WHY IT IS NOT CRON ANY MORE
#     This box runs UTC, and Ubuntu's cron cannot schedule in another
#     timezone -- `man 5 crontab` says so outright and suggests checking
#     the date inside the job as a workaround. A fixed UTC time would mean
#     09:30 in summer and 08:30 in winter, which is exactly the kind of
#     wrong that nobody notices twice a year.
#
#     systemd handles it natively:
#         OnCalendar=*-*-* 09:30:00 America/New_York
#     See chatbot-morning.timer. `Persistent=true` there also closes a gap
#     cron never covered: if the box is down at 09:30 the run happens on
#     the next boot rather than being silently skipped.
#
# ORDER MATTERS, AND IT WAS WRONG BEFORE
#     budget_report queues into the digest rather than mailing directly.
#     The old crontab ran the digest at 07:10 and the report at 07:20, so
#     the weekly budget report sat in the queue and went out the FOLLOWING
#     morning. Everything that queues runs first here; the digest is last.
#
# WHAT IS DELIBERATELY NOT HERE
#     Anything that must not wait for business hours, and anything that
#     must not run during them:
#       liveness_watchdog  every 5 min   the service being dead is not news
#                                        that keeps until morning
#       budget_guard       every 15 min  one client can spend the monthly
#                                        ceiling in about six hours
#       cost_rollup        02:00         feeds the reports below; has to be
#                                        finished before they read it
#       backup_db          03:30         a pg_dump on a 3.8 GB box, kept out
#                                        of the hours students are asking.
#                                        Its failure notice reaches you at
#                                        09:30 through the digest.
set -uo pipefail

# --dry-run runs every job with mail switched off. It exits NON-ZERO,
# because a suppressed send is a failed send as far as the jobs are
# concerned -- a red dry run is the expected outcome, not a fault.
#
# It exists because sourcing .env below OVERRIDES the caller's environment,
# so `ALERT_EMAIL_ENABLED=false ./morning_jobs.sh` does not do what it
# looks like it does -- it sends. Found the direct way, 2026-08-30.
DRY=0
[ "${1:-}" = "--dry-run" ] && DRY=1

REPO=/opt/chatbot/ai-core
cd "$REPO" || exit 2

set -a
# shellcheck disable=SC1091
. /opt/chatbot/.env
set +a

# AFTER the source, which is the whole point.
[ "$DRY" = 1 ] && export ALERT_EMAIL_ENABLED=false

PY="$REPO/.venv/bin/python"
DOW=$(TZ=America/New_York date +%u)   # 1=Mon .. 7=Sun
DOM=$(TZ=America/New_York date +%-d)
STAMP=$(TZ=America/New_York date '+%Y-%m-%d %H:%M %Z')
[ "$DRY" = 1 ] && STAMP="$STAMP (dry run)"

failed=0

run() {
    # run <log name> <human name> <args...>
    local log="$1" name="$2"; shift 2
    echo "--- $STAMP  $name" >> "logs/$log.log"
    if ! "$PY" -m "$@" >> "logs/$log.log" 2>&1; then
        # Reported, never fatal: one job failing must not cost you the
        # other four. The unit goes red at the end so `systemctl status`
        # still tells you something went wrong.
        echo "!!! $name exited non-zero" >> "logs/$log.log"
        failed=1
    fi
}

# --- daily ----------------------------------------------------------------
run data_health "data health" scripts.data_health --quiet

# --- Mondays --------------------------------------------------------------
if [ "$DOW" = "1" ]; then
    run etl_watch     "website watch"        scripts.etl_watch
    run budget_report "budget report (week)" scripts.budget_report --email
fi

# --- the 1st --------------------------------------------------------------
if [ "$DOM" = "1" ]; then
    LAST_MONTH=$(TZ=America/New_York date -d 'last month' +%Y-%m)
    run budget_report "budget report (month)" \
        scripts.budget_report --month "$LAST_MONTH" --email
fi

# --- last, so today's queued events go out today --------------------------
# Daily, not weekdays. It used to skip weekends, which was fine when
# nothing queued overnight -- but the backup runs at 03:30 every day, so a
# Saturday failure would have waited until Monday to be mentioned.
run alert_digest "daily digest" scripts.alert_digest

exit "$failed"
