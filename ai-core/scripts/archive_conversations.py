"""Archive conversation traffic out of the live database, then purge it.

WHY
    Operator ruling 2026-08-11, ahead of launch: everything from before
    August is finished business, and leaving 5,863 old conversations in
    the tables makes the admin queues and every ad-hoc query wade through
    history nobody is going to read again.

WHAT IS AND IS NOT TOUCHED
    Traffic only -- Conversation and its four children (Message,
    ModelTokenUsage, ToolExecution, ConversationFeedback). Reference and
    config data (Librarian, Subject, LibGuide, UrlSeen, ManualCorrection,
    Campus, Library...) is never in scope: it describes the library, not
    a conversation, and deleting it would break the running bot.

    DailyCost is ARCHIVED BUT NOT DELETED. It is 44 rows of spend
    history, it costs nothing to search past, and dropping it would leave
    the cost dashboard with no history to show. Pass --purge-daily-cost
    to include it.

THE CUT IS BY CONVERSATION, NOT BY ROW TIMESTAMP
    A conversation that starts at 23:50 on 31 July and runs past midnight
    is one conversation; splitting it would leave a half in each side and
    -- because every foreign key is ON DELETE RESTRICT -- the delete would
    fail anyway. So a conversation belongs to the day it STARTED, and its
    children go with it whatever their own timestamps say.

    Checked before writing this: zero conversations straddle the
    2026-08-01 boundary, so both readings currently give identical sets.
    The rule is stated anyway, because the next cut may not be so lucky.

ORDER OF DELETION
    Children first. Every FK into Conversation is ON DELETE RESTRICT, so
    a parent-first delete does not cascade -- it errors, which is the
    right failure but only if you were not expecting a cascade.

SAFETY
    Archive, verify, then delete, in that order, in one run:
      1. write one JSONL per table plus a manifest with row counts and a
         SHA-256 of every file
      2. re-read the files and check counts and digests against the
         manifest
      3. only then delete, and re-count to confirm what went

    Without --purge it stops after step 2, which is the default.

    The archive holds patron questions, so it is written under
    /opt/chatbot-private-data (mode 700) and never inside the repo.

Run:
    python ai-core/scripts/archive_conversations.py --before 2026-08-01
    python ai-core/scripts/archive_conversations.py --before 2026-08-01 --purge
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import hashlib
import json
import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_AI_CORE = _HERE.parent
sys.path.insert(0, str(_AI_CORE))

_ENV_PATH = _AI_CORE.parent / ".env"
if _ENV_PATH.exists():
    for _line in _ENV_PATH.read_text(encoding="utf-8").splitlines():
        if not _line or _line.startswith("#") or "=" not in _line:
            continue
        _k, _, _v = _line.partition("=")
        _k = _k.strip()
        if _k and _k not in os.environ:
            os.environ[_k] = _v.strip().strip('"').strip("'")

ARCHIVE_ROOT = Path(
    os.getenv("CONVERSATION_ARCHIVE_DIR", "/opt/chatbot-private-data/archive")
)

# Children before parent: every FK into Conversation is ON DELETE RESTRICT.
# (LibrarianReview -> Message is CASCADE, so message deletes carry it.)
CHILD_TABLES = [
    # LinkClick FIRST: it points at BOTH Conversation and Message, so it has
    # to go before Message or the Message delete hits a RESTRICT violation.
    # Added 2026-08-16 with the table itself -- this list drives the ARCHIVE
    # loop as well as the delete loop, so forgetting it would both break the
    # purge AND delete rows that were never written to the archive.
    ("LinkClick", "linkclick"),
    ("ConversationFeedback", "conversationfeedback"),
    ("ToolExecution", "toolexecution"),
    ("ModelTokenUsage", "modeltokenusage"),
    ("Message", "message"),
]


def _json_default(o):
    if isinstance(o, (dt.datetime, dt.date)):
        return o.isoformat()
    return str(o)


def _digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


async def _rows(db, sql: str) -> list[dict]:
    return await db.query_raw(sql)


def _write_jsonl(path: Path, rows: list[dict]) -> dict:
    with path.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, default=_json_default, ensure_ascii=False))
            fh.write("\n")
    path.chmod(0o600)
    return {"rows": len(rows), "bytes": path.stat().st_size,
            "sha256": _digest(path)}


def _verify(outdir: Path, manifest: dict) -> list[str]:
    """Re-read what was written. An archive nobody checked is a rumour."""
    problems = []
    for table, meta in manifest["tables"].items():
        path = outdir / f"{table}.jsonl"
        if not path.exists():
            problems.append(f"{table}: file missing")
            continue
        if _digest(path) != meta["sha256"]:
            problems.append(f"{table}: sha256 mismatch")
        n = sum(1 for line in path.open(encoding="utf-8") if line.strip())
        if n != meta["rows"]:
            problems.append(f"{table}: {n} lines, manifest says {meta['rows']}")
        # every line must parse -- a truncated write is worse than no file
        try:
            with path.open(encoding="utf-8") as fh:
                for line in fh:
                    if line.strip():
                        json.loads(line)
        except json.JSONDecodeError as e:
            problems.append(f"{table}: unreadable JSON ({e})")
    return problems


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--before", required=True,
                    help="ISO date; conversations STARTED before this go")
    ap.add_argument("--purge", action="store_true",
                    help="delete after a verified archive (default: archive only)")
    ap.add_argument("--purge-daily-cost", action="store_true",
                    help="also delete archived DailyCost rows")
    args = ap.parse_args()

    cut = args.before
    dt.date.fromisoformat(cut)          # fail loudly on a bad date

    from src.database.prisma_client import get_prisma_client

    db = get_prisma_client()
    if not db.is_connected():
        await db.connect()

    stamp = (await db.query_raw("SELECT now()::text AS t"))[0]["t"][:19]
    outdir = ARCHIVE_ROOT / f"{stamp[:10]}_before_{cut}"
    outdir.mkdir(parents=True, exist_ok=True)
    outdir.chmod(0o700)

    scope = f'SELECT id FROM "Conversation" WHERE "createdAt" < \'{cut}\''
    n_conv = (await _rows(db, f"SELECT COUNT(*)::int n FROM ({scope}) s"))[0]["n"]
    print(f"  cut          : conversations started before {cut}")
    print(f"  conversations: {n_conv}")
    if n_conv == 0:
        print("  nothing to archive.")
        await db.disconnect()
        return 0

    manifest = {
        "created_at": stamp,
        "cut_before": cut,
        "rule": "conversation belongs to the day it STARTED; children follow it",
        "tables": {},
    }

    # --- 1. archive ------------------------------------------------------
    for table, _model in CHILD_TABLES:
        rows = await _rows(db, f"""
            SELECT x.* FROM "{table}" x
            JOIN "Conversation" c ON c.id = x."conversationId"
            WHERE c."createdAt" < '{cut}'
        """)
        manifest["tables"][table] = _write_jsonl(outdir / f"{table}.jsonl", rows)
        print(f"  archived {table:22s} {len(rows):6d}")

    rows = await _rows(db, f'SELECT * FROM "Conversation" WHERE "createdAt" < \'{cut}\'')
    manifest["tables"]["Conversation"] = _write_jsonl(
        outdir / "Conversation.jsonl", rows)
    print(f"  archived {'Conversation':22s} {len(rows):6d}")

    rows = await _rows(db, f'SELECT * FROM "DailyCost" WHERE "createdAt" < \'{cut}\'')
    manifest["tables"]["DailyCost"] = _write_jsonl(
        outdir / "DailyCost.jsonl", rows)
    print(f"  archived {'DailyCost':22s} {len(rows):6d}  (kept in the DB "
          f"unless --purge-daily-cost)")

    (outdir / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8")
    (outdir / "manifest.json").chmod(0o600)

    # --- 2. verify -------------------------------------------------------
    problems = _verify(outdir, manifest)
    if problems:
        print("\n  ARCHIVE FAILED VERIFICATION -- nothing deleted:")
        for p in problems:
            print(f"    {p}")
        await db.disconnect()
        return 1
    total = sum(m["rows"] for m in manifest["tables"].values())
    print(f"\n  verified     : {total} rows re-read, digests match")
    print(f"  archive      : {outdir}")

    if not args.purge:
        print("\n  ARCHIVE ONLY. Re-run with --purge to delete.")
        await db.disconnect()
        return 0

    # --- 3. purge --------------------------------------------------------
    print("\n  deleting (children first; every FK is ON DELETE RESTRICT)")
    deleted = {}
    for table, _model in CHILD_TABLES:
        r = await db.execute_raw(f"""
            DELETE FROM "{table}" x
            USING "Conversation" c
            WHERE c.id = x."conversationId" AND c."createdAt" < '{cut}'
        """)
        deleted[table] = r
        print(f"    {table:22s} {r:6d}")
    r = await db.execute_raw(
        f'DELETE FROM "Conversation" WHERE "createdAt" < \'{cut}\'')
    deleted["Conversation"] = r
    print(f"    {'Conversation':22s} {r:6d}")

    if args.purge_daily_cost:
        r = await db.execute_raw(
            f'DELETE FROM "DailyCost" WHERE "createdAt" < \'{cut}\'')
        deleted["DailyCost"] = r
        print(f"    {'DailyCost':22s} {r:6d}")

    left = (await _rows(db, f"""
        SELECT COUNT(*)::int n FROM "Conversation" WHERE "createdAt" < '{cut}'
    """))[0]["n"]
    print(f"\n  remaining before {cut}: {left} (want 0)")

    (outdir / "purged.json").write_text(
        json.dumps({"purged_at": stamp, "deleted": deleted, "remaining": left},
                   indent=2), encoding="utf-8")
    (outdir / "purged.json").chmod(0o600)
    await db.disconnect()
    return 0 if left == 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
