"""Infer a SUBJECT from vocabulary that can only mean one subject.

Operator's decision, 2026-08-20: when a question is obviously about a
discipline, volunteer that discipline's liaison rather than refusing --
"Mozart Piano Sonata No. 13, K331 sheet music" was answered "that is outside
my scope", and a music question is exactly what a subject librarian is for.

Three constraints came with it, and they are the whole design:

  1. HIGH CONFIDENCE ONLY. The vocabulary lives in
     data/subject_exclusive_terms.json and may contain only words that cannot
     plausibly mean anything else in a library. Words that double as ordinary
     English -- business, art, design, health, management -- are banned by
     construction. That is the unsolved everyday-word problem, and this list
     walks around it rather than into it.

  2. THE SUBJECT, NEVER THE PERSON. This returns a subject string that
     matches the Libraries' own liaisons page; who covers it is looked up
     live by the existing lookup_librarian path. Nobody is hardcoded here, so
     the file cannot go stale when staff change -- and the Amos Music Library
     closing is the standing reminder of why that matters.

  3. THE ANSWER MUST SAY IT IS A GUESS. An inferred referral is not the same
     as "who is the chemistry librarian", where the patron named the subject
     and the directory matched it exactly. Only the inferred ones carry the
     caveat; putting it on both would devalue the certain answers until
     nobody reads it.

The file is DATA on purpose: a librarian reviewing this list should not have
to read Python, and striking a word they disagree with should not be a code
change. Rejected terms are kept with status "rejected" rather than deleted,
so the record survives.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Optional

_DATA = Path(__file__).resolve().parent / "data" / "subject_exclusive_terms.json"

LIAISONS_URL = "https://www.lib.miamioh.edu/about/organization/liaisons/"

INFERRED_CAVEAT = (
    "\n\nA note on that suggestion: I matched it from the subject of your "
    "question rather than from anything you told me, so it is my reading and "
    "it may be off. If it looks wrong, the Libraries' full list of subject "
    "librarians is here and you can pick the right one yourself [{n}]."
)


@lru_cache(maxsize=1)
def _load() -> "tuple[tuple[str, tuple[str, ...]], ...]":
    """((subject, terms), ...) for ACTIVE entries only."""
    try:
        raw = json.loads(_DATA.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 -- a missing list must not break a turn
        return ()
    out = []
    for entry in raw.get("subjects", []):
        if entry.get("status") != "active":
            continue
        terms = tuple(t.lower() for t in entry.get("terms", []) if t)
        if terms:
            out.append((entry["subject"], terms))
    return tuple(out)


@lru_cache(maxsize=1)
def _load_special() -> "tuple[str, ...]":
    try:
        raw = json.loads(_DATA.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return ()
    sc = raw.get("special_collections") or {}
    if sc.get("status") != "active":
        return ()
    return tuple(t.lower() for t in sc.get("terms", []) if t)


def _hit(message: str, terms: "tuple[str, ...]") -> Optional[str]:
    """The first term present on WORD boundaries, or None.

    Boundaries matter for the same reason they do in the scope aliases:
    `codex` must not fire inside `codexample`, and `cfr` must not fire inside
    a longer token.
    """
    m = (message or "").lower()
    for t in terms:
        # A trailing plural is the same term: the operator's own example,
        # "bloomberg terminals", missed "bloomberg terminal" by one letter.
        if re.search(r"(?<!\w)" + re.escape(t) + r"s?(?!\w)", m):
            return t
    return None


def infer_subject(message: str) -> "Optional[tuple[str, str]]":
    """(subject, the term that matched) or None."""
    for subject, terms in _load():
        t = _hit(message, terms)
        if t:
            return subject, t
    return None


def looks_like_special_collections(message: str) -> Optional[str]:
    """The matched term for a Special Collections referral, or None.

    Separate from the subjects above because it is not an inference about a
    PERSON: Special Collections & University Archives actually holds local,
    university and family history, so this is a holdings-backed route.
    """
    return _hit(message, _load_special())
