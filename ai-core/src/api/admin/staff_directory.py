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


_roster_cache: "list | None" = None


def load_staff_roster(*, refresh: bool = False) -> list:
    """Everyone on the staff page: name, title, email, phone, campus.

    SEPARATE FROM load_staff_identifiers ON PURPOSE, and the difference is
    the whole reason this module says it never says WHO.

    That function answers "should this conversation count as patron use",
    and a yes/no answers it -- so it reduces the file to a set of strings
    and keeps no names. This one answers a question a PATRON asked out
    loud: "who is the web services librarian?". The names, titles and desk
    phones it returns are already published on the Libraries staff page;
    what would be wrong is attaching them to somebody's conversation, and
    nothing here does that.

    Added 2026-08-31. `lookup_librarian` is backed by LibrarianSubject --
    the subject-liaison table -- so a job title was not in the bot's world
    at all. "Who are the web services librarians?" was answered "Miami
    doesn't have a subject librarian listed for Web Services", about two
    colleagues whose job title is exactly that.
    """
    global _roster_cache
    if _roster_cache is not None and not refresh:
        return _roster_cache

    people: list = []
    path = _path()
    try:
        with path.open(newline="", encoding="utf-8-sig") as fh:
            for row in csv.DictReader(fh):
                # Somebody who has left is not "here". `last-date` is the
                # export's own leaving date; a row that carries one is
                # history, and answering with it would send a patron to a
                # desk nobody sits at.
                if (row.get("last-date") or "").strip():
                    continue
                first = (row.get("first-name") or "").strip()
                last = (row.get("last-name") or "").strip()
                title = (row.get("title") or "").strip()
                mail = (row.get("email") or "").strip()
                if not (first or last) or not title:
                    continue
                people.append({
                    "name": f"{first} {last}".strip(),
                    "title": title,
                    "email": mail,
                    "phone": (row.get("phone") or "").strip(),
                    "campus": (row.get("library") or "").strip(),
                    "uid": (row.get("uniqueid") or "").strip().lower(),
                })
    except FileNotFoundError:
        logger.info("no staff directory at %s -- title lookups will find "
                    "nobody; nothing else changes", path)
    except Exception:  # noqa: BLE001 -- a malformed export must not break a turn
        logger.warning("could not read the staff roster at %s", path,
                       exc_info=True)

    _roster_cache = people
    return _roster_cache


# Words that carry no signal in a job title. Matching on them would make
# "who is the librarian?" return all seventy-seven people.
_TITLE_STOP = frozenset({
    "the", "a", "an", "of", "and", "for", "our", "your", "is", "are", "who",
    "whom", "what", "does", "do", "work", "here", "at", "in", "on", "we",
    "have", "has", "there", "any", "someone", "somebody", "person", "staff",
    "miami", "university", "libraries", "library", "please", "tell", "me",
    "about", "contact", "email", "phone", "number", "name",
    # Conversational wrapping. None of it can appear in a job title, and
    # leaving it in means "can you tell me the web services librarian
    # please" requires the title to contain the word "can".
    "can", "you", "could", "would", "will", "know", "find", "looking",
    "need", "want", "help", "talk", "speak", "reach", "get",
})


def _title_words(text: str) -> list:
    out = []
    for w in re.findall(r"[a-z]+", (text or "").lower()):
        if w in _TITLE_STOP or len(w) < 3:
            continue
        # "librarians" and "librarian" are the same job. Crude, and crude
        # is right here: a stemmer would be a dependency and a surprise.
        if w.endswith("s") and len(w) > 4 and not w.endswith("ss"):
            w = w[:-1]
        out.append(w)
    return out


def find_by_title(asked: str, *, roster: "list | None" = None) -> list:
    """Everyone whose job title matches what was asked. Best matches first.

    Every significant word in the question that is not noise has to appear
    in the title. "web services librarian" matches "Web Services
    Librarian"; "web services" matches it too; "librarian" alone matches
    nothing, because `librarian` is stopped out of a one-word question by
    being the only word left -- see the guard below.
    """
    words = _title_words(asked)
    # One generic word is not a question about a job title. Without this,
    # "who is the librarian?" names three of the forty people whose title
    # ends in the word.
    if not words or (len(words) == 1 and words[0] in
                     {"librarian", "manager", "director", "head", "dean",
                      "coordinator", "associate", "assistant", "specialist"}):
        return []
    hits = []
    for p in (roster if roster is not None else load_staff_roster()):
        title_words = set(_title_words(p["title"]))
        if all(w in title_words for w in words):
            # A title with nothing spare is a better answer than one that
            # happens to contain the words among others.
            hits.append((len(title_words) - len(words), p))
    hits.sort(key=lambda pair: (pair[0], pair[1]["name"]))
    return [p for _, p in hits]


# A surname immediately followed by one of these is a place, not a person.
# "Who is Smith Library" matched three colleagues called Smith.
_PLACE_AFTER = frozenset({
    "library", "libraries", "hall", "building", "center", "centre", "room",
    "wing", "annex", "gallery", "lab", "commons", "collection", "campus",
})


def find_by_name(asked: str, *, roster: "list | None" = None) -> list:
    """Everyone on the staff page whose name appears in the question.

    For "does <person> work here?" -- which the bot answered "that is
    outside my scope", about a colleague, to that colleague.

    A FULL name is taken at once. A surname alone is taken only when it is
    not standing in front of a place word, because seventy-five surnames
    include several that are also ordinary English and several that are
    also buildings here. The cost of being loose is a colleague's desk
    phone put in front of somebody who did not ask for it.
    """
    words = re.findall(r"[a-z]+", (asked or "").lower())
    if not words:
        return []
    low = " " + " ".join(words) + " "
    full, surname_only = [], []
    for p in (roster if roster is not None else load_staff_roster()):
        parts = re.findall(r"[a-z]+", p["name"].lower())
        if not parts:
            continue
        surname = parts[-1]
        if len(surname) < 4 or f" {surname} " not in low:
            continue
        # The word after the surname, if there is one.
        try:
            after = words[words.index(surname) + 1]
        except (ValueError, IndexError):
            after = ""
        if after in _PLACE_AFTER:
            continue
        first = parts[0]
        if len(first) >= 3 and f" {first} " in low:
            full.append(p)
        else:
            surname_only.append(p)
    # A full-name match is a different level of certainty, and the caller
    # is told which it got: "Ken Irwin" in a sentence is unambiguous
    # whatever else the sentence says, while a bare surname needs the
    # phrasing to be asking about a person before it means anything.
    chosen = full or surname_only
    kind = "full" if full else "surname"
    return [dict(p, match=kind) for p in chosen]


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
