"""
Resolve a user message + session origin into a Scope object.

A Scope is the (campus, library) tuple every retrieval call carries.
Without a scope, retrieval cannot enforce the cross-campus refusal that
prevents King's hours being served as Hamilton's hours.

See plan: Data preparation playbook §8 -- Campus and library scope resolution.

================================================================================
ALGORITHM (one pass per user message)
================================================================================

1. Substring-match the lowercased user message against LIBRARY_ALIASES.
   Use longest-match-wins so "Art and Architecture Library" beats "Art".
2. If a library matched -> set scope.library + derive scope.campus from it.
3. Otherwise, substring-match against CAMPUS_ALIASES. If matched, set
   scope.campus only (library stays null -- "all libraries on this campus").
4. Otherwise, fall back to the session_origin campus (regional widget user).
5. Otherwise, default to ("oxford", None).

The matcher is intentionally simple. We do NOT use the LLM for scope
detection -- it would add latency and cost on every turn, and the failure
mode (LLM picks the wrong campus) is exactly the failure mode we're trying
to engineer out. Keep it deterministic.
"""

import re
from dataclasses import dataclass
from typing import Literal, Optional
from urllib.parse import urlparse

from src.scope.aliases import (
    BLOCKED_CAMPUS_PHRASES,
    CAMPUS_ALIASES,
    CAMPUS_DISPLAY,
    Campus,
    DOMAIN_TO_CAMPUS,
    LIBRARY_ALIASES,
    SERVICE_ALIASES,
    LIBRARY_DISPLAY,
    LIBRARY_TO_CAMPUS,
    Library,
)


ScopeSource = Literal["library_alias", "campus_alias", "session_origin",
                      "previous_turn", "default"]
"""Where the scope came from.

`previous_turn` is inherited by a short follow-up that named no building of
its own -- "and the Oxford one", "are you sure" -- and only ever replaces
`default`, so a message that DID name somewhere keeps what it said."""
"""Where the resolved scope came from -- logged so we can audit how often
defaults fire vs explicit signals."""


@dataclass(frozen=True)
class Scope:
    """The resolved retrieval scope for a single user turn.

    Every retrieval call (`search_kb(query, scope)`) carries this. The
    Weaviate query gets `where: {campus: scope.campus}` always, plus
    `library: scope.library OR "all"` when `scope.library` is set.
    """

    campus: Campus
    library: Optional[Library]
    source: ScopeSource

    also_campuses: "tuple[Campus, ...]" = ()
    """Other campuses this ONE question also asked about.

    "is the loan period for laptops different at King Library and the
    Gardner-Harvey Library?" names two buildings on two campuses. A single
    `campus` cannot hold that, so the longest alias won and the answer came
    back about Middletown alone -- with a liaison directory link that has
    nothing to do with laptops. Asked seven times during the beta.

    Empty for the ordinary single-campus turn, so nothing downstream
    changes shape unless a question really did name more than one place.
    `campus` stays the primary: it is what the answer leads with, and what
    a caller that ignores this field still gets right.
    """

    @property
    def campus_display(self) -> str:
        return CAMPUS_DISPLAY[self.campus]

    @property
    def library_display(self) -> Optional[str]:
        return LIBRARY_DISPLAY[self.library] if self.library else None

    @property
    def is_explicit(self) -> bool:
        """True if the user gave a clear scope signal (vs default fallback)."""
        return self.source in ("library_alias", "campus_alias")

    @property
    def all_campuses(self) -> "tuple[Campus, ...]":
        """Every campus this turn may cite from, primary first."""
        return (self.campus, *[c for c in self.also_campuses
                               if c != self.campus])

    def as_filter(self) -> dict:
        """Serialize to the dict shape the retriever expects."""
        return {
            "campus": self.campus,
            "library": self.library,
            "source": self.source,
            "also_campuses": list(self.also_campuses),
        }


def _longest_alias_match(haystack: str, alias_table: dict[str, object]) -> Optional[str]:
    """Return the longest alias that matches haystack on WORD BOUNDARIES,
    or None.

    Both `haystack` and table keys must already be lowercased.

    Word-boundary match (not raw substring) is critical: "I'm looking
    for a book" must NOT trigger the `king` library alias because
    `king` happens to be a substring of `looking`. Same for `sword`
    inside `password`, `wertz` inside (hypothetical) longer words, etc.

    Implementation: for each alias, scan for occurrences and check
    that the chars immediately before and after are NOT word
    characters (alphanumeric or underscore). Faster than compiling
    one regex per alias for the small (~70 alias) table.

    O(n*m) scan -- fine for our ~70 aliases. Premature optimization
    (Aho-Corasick, trie) hurts readability and has no measurable effect.
    """
    best: Optional[str] = None
    haylen = len(haystack)
    for alias in alias_table:
        # Find all occurrences and check word-boundary on each.
        start = 0
        while True:
            idx = haystack.find(alias, start)
            if idx < 0:
                break
            # Char before alias must be non-word (or start of string).
            before_ok = idx == 0 or not haystack[idx - 1].isalnum() and haystack[idx - 1] != "_"
            # Char after alias must be non-word (or end of string).
            end_idx = idx + len(alias)
            after_ok = (
                end_idx == haylen
                or (not haystack[end_idx].isalnum() and haystack[end_idx] != "_")
            )
            if before_ok and after_ok:
                if best is None or len(alias) > len(best):
                    best = alias
                break  # found a valid occurrence; longer-alias check handled at outer level
            start = idx + 1
    return best


