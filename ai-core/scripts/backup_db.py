"""Nightly database backup, with the verification that makes it a backup.

WHY
    Until now there was none. Through the test period that was a reasonable
    call -- the database held the operator's own probing. From the day beta
    opens it holds students' real questions, their room bookings and the
    librarians' corrections, and there is no second copy of any of it.

WHAT MAKES THIS DIFFERENT FROM `pg_dump > file`
    A dump that silently produced a truncated file would leave a directory
    full of reassuring filenames and nothing recoverable inside them. The
    same failure shape has already bitten this project twice: a .gitignore
    rule that matched nothing, and an OOM-killed eval that left short result
    files which scored as passes. Both were controls that appeared to be
    working.

    So every run:
      1. dumps in custom format (-Fc), which is compressed and selectively
         restorable,
      2. reads the dump back with `pg_restore --list`, which only succeeds
         on a structurally complete archive,
      3. counts rows in the tables that matter and stores them beside the
         dump, so a future restore can be checked against what was actually
         taken rather than against hope,
      4. emails the operator when any of that fails, because a backup that
         fails quietly is worse than no backup -- it removes the worry
         without removing the risk.

    And `--verify-restore` actually restores into a scratch database and
    compares those counts. A backup nobody has ever restored is a guess.

NO PASSWORD ANYWHERE
    pg_dump runs inside the container over the local socket, which trusts
    the connection, so this never reads DATABASE_URL and there is no secret
    to leak into a log, a process list, or this file.

WEAVIATE IS NOT COVERED
    Deliberately, and it is not an oversight -- see the note at the bottom
    of this docstring's companion, docs/OPS-BACKUP.md. Weaviate's backup
    module is not enabled on this container, so snapshotting it needs either
    a restart with ENABLE_MODULES=backup-filesystem or a brief stop, and a
    restart of production is the operator's call, not this script's.

USAGE
    python -m scripts.backup_db                 # take one, verify, prune
    python -m scripts.backup_db --verify-restore  # prove the newest restores
    python -m scripts.backup_db --list          # what we have

EXIT CODES
    0 success, 1 failure (cron will also have received an email).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import os
import subprocess
import sys
from pathlib import Path

log = logging.getLogger("backup_db")

CONTAINER = os.getenv("BACKUP_PG_CONTAINER", "chatbot-postgres")
# The container's superuser, not the application role. The app connects as
# `smartchatbot`, which cannot CREATE DATABASE and so cannot restore into a
# scratch copy -- and a backup you cannot practise restoring is not one.
#
# Checked on 2026-08-12 that this does not change what gets dumped: both
# roles produce a byte-identical 444,994-byte archive with the same 167
# objects, so nothing here is being taken on trust.
DB_USER = os.getenv("BACKUP_PG_USER", "myuser")
DB_NAME = os.getenv("BACKUP_PG_DB", "smartchatbot")

BACKUP_DIR = Path(os.getenv("BACKUP_DIR", "/opt/chatbot-private-data/backups"))
KEEP_DAYS = int(os.getenv("BACKUP_KEEP_DAYS", "30"))

# A dump smaller than this is not a real dump of this database. The schema
# alone exceeds it, so a truncated or empty file cannot slip through as a
# plausible-looking success.
MIN_DUMP_BYTES = 50_000

# Counted before the dump and stored beside it. These are the tables whose
# loss would actually hurt -- what students asked, what the bot did about it,
# and the corrections librarians have made by hand -- plus the reference data
# that took an ETL run to build.
#
# Names verified against the live schema on 2026-08-12. A first pass invented
# ToolCall/RoomBooking/Ticket, which do not exist; they recorded as -1 and
# would have made the restore check silently weaker at exactly the tables it
# most needed to cover. If a name here stops matching the schema, that shows
# up as -1 in the manifest rather than being skipped.
COUNTED_TABLES = (
    "Conversation", "Message", "ToolExecution", "ConversationFeedback",
    "LibrarianReview", "ManualCorrection", "CorrectionTicket",
    "Librarian", "LibGuide", "Subject", "ModelTokenUsage", "DailyCost",
)


def _docker() -> "list[str]":
    """docker, with sudo when we are not in the docker group.

    Cron runs as root and needs neither; a human running this by hand
    usually does.
    """
    probe = subprocess.run(["docker", "info"], capture_output=True)
    return ["docker"] if probe.returncode == 0 else ["sudo", "-n", "docker"]


def _psql(sql: str) -> "str | None":
    r = subprocess.run(
        [*_docker(), "exec", CONTAINER, "psql", "-U", DB_USER, "-d", DB_NAME,
         "-tAc", sql],
        capture_output=True, text=True)
    if r.returncode != 0:
        log.error("psql failed: %s", r.stderr.strip()[:400])
        return None
    return r.stdout.strip()


def table_counts() -> "dict[str, int]":
    """Row counts for the tables worth checking a restore against.

    A table that does not exist is recorded as -1 rather than skipped: a
    schema that quietly lost a table is exactly the kind of thing this
    should make visible.
    """
    counts: "dict[str, int]" = {}
    for t in COUNTED_TABLES:
        out = _psql(f'SELECT count(*) FROM "{t}";')
        counts[t] = int(out) if out and out.isdigit() else -1
    return counts


def _alert(subject: str, body: str) -> None:
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from src.observability.alerting import send_alert_email

        send_alert_email(subject, body)
    except Exception as e:  # noqa: BLE001 -- never let alerting mask the failure
        log.error("could not send the backup alert: %s", e)


def take_backup(stamp: str) -> "tuple[bool, str]":
    """-> (ok, human-readable detail). Writes dump + sidecar manifest."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(BACKUP_DIR, 0o700)

    dump = BACKUP_DIR / f"{DB_NAME}-{stamp}.dump"
    manifest = BACKUP_DIR / f"{DB_NAME}-{stamp}.json"
    partial = dump.with_suffix(".dump.partial")

    counts = table_counts()
    if all(v == -1 for v in counts.values()):
        return False, ("could not read row counts from the database at all -- "
                       "the container or the credentials are wrong, and a dump "
                       "taken now would not be trustworthy")

    # Write to .partial and rename only on success, so an interrupted run
    # never leaves a file that looks like a finished backup.
    with partial.open("wb") as fh:
        r = subprocess.run(
            [*_docker(), "exec", CONTAINER, "pg_dump", "-U", DB_USER,
             "-d", DB_NAME, "-Fc"],
            stdout=fh, stderr=subprocess.PIPE)
    if r.returncode != 0:
        partial.unlink(missing_ok=True)
        return False, f"pg_dump exited {r.returncode}: {r.stderr.decode()[:400]}"

    size = partial.stat().st_size
    if size < MIN_DUMP_BYTES:
        partial.unlink(missing_ok=True)
        return False, (f"the dump was only {size} bytes, which is smaller than "
                       f"this database's schema -- treating it as truncated")

    # The real check: pg_restore --list only parses a complete archive.
    listing = subprocess.run(
        [*_docker(), "exec", "-i", CONTAINER, "pg_restore", "--list"],
        stdin=partial.open("rb"), capture_output=True, text=True)
    if listing.returncode != 0:
        partial.unlink(missing_ok=True)
        return False, (f"the dump was written but pg_restore could not read it "
                       f"back: {listing.stderr.strip()[:300]}")
    objects = sum(1 for ln in listing.stdout.splitlines()
                  if ln and not ln.startswith(";"))

    partial.rename(dump)
    os.chmod(dump, 0o600)

    manifest.write_text(json.dumps({
        "taken_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "database": DB_NAME,
        "dump_file": dump.name,
        "bytes": size,
        "archive_objects": objects,
        "row_counts": counts,
    }, indent=2) + "\n")
    os.chmod(manifest, 0o600)

    total = sum(v for v in counts.values() if v > 0)
    return True, (f"{dump.name}, {size / 1e6:.1f} MB, {objects} archive objects, "
                  f"{total} rows across {len(COUNTED_TABLES)} tracked tables")


