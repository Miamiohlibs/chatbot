"""Who works here, for the sole purpose of not counting them as patrons.

WHAT THIS READS
    staff-members.csv, the Libraries' own staff export. It carries names,
    titles, phone numbers, supervisors and start dates. NONE of that is
    loaded. Two columns are read -- `email` and `uniqueid` -- and reduced to
    a set of strings before anything else happens.

WHAT IT NEVER DOES
    Say who. The operator asked to know that a conversation came from staff
    and explicitly did not ask to know which one, and there is no reason the
    dashboard needs it: the question being answered is "should this count as
    patron use", and a yes/no answers it. So the label is "staff test" and
    the reason says an address appeared, not whose.

    That is a deliberate limit, not an oversight. A dashboard that names the
    librarian who typed something turns a usage measurement into a record of
    who was testing when, which nobody asked for and which would change how
    people use the thing.

THE FILE IS NOT IN THE REPOSITORY
    It is gitignored and has never been committed -- 132 colleagues' contact
    details do not belong in a git history. If it is missing the matching
    simply does not happen; nothing else changes.

NETID MATCHING IS DELIBERATELY TIMID
    The shortest NetID in the file is three characters, and three characters
    match inside ordinary words. Only NetIDs of five or more are matched on
    their own, and only on a word boundary. Everyone is still caught by
    their address, which is what the booking flow asks for anyway.
"""

from __future__ import annotations

import csv
import logging
import os
import re
from pathlib import Path

logger = logging.getLogger(__name__)

MIN_NETID_LEN = 5

_cache: "dict | None" = None


def _path() -> Path:
    return Path(os.getenv(
        "STAFF_DIRECTORY_CSV",
        # parents: admin -> api -> src -> ai-core -> repo root.
        str(Path(__file__).resolve().parents[4] / "staff-members.csv")))


def load_staff_identifiers(*, refresh: bool = False) -> dict:
    """{"emails": frozenset, "netids": frozenset}. Never raises.

    Cached: this runs on every dashboard page load and the file does not
    change between deploys.
    """
    global _cache
    if _cache is not None and not refresh:
        return _cache

    emails: set = set()
    netids: set = set()
    path = _path()
    try:
        with path.open(newline="", encoding="utf-8-sig") as fh:
            for row in csv.DictReader(fh):
                mail = (row.get("email") or "").strip().lower()
                if "@" in mail:
                    emails.add(mail)
                uid = (row.get("uniqueid") or "").strip().lower()
                if uid.isalnum() and len(uid) >= MIN_NETID_LEN:
                    netids.add(uid)
    except FileNotFoundError:
        logger.info("no staff directory at %s -- staff addresses will not be "
                    "matched; nothing else changes", path)
    except Exception:  # noqa: BLE001 -- a malformed export must not 500 a page
        logger.warning("could not read the staff directory at %s", path,
                       exc_info=True)

    _cache = {"emails": frozenset(emails), "netids": frozenset(netids)}
    return _cache


def looks_like_staff(text: str) -> bool:
    """True if a staff address or NetID appears in `text`.

    Returns a BOOLEAN, not the match. The caller has no use for which person
    it was and the dashboard must not be able to show it.
    """
    if not text:
        return False
    low = text.lower()
    ids = load_staff_identifiers()

    if any(mail in low for mail in ids["emails"]):
        return True

    words = set(re.findall(r"[a-z0-9]{%d,}" % MIN_NETID_LEN, low))
    return bool(words & ids["netids"])


__all__ = ["MIN_NETID_LEN", "load_staff_identifiers", "looks_like_staff"]
