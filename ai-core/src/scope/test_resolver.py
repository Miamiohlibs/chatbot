"""Scope resolution: which building a question is about.

The rule these cover is that a named building beats a service bound to
another one -- see the block comment above SERVICE_ALIASES in aliases.py.
"""

from src.scope.resolver import resolve_scope

# --- a named building beats a service bound to another one ---------------
#
# "makerspace" and "archivist" sit in LIBRARY_ALIASES because naming one is
# normally a good signal for where to search -- there is one MakerSpace and
# one University Archivist. But they are the OBJECT of a question, never its
# subject.
#
# "does Rentschler have a MakerSpace" resolved to King/Oxford: "makerspace"
# and "rentschler" are the same length and the longest-match tie went the
# wrong way. The bot then answered about the wrong building rather than
# saying no, it is at King. Asked four times during the beta.


def test_a_named_building_wins_over_a_service_from_another_one() -> None:
    scope = resolve_scope("does Rentschler have a MakerSpace")
    assert scope.campus == "hamilton"
    assert scope.library == "rentschler"


def test_the_same_holds_for_the_archivist() -> None:
    scope = resolve_scope("does Rentschler have an archivist")
    assert scope.campus == "hamilton"


def test_a_service_alias_alone_still_carries_its_building() -> None:
    """The reason these are in the table at all -- do not regress it."""
    assert resolve_scope("where is the makerspace").library == "king"
    assert resolve_scope("makerspace hours").library == "king"
    assert resolve_scope("who is the archivist").library == "special"


def test_a_campus_named_beside_a_service_still_wins() -> None:
    assert resolve_scope("is there a makerspace at hamilton").campus == "hamilton"
    scope = resolve_scope("can I use the makerspace at Gardner-Harvey")
    assert scope.campus == "middletown"
