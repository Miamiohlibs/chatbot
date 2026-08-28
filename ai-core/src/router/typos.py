"""Correct a misspelled word the bot knows, without a hand-written list.

WHY
    "who is in charge of the lirbary" was answered "Miami doesn't have a
    subject librarian listed for 'library leadership'". The same student
    typed it correctly two minutes later and got the Dean's name. The
    transposed r/b was the whole difference.

    The fix at the time was to add `lirbar\\w+` to a pattern -- the fourth
    hand-maintained list of misspellings in the file, after `librarian`,
    `subject` and `makerspace`. Those lists have a problem the operator
    named: every new typo needs a code change, and the only way to learn
    which one is missing is for somebody to hit it and give up. A student
    who mistypes and gets a bad answer does not file a report.

WHAT THIS DOES INSTEAD, AND WHAT THE DATA SAID
    One pass over the message, correcting a token that is an ADJACENT
    LETTER SWAP away from a word the routing turns on. "lirbary" ->
    "library"; "librarain" -> "librarian".

    Swaps only, and that is not an arbitrary restriction -- it is what
    3,133 real questions supported. A first version allowed any single
    edit, and measured against every word patrons have actually typed it
    corrected TEN tokens, of which EIGHT were wrong:

        directory -> director      (a real word, and a real page)
        onesearch -> research      (a product name)
        archivist -> archives      (a real word, and a job title)
        charge    -> charger       borrowed -> borrow
        chapters  -> chargers      point    -> print
        situation -> citation

    Only two were genuine mistypings -- and both were swaps. Frequency
    could not separate them either: "lirbary" appears twice and
    "archivist" once. So the rule is the shape of the error, not its
    rarity. A swap is fingers out of order; a substitution or a dropped
    letter is usually a different word.

    On the same 3,133 questions, swaps-only corrects exactly those two and
    nothing else.

    The hand-written lists in new_orchestrator (`libary`, `libraian`) stay:
    those are dropped letters, which this deliberately does not touch.

    The original text is never replaced. Callers match against both, so a
    correction can only ADD a match -- no phrasing that worked before can
    stop working because of this.
"""
from __future__ import annotations

import re
from functools import lru_cache

# The words the routing actually turns on. Adding one here makes every
# matcher that uses it typo-tolerant at once, which is the whole point --
# the four hand-written lists this replaces each covered exactly one word.
VOCABULARY = frozenset({
    "library", "libraries", "librarian", "librarians",
    "subject", "subjects", "makerspace", "reserves", "reserve",
    "interlibrary", "borrow", "renew", "renewal", "return",
    "hours", "printing", "print", "scanning", "scan",
    "catalog", "catalogue", "database", "databases",
    "citation", "citations", "archives", "archive",
    "collections", "collection", "appointment", "appointments",
    "reference", "research", "checkout", "equipment",
    "laptop", "laptops", "charger", "chargers",
    "dean", "director", "campus", "account",
})

_MIN_LEN = 5
"""Below five letters a transposition reaches too many real words."""

_TOKEN_RE = re.compile(r"[A-Za-z]+")


def _transpositions(word: str) -> "set[str]":
    """Every word one adjacent-letter swap away from `word`."""
    return {word[:i] + word[i + 1] + word[i] + word[i + 2:]
            for i in range(len(word) - 1)
            if word[i] != word[i + 1]}


@lru_cache(maxsize=1)
def _index() -> dict:
    """misspelling -> the vocabulary word it is a swap away from.

    Built once from VOCABULARY. A misspelling that two vocabulary words
    both reach is dropped: a token we cannot read unambiguously is one we
    leave exactly as typed.
    """
    seen: dict = {}
    for word in VOCABULARY:
        if len(word) < _MIN_LEN:
            continue
        for variant in _transpositions(word):
            if variant in VOCABULARY:
                continue          # a swap that lands on another real word
            seen[variant] = word if variant not in seen else None
    return {k: v for k, v in seen.items() if v}


@lru_cache(maxsize=4096)
def correction_for(token: str) -> "str | None":
    """The vocabulary word `token` is a mistyping of, or None."""
    low = token.lower()
    if len(low) < _MIN_LEN or low in VOCABULARY:
        return None
    return _index().get(low)


@lru_cache(maxsize=2048)
def normalise(message: str) -> str:
    """`message` with recognisable mistypings corrected.

    Returns the message UNCHANGED when nothing was corrected, so a caller
    can tell cheaply whether a second match is worth running.
    """
    if not message:
        return message or ""
    out = []
    last = 0
    for m in _TOKEN_RE.finditer(message):
        fixed = correction_for(m.group(0))
        if fixed is None:
            continue
        out.append(message[last:m.start()])
        # Keep the shape the reader typed, so anything that echoes the
        # text does not look like it silently rewrote them.
        out.append(fixed.capitalize() if m.group(0)[:1].isupper() else fixed)
        last = m.end()
    if not out:
        return message
    out.append(message[last:])
    return "".join(out)


__all__ = ["VOCABULARY", "correction_for", "normalise"]