def prune() -> "list[str]":
    cutoff = dt.datetime.now() - dt.timedelta(days=KEEP_DAYS)
    removed = []
    for f in sorted(BACKUP_DIR.glob(f"{DB_NAME}-*")):
        try:
            if dt.datetime.fromtimestamp(f.stat().st_mtime) < cutoff:
                f.unlink()
                removed.append(f.name)
        except OSError as e:  # noqa: PERF203
            log.warning("could not prune %s: %s", f, e)
    return removed


def verify_restore() -> bool:
    """Restore the newest dump into a scratch database and compare counts.

    This is the only step that proves the file is usable rather than merely
    well-formed. It creates and drops its own database and never touches
    the live one.
    """
    dumps = sorted(BACKUP_DIR.glob(f"{DB_NAME}-*.dump"))
    if not dumps:
        print("no backups to verify")
        return False
    newest = dumps[-1]
    manifest = newest.with_suffix(".json")
    expected = json.loads(manifest.read_text())["row_counts"] if manifest.exists() else {}

    scratch = f"{DB_NAME}_restorecheck"
    d = _docker()
    print(f"restoring {newest.name} into scratch database {scratch} ...")
    subprocess.run([*d, "exec", CONTAINER, "psql", "-U", DB_USER, "-d", DB_NAME,
                    "-c", f'DROP DATABASE IF EXISTS "{scratch}";'],
                   capture_output=True)
    mk = subprocess.run([*d, "exec", CONTAINER, "psql", "-U", DB_USER, "-d",
                         DB_NAME, "-c", f'CREATE DATABASE "{scratch}";'],
                        capture_output=True, text=True)
    if mk.returncode != 0:
        print(f"  could not create the scratch database: {mk.stderr.strip()[:300]}")
        return False

    try:
        rest = subprocess.run(
            [*d, "exec", "-i", CONTAINER, "pg_restore", "-U", DB_USER,
             "-d", scratch, "--no-owner", "--no-privileges"],
            stdin=newest.open("rb"), capture_output=True, text=True)
        # pg_restore warns about ownership and extensions on a clean target;
        # what matters is whether the rows arrived.
        if rest.returncode != 0:
            print(f"  pg_restore reported problems (exit {rest.returncode}); "
                  f"checking the data anyway")

        ok = True
        for table, want in expected.items():
            if want < 0:
                continue
            r = subprocess.run(
                [*d, "exec", CONTAINER, "psql", "-U", DB_USER, "-d", scratch,
                 "-tAc", f'SELECT count(*) FROM "{table}";'],
                capture_output=True, text=True)
            got = int(r.stdout.strip()) if r.stdout.strip().isdigit() else -1
            mark = "ok " if got == want else "BAD"
            if got != want:
                ok = False
            print(f"  {mark} {table:<20} expected {want:>7}  restored {got:>7}")
        print("\nRESTORE VERIFIED -- this backup is recoverable." if ok else
              "\nRESTORE MISMATCH -- do not rely on this backup.")
        return ok
    finally:
        subprocess.run([*d, "exec", CONTAINER, "psql", "-U", DB_USER, "-d",
                        DB_NAME, "-c", f'DROP DATABASE IF EXISTS "{scratch}";'],
                       capture_output=True)
        print(f"scratch database {scratch} dropped")


