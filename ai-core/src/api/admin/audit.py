"""Who did what, on the surfaces where doing it matters.

WHY THIS EXISTS
    Every dangerous action on this console used to be gated by a shared
    passphrase typed into a box beside a name typed into another box. That
    is a lock, but it is not a record: the name is whatever the person
    typing chose to write, and the passphrase is one string five people
    know. "qum@miamioh.edu paused the service" meant "somebody who knows
    the passphrase typed that address".

    Once Miami SSO establishes who is asking, the passphrase stops earning
    its place -- it is a second copy of a check the IdP already did, and it
    is the reason a librarian has to keep a shared secret in a note
    somewhere. So on an authenticated request it is dropped, and what
    replaces it is this: an append-only line saying who, what and when,
    written from the session rather than from a form field.

    Operator, 2026-08-30: "每次进行危险操作...就不用配备密码了 直接记录log就行".

WHAT IT DOES NOT DO
    It does not replace the passphrase for a caller holding the shared URL
    key. That caller is anonymous -- see `Caller` in sso.py -- and a log
    line naming an anonymous caller records nothing worth having. The
    passphrase stays on that path, which is also the path the console
    falls back to during an IdP outage.

WHY A FILE AND NOT A TABLE
    It has to survive the things it is most likely to be read after. A
    database outage, a bad migration and a rollback are all moments when
    somebody wants to know what was done in the last hour, and all three
    are moments when Postgres is the wrong place to have put it. One JSONL
    file per month, appended with O_APPEND so concurrent writers cannot
    interleave a line, and readable with `tail` when the console itself is
    what is broken.

    A write that fails must not take the action down with it -- refusing to
    let anyone stop the bot because the disk is full is a worse failure
    than an unrecorded pause. But it must not vanish either, or dropping
    the passphrase bought nothing: the fallback is the application log,
    which journald has already durably stored somewhere else.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

AUDIT_DIR = Path(os.getenv(
    "ADMIN_AUDIT_DIR", "/opt/chatbot/ai-core/data/audit"))

# Actions worth a line. Naming them here rather than passing free strings
# keeps the log greppable: a reader filtering for every corpus rebuild
# should not have to know which of four spellings the caller used.
CORPUS_FETCH = "corpus.fetch"
CORPUS_APPROVE = "corpus.approve"
CORPUS_REJECT = "corpus.reject"
CORPUS_INCLUDE = "corpus.include"
SERVICE_PAUSE = "service.pause"
SERVICE_RESUME = "service.resume"

ACTION_LABELS = {
    CORPUS_FETCH: "re-crawled the site",
    CORPUS_APPROVE: "approved a corpus rebuild",
    CORPUS_REJECT: "sent a corpus diff back",
    CORPUS_INCLUDE: "put an excluded page back",
    SERVICE_PAUSE: "took the bot out of service",
    SERVICE_RESUME: "put the bot back in service",
}


def _month_file(when: dt.datetime) -> Path:
    return AUDIT_DIR / f"actions-{when:%Y-%m}.jsonl"


def _client_ip(request: Any) -> str:
    """Best effort, and never a reason to fail.

    Behind nginx the peer address is always 127.0.0.1, so the forwarded
    header is the only thing that distinguishes two operators. It is also
    caller-supplied and therefore a claim, not a fact -- recorded as one
    field among several rather than as identity.
    """
    if request is None:
        return ""
    try:
        fwd = (request.headers.get("x-forwarded-for") or "").split(",")[0]
        if fwd.strip():
            return fwd.strip()[:60]
        client = getattr(request, "client", None)
        return (getattr(client, "host", "") or "")[:60]
    except Exception:  # noqa: BLE001 -- an audit line is not worth a 500
        return ""


def record(action: str, *, who: Any = None, target: str = "",
           detail: str = "", request: Any = None,
           when: Optional[dt.datetime] = None) -> bool:
    """Write one line. Returns whether it reached the file.

    `who` is the Caller from the guard. Its `authenticated` flag is
    recorded verbatim, because a reader six months from now needs to know
    whether the name in the line was established by Miami's IdP or typed
    into a form by whoever held the shared key.
    """
    when = when or dt.datetime.now(dt.timezone.utc)
    row = {
        "at": when.isoformat(timespec="milliseconds"),
        "action": action,
        "actor": (getattr(who, "uid", "") or "") if who is not None else "",
        "authenticated": bool(getattr(who, "authenticated", False)),
        "role": (getattr(who, "role", "") or "") if who is not None else "",
        "target": target[:400],
        "detail": detail[:1000],
        "ip": _client_ip(request),
    }
    line = json.dumps(row, ensure_ascii=False)
    try:
        AUDIT_DIR.mkdir(parents=True, exist_ok=True)
        with _month_file(when).open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        return True
    except OSError as exc:
        # Loud, and still recorded -- journald has this line even when the
        # file does not. Dropping the passphrase is only defensible while
        # the record survives somewhere.
        logger.error("AUDIT WRITE FAILED (%s) -- the action still happened: %s",
                     exc, line)
        return False


def read_recent(limit: int = 200, *,
                months: int = 3,
                when: Optional[dt.datetime] = None) -> list:
    """The most recent entries, newest first.

    Reads whole month files rather than seeking: the largest of these is a
    few hundred lines, because it records decisions and not traffic.
    """
    when = when or dt.datetime.now(dt.timezone.utc)
    rows: list = []
    seen: set = set()
    cursor = dt.date(when.year, when.month, 1)
    for _ in range(max(1, months)):
        path = AUDIT_DIR / f"actions-{cursor:%Y-%m}.jsonl"
        if str(path) not in seen:
            seen.add(str(path))
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                text = ""
            for raw in text.splitlines():
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    rows.append(json.loads(raw))
                except ValueError:
                    # One corrupt line must not hide the rest of the month.
                    rows.append({"at": "", "action": "unreadable line",
                                 "actor": "", "authenticated": False,
                                 "detail": raw[:200], "target": "", "ip": ""})
        cursor = (cursor - dt.timedelta(days=1)).replace(day=1)
    # Position within the file breaks a tie, because a timestamp can. Two
    # actions in the same instant -- a pause and the resume that undoes it
    # -- would otherwise come back in the order they were WRITTEN under a
    # heading that says newest first, which is the one ordering a reader
    # cannot detect is wrong. Lines are appended, so a later index is a
    # later action.
    numbered = list(enumerate(rows))
    numbered.sort(key=lambda pair: (str(pair[1].get("at") or ""), pair[0]),
                  reverse=True)
    return [r for _, r in numbered[:max(1, limit)]]


def describe(row: dict) -> str:
    """One sentence for the console. Falls back to the raw action name so
    a line written by a newer build is still legible on an older one."""
    return ACTION_LABELS.get(str(row.get("action") or ""),
                             str(row.get("action") or "did something"))
