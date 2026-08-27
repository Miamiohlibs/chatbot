"""Run the ETL phases from the console, one at a time, without SSH.

WHY THIS EXISTS
    The web team updates the site on Saturdays. Getting those updates into
    the bot meant: wait for Monday's 06:10 cron to produce a diff, sign it,
    then find somebody who could `sudo git pull && sudo bash build.sh` on
    the box. They asked for a button.

WHAT IT COSTS, WHICH IS NOT HIDDEN
    `prepare` re-crawls our own public site: ~410 fetches, under a minute,
    and NO API spend -- the dry run skips embedding entirely.

    `apply` embeds. The last one took about seven minutes, and the box is a
    t4g.medium with 3,823 MB. Measured, in docs/AWS-CAPACITY-REQUEST.md:

        idle .......................................  7.0 s per answer
        reindex running, capped to 1,100 MB ........ 25.5 s per answer
        reindex running, UNCAPPED .................. no answer in 30 s

    The third row is an outage: the process stays `active` and is simply
    paged out. So apply ALWAYS runs under a cap. Slower answers for seven
    minutes is a cost; a bot that stops answering is not one we get to
    choose.

ONE AT A TIME
    Two of these at once would take the box down, and a prepare racing an
    apply would sign one diff and apply another. The lock is a module-level
    single slot, not a queue: a second request is refused with what is
    already running, rather than queued behind something the caller cannot
    see.
"""
from __future__ import annotations

import datetime as dt
import logging
import os
import subprocess
import threading
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

REPO = "/opt/chatbot/ai-core"
ENV_FILE = "/opt/chatbot/.env"

APPLY_MEMORY_CAP_MB = 1100
"""What the reindex is allowed to use. 1,100 MB is the figure the capacity
document measured 25.5-second answers at -- known-degraded and known-alive.
Raising it is how you get the third row of that table."""

PREPARE_TIMEOUT_S = 20 * 60
APPLY_TIMEOUT_S = 45 * 60
"""Generous: the last apply took ~7 minutes, and a run that has genuinely
hung must still end rather than hold the lock for ever."""


@dataclass
class Job:
    """One run. Held in memory; the console shows the current or last one."""

    phase: str
    started_at: dt.datetime
    started_by: str
    finished_at: Optional[dt.datetime] = None
    returncode: Optional[int] = None
    output: str = ""
    error: str = ""
    promoted_collection: str = ""
    _lines: list = field(default_factory=list)

    @property
    def running(self) -> bool:
        return self.finished_at is None

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    @property
    def elapsed_s(self) -> int:
        end = self.finished_at or dt.datetime.now(dt.timezone.utc)
        return int((end - self.started_at).total_seconds())


_lock = threading.Lock()
_current: Optional[Job] = None


def current() -> Optional[Job]:
    return _current


def is_running() -> bool:
    return _current is not None and _current.running


def _cmd(phase: str) -> list:
    """The command line for one phase.

    apply is wrapped in a systemd scope with a hard memory cap. Not a
    courtesy: uncapped, the reindex pushes the serving process into swap
    and patrons get nothing at all.
    """
    py = f"{REPO}/.venv/bin/python"
    inner = (f"set -a; . {ENV_FILE}; set +a; "
             f"cd {REPO} && {py} -m scripts.etl.run_etl --phase {phase}")
    if phase == "apply":
        return ["systemd-run", "--scope", "-q",
                "-p", f"MemoryMax={APPLY_MEMORY_CAP_MB}M",
                "--slice=etlweb.slice", "bash", "-lc", inner]
    return ["bash", "-lc", inner]