def resolve_session_origin(origin_url: Optional[str]) -> Optional[Campus]:
    """Extract a campus from a Socket.IO/HTTP `Origin` header URL.

    Returns None if the origin is unknown or malformed -- caller falls
    back to the Oxford default.
    """
    if not origin_url:
        return None
    try:
        host = urlparse(origin_url).hostname
    except (ValueError, AttributeError):
        return None
    if host is None:
        return None
    return DOMAIN_TO_CAMPUS.get(host.lower())



# A comparison does not have to name the campuses. "Is ILL faster at Oxford
# or the regionals?" names one side by a group word, and "Can I print at any
# library?" names none at all -- both are questions about more than one
# campus, and both retrieved one.
#
# THE BOUNDARY THAT MATTERS: "Tell me about the regional library" (singular,
# no comparison) must still ask WHICH ONE rather than answering about both.
# Gold xc_regional_unspecified expects a clarify, so a group word cannot be
# allowed to blanket-trigger a comparison -- only the plural/every-of forms
# below count, and the bare singular deliberately does not appear here.
_REGIONALS_RE = re.compile(
    r"\b(the\s+)?regionals\b"
    r"|\bregional\s+(campuses|libraries)\b"
    r"|\bboth\s+regionals?\b",
    re.IGNORECASE,
)
_EVERY_CAMPUS_RE = re.compile(
    r"\b(any|each|every|all|which|whichever)\s+"
    r"(campus|campuses|librar(y|ies)|location|locations)\b"
    r"|\ball\s+(three\s+)?campuses\b"
    r"|\bacross\s+campuses\b",
    # NOT a bare "campus library": "where is the campus library" means the
    # one on MY campus, not all of them. "WHICH campus library" is already
    # caught by the determiner list above, which is what makes it a
    # comparison.
    re.IGNORECASE,
)

_REGIONAL_CAMPUSES: "tuple[Campus, ...]" = ("hamilton", "middletown")
_ALL_CAMPUSES: "tuple[Campus, ...]" = ("oxford", "hamilton", "middletown")


def _group_campuses(hay: str) -> "tuple[Campus, ...]":
    """Campuses named by a GROUP word rather than by name."""
    if _EVERY_CAMPUS_RE.search(hay):
        return _ALL_CAMPUSES
    if _REGIONALS_RE.search(hay):
        return _REGIONAL_CAMPUSES
    return ()


def campuses_named(user_message: str) -> "tuple[Campus, ...]":
    """Every campus the message names, in the order they appear.

    A comparison question is a normal thing to ask -- "is the loan period
    for laptops different at King Library and the Gardner-Harvey Library?"
    -- and the resolver could only ever return one campus for it. The
    longest alias won, which is arbitrary: it answered about Middletown
    alone and said it had no information, while the Oxford half was
    answerable.

    Buildings and campus names both count, and both resolve to a campus.
    Order matters and is the order of appearance, because the answer should
    address them the way the patron asked.
    """
    hay = (user_message or "").lower()
    if any(p in hay for p in BLOCKED_CAMPUS_PHRASES):
        return ()

    found: list = []
    for alias, library in LIBRARY_ALIASES.items():
        if alias in SERVICE_ALIASES:
            continue
        pos = _alias_position(hay, alias)
        if pos is not None:
            found.append((pos, LIBRARY_TO_CAMPUS[library]))
    for alias, campus in CAMPUS_ALIASES.items():
        pos = _alias_position(hay, alias)
        if pos is not None:
            found.append((pos, campus))

    out: list = []
    for _pos, campus in sorted(found):
        if campus not in out:
            out.append(campus)

    # Group words come AFTER the named ones, so "Oxford or the regionals"
    # keeps Oxford primary -- the patron led with it. A group word alone
    # ("can I print at any library?") supplies the whole list.
    for campus in _group_campuses(hay):
        if campus not in out:
            out.append(campus)
    return tuple(out)


