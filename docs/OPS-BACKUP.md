# Backups: what is protected, what is not

## PostgreSQL — covered

Nightly at 03:30 (root cron), `ai-core/scripts/backup_db.py`.

Dumps land in `/opt/chatbot-private-data/backups/` (mode 700, files 600),
**outside the repo**, 30 days retained. Each dump has a `.json` sidecar
recording row counts for twelve tables at the moment it was taken.

Every run verifies itself: the archive is read back with `pg_restore --list`
(which only succeeds on a complete file), and the run writes to `.partial`
and renames on success, so an interrupted job cannot leave something that
looks finished. If any of that fails the operator gets an email, because a
backup that fails quietly is worse than no backup — it removes the worry
without removing the risk.

```bash
# what we hold
cd /opt/chatbot/ai-core && sudo .venv/bin/python -m scripts.backup_db --list

# take one now
sudo .venv/bin/python -m scripts.backup_db

# prove the newest one actually restores (safe: scratch DB, dropped after)
sudo .venv/bin/python -m scripts.backup_db --verify-restore
```

**Run `--verify-restore` before you need it, not after.** It restores into a
throwaway database and compares every recorded row count against the live
figures. First drill, 2026-08-12: 12/12 tables, 5,629 rows, exact.

### Restoring for real

```bash
sudo docker exec -i chatbot-postgres pg_restore -U myuser \
    -d smartchatbot --clean --if-exists < /opt/chatbot-private-data/backups/<file>.dump
```

Check the result against the sidecar `.json` for that dump. `--clean` drops
existing objects first — on the live database that is destructive, so take a
fresh dump before running it.

## Weaviate — NOT covered

The corpus (collection `Chunk_vv20260804_1110`) has no backup, and this is a
known gap rather than an oversight.

Weaviate's backup module is not enabled on this container
(`ENABLE_MODULES=` is empty), so a consistent snapshot needs either a restart
with `ENABLE_MODULES=backup-filesystem` or a brief stop to copy the volume.
Copying the volume while it runs is not crash-consistent and can produce an
archive that restores into a corrupt store — worse than having none, because
it looks like protection.

Restarting production is an operator decision, so nothing here does it.

**Why this matters more than it looks:** re-running the ETL does not
reproduce the current index. The live collection was built over many passes,
and the gold answers were shaped against what is in it. A rebuild would give
a different corpus and move the eval scores.

## What is deliberately not in git

Patron transcripts live in `/opt/chatbot-private-data/libchat-transcripts/`
(mode 700) and must never return to the repository. `scripts/scan_for_pii.py`
runs as a pre-commit hook and in CI to keep it that way; see
`scripts/setup_hooks.sh`.