def _run(job: Job) -> None:
    global _current
    timeout = APPLY_TIMEOUT_S if job.phase == "apply" else PREPARE_TIMEOUT_S
    try:
        proc = subprocess.run(
            _cmd(job.phase), capture_output=True, text=True,
            timeout=timeout, cwd=REPO,
        )
        job.returncode = proc.returncode
        # stderr first: that is where the traceback is when this fails, and
        # a failure with the reason scrolled off the bottom is a failure
        # somebody will guess at.
        job.output = ((proc.stderr or "") + "\n" + (proc.stdout or "")).strip()
    except subprocess.TimeoutExpired:
        job.returncode = -1
        job.error = (f"{job.phase} did not finish within "
                     f"{timeout // 60} minutes and was stopped.")
        logger.error("ETL %s timed out after %ds", job.phase, timeout)
    except Exception as e:  # noqa: BLE001
        job.returncode = -1
        job.error = f"{type(e).__name__}: {e}"
        logger.exception("ETL %s failed to start", job.phase)
    else:
        # A successful apply is only half of "it is live". The new
        # collection exists but nothing serves from it until promotion, and
        # promotion used to be a hand-edit of .env plus a restart. Chain it
        # here so signing really does mean live.
        if job.phase == "apply" and job.returncode == 0:
            _promote_after_apply(job)
    finally:
        job.finished_at = dt.datetime.now(dt.timezone.utc)


def _promote_after_apply(job: "Job") -> None:
    """Run the promote phase, then switch this process over.

    Failure here does NOT fail the job's apply -- the corpus was built and
    is safe on disk, and the marker records it. It fails the PROMOTION,
    which is the part a person can retry, so it is reported as its own
    line rather than turning a good build into a red run.
    """
    try:
        proc = subprocess.run(
            _cmd_promote(), capture_output=True, text=True,
            timeout=PREPARE_TIMEOUT_S, cwd=REPO,
        )
        job.output = (job.output + "\n" + (proc.stderr or "")
                      + "\n" + (proc.stdout or "")).strip()
        if proc.returncode != 0:
            job.error = ("The corpus was built but promoting it failed, so "
                         "the bot is still answering from the previous one. "
                         "The build is safe on disk; retry the promotion.")
            return
        coll = _applied_collection()
        if coll:
            promote_in_process(coll)
            job.promoted_collection = coll
        else:
            job.error = ("Promoted, but the collection name could not be "
                         "read back from the marker -- this process may "
                         "still be on the old corpus until it restarts.")
    except Exception as e:  # noqa: BLE001
        job.error = f"promotion failed: {type(e).__name__}: {e}"
        logger.exception("ETL promote failed")


def _cmd_promote() -> list:
    py = f"{REPO}/.venv/bin/python"
    return ["bash", "-lc",
            f"set -a; . {ENV_FILE}; set +a; "
            f"cd {REPO} && {py} -m scripts.etl.run_etl --phase promote"]


def _applied_collection() -> str:
    """The collection the latest applied diff names, from its marker."""
    try:
        from scripts.etl import gate

        diff = gate.find_latest_applied_diff()
        if diff is None:
            return ""
        marker = diff.with_suffix(".applied")
        for line in marker.read_text(encoding="utf-8").splitlines():
            if line.startswith("collection:"):
                return line.split(":", 1)[1].strip()
    except Exception:  # noqa: BLE001
        logger.warning("could not read the applied collection", exc_info=True)
    return ""


def start(phase: str, *, started_by: str) -> "tuple[bool, str]":
    """Begin a phase in the background. (started, message)."""
    global _current
    if phase not in ("prepare", "apply"):
        return False, f"unknown phase {phase!r}"
    with _lock:
        if is_running():
            assert _current is not None
            return False, (f"{_current.phase} is already running "
                           f"({_current.elapsed_s}s so far). Wait for it.")
        job = Job(phase=phase, started_at=dt.datetime.now(dt.timezone.utc),
                  started_by=started_by)
        _current = job
    t = threading.Thread(target=_run, args=(job,), daemon=True,
                         name=f"etl-{phase}")
    t.start()
    logger.info("ETL %s started by %s", phase, started_by)
    return True, f"{phase} started"


def promote_in_process(collection: str) -> None:
    """Point THIS process at the new collection.

    The whole reason no restart is needed. Every read of the collection
    name on the serving path is an os.getenv at request time -- search.py's
    _default_collection and the two prefetch helpers in the orchestrator --
    so setting it here takes effect on the very next question. `.env` is
    written separately, by the promote phase, so a later restart comes back
    to the same place.
    """
    os.environ["WEAVIATE_CHUNK_COLLECTION"] = collection
    logger.info("serving collection switched in-process to %s", collection)


def reset_for_tests() -> None:
    global _current
    _current = None


__all__ = ["APPLY_MEMORY_CAP_MB", "Job", "current", "is_running",
           "promote_in_process", "reset_for_tests", "start"]