def _alias_position(haystack: str, alias: str) -> "Optional[int]":
    """Where `alias` starts in `haystack` on word boundaries, else None.

    Same boundary rule as _longest_alias_match -- "king" inside "looking"
    is not a building.
    """
    start = 0
    while True:
        i = haystack.find(alias, start)
        if i < 0:
            return None
        before_ok = i == 0 or not (haystack[i - 1].isalnum()
                                   or haystack[i - 1] == "_")
        end = i + len(alias)
        after_ok = end >= len(haystack) or not (haystack[end].isalnum()
                                                or haystack[end] == "_")
        if before_ok and after_ok:
            return i
        start = i + 1


def resolve_scope(
    user_message: str,
    session_origin_campus: Optional[Campus] = None,
) -> Scope:
    """Resolve a user message + session origin into a Scope.

    Args:
        user_message: Raw user text. Empty string is allowed (defaults fire).
        session_origin_campus: Campus inferred from the chat widget's host
            at connect time. Pre-resolve via `resolve_session_origin()` so
            this function doesn't need to know about URLs.

    Returns:
        A Scope. Never None.

    Examples:
        >>> resolve_scope("when does Wertz close tonight?")
        Scope(campus='oxford', library='wertz', source='library_alias')

        >>> resolve_scope("hours at the hamilton campus library")
        Scope(campus='hamilton', library='rentschler', source='library_alias')

        >>> resolve_scope("can I print here?")
        Scope(campus='oxford', library=None, source='default')

        >>> resolve_scope("can I print here?", session_origin_campus="middletown")
        Scope(campus='middletown', library=None, source='session_origin')
    """
    haystack = (user_message or "").lower()

    # A question can name more than one place. Worked out once here and
    # attached to whatever scope the rules below settle on, so the primary
    # campus is chosen exactly as it always was and the extra campuses ride
    # along -- a caller that ignores them behaves identically to before.
    _named = campuses_named(user_message)

    # Suppress campus-alias matching when a known false-positive phrase is
    # present (e.g., "Hamilton Journal-News" -- the newspaper, not the
    # campus). Library-alias matching is unaffected.
    campus_matching_blocked = any(
        phrase in haystack for phrase in BLOCKED_CAMPUS_PHRASES
    )

    # 1. Library alias (most specific)
    lib_match = _longest_alias_match(haystack, LIBRARY_ALIASES)

    # A named building beats a service bound to a different one. "does
    # Rentschler have a MakerSpace" is a question ABOUT Rentschler; the
    # MakerSpace is what is being asked about, not where. Without this the
    # longest-match tie handed the scope to King and the bot answered about
    # the wrong building instead of saying the MakerSpace is at King.
    if lib_match in SERVICE_ALIASES:
        building_only = {a: lib for a, lib in LIBRARY_ALIASES.items()
                         if a not in SERVICE_ALIASES}
        building_match = _longest_alias_match(haystack, building_only)
        if building_match is not None:
            lib_match = building_match

    if lib_match is not None:
        library: Library = LIBRARY_ALIASES[lib_match]
        lib_campus = LIBRARY_TO_CAMPUS[library]

        # Cross-check: if the user ALSO named a different campus
        # explicitly ("Where are special collections at Hamilton?"),
        # the campus signal wins. The library name is then a service
        # mention, not a building selection -- the synthesizer's
        # services_offered truth table will refuse appropriately.
        if not campus_matching_blocked:
            campus_match = _longest_alias_match(haystack, CAMPUS_ALIASES)
            if campus_match is not None:
                campus_from_alias = CAMPUS_ALIASES[campus_match]
                if campus_from_alias != lib_campus:
                    return Scope(
            campus=campus_from_alias,
            library=None,
            source="campus_alias",
            also_campuses=tuple(c for c in _named if c != campus_from_alias),
        )

        return Scope(
            campus=lib_campus,
            library=library,
            source="library_alias",
            also_campuses=tuple(c for c in _named if c != lib_campus),
        )

    # 2. Campus alias (no library narrow-down)
    if not campus_matching_blocked:
        campus_match = _longest_alias_match(haystack, CAMPUS_ALIASES)
        if campus_match is not None:
            return Scope(
            campus=CAMPUS_ALIASES[campus_match],
            library=None,
            source="campus_alias",
            also_campuses=tuple(c for c in _named if c != CAMPUS_ALIASES[campus_match]),
        )

    # 3. Session origin (regional-campus widget user)
    if session_origin_campus is not None:
        return Scope(
            campus=session_origin_campus,
            library=None,
            source="session_origin",
            also_campuses=tuple(c for c in _named if c != session_origin_campus),
        )

    # 4. Default: Oxford, no specific library
    return Scope(campus="oxford", library=None, source="default")