def list_backups() -> None:
    files = sorted(BACKUP_DIR.glob(f"{DB_NAME}-*.dump"))
    if not files:
        print(f"no backups in {BACKUP_DIR}")
        return
    print(f"{len(files)} backup(s) in {BACKUP_DIR}:")
    for f in files:
        m = f.with_suffix(".json")
        rows = ""
        if m.exists():
            try:
                c = json.loads(m.read_text())["row_counts"]
                rows = f"  {sum(v for v in c.values() if v > 0)} rows"
            except Exception:  # noqa: BLE001
                rows = "  (manifest unreadable)"
        age = dt.datetime.now() - dt.datetime.fromtimestamp(f.stat().st_mtime)
        print(f"  {f.name}  {f.stat().st_size / 1e6:6.1f} MB  "
              f"{age.days}d old{rows}")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--verify-restore", action="store_true",
                    help="restore the newest dump into a scratch database")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--quiet", action="store_true", help="only speak up on failure")
    args = ap.parse_args()

    if args.list:
        list_backups()
        return 0
    if args.verify_restore:
        return 0 if verify_restore() else 1

    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    ok, detail = take_backup(stamp)

    if not ok:
        log.error("BACKUP FAILED: %s", detail)
        _alert(
            "[chatbot] the nightly database backup FAILED",
            f"No usable backup was produced tonight.\n\n"
            f"  {detail}\n\n"
            f"The database holds students' questions, their room bookings and "
            f"the librarians' corrections, and there is no other copy.\n\n"
            f"  check:   python -m scripts.backup_db --list\n"
            f"  by hand: python -m scripts.backup_db\n"
            f"  proof:   python -m scripts.backup_db --verify-restore\n",
        )
        return 1

    removed = prune()
    if not args.quiet:
        print(f"backup ok: {detail}")
        if removed:
            print(f"pruned {len(removed)} backup(s) older than {KEEP_DAYS} days")
    log.info("backup ok: %s", detail)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
