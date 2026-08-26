"""A question that names two campuses must reach both.

Seven patrons during the beta asked some form of "is the laptop loan
different at King and Gardner-Harvey". Every one of them got an answer
about ONE campus: the resolver picked whichever alias it saw, retrieval
filtered to that campus, and the post-processor then rejected any
citation from the other one as a scope violation. Three layers, all
agreeing, all wrong -- so this file tests all three.
"""

from src.scope.resolver import campuses_named, resolve_scope


class TestCampusesNamed:
    def test_two_campuses_both_returned_in_reading_order(self):
        got = campuses_named(
            "is the laptop loan period different at King and Gardner-Harvey?"
        )
        assert got == ("oxford", "middletown")

    def test_reading_order_is_the_order_asked(self):
        """Whichever campus is named FIRST is the primary one. The patron
        led with it; the answer should too."""
        assert campuses_named("Gardner-Harvey or King?") == (
            "middletown",
            "oxford",
        )

    def test_one_campus_stays_one(self):
        assert campuses_named("what time does King close today") == ("oxford",)

    def test_no_campus_named_returns_empty(self):
        assert campuses_named("how do I renew a book") == ()

    def test_hamilton_and_oxford(self):
        got = campuses_named("does Rentschler have the same hours as King")
        assert set(got) == {"hamilton", "oxford"}

    def test_same_campus_named_twice_is_not_a_comparison(self):
        got = campuses_named("King Library and BEST Library hours")
        assert got == ("oxford",)


class TestResolveScope:
    def test_comparison_populates_also_campuses(self):
        """Both campuses reach retrieval.

        WHICH one is primary is deliberately left to the old rule
        (longest library alias -- here "gardner-harvey" beats "king"),
        not to reading order. For a comparison it does not matter: both
        campuses are retrieved and both are allowed to be cited, so the
        primary only decides a label. Changing that rule would move
        single-campus scoping too, for no gain here."""
        scope = resolve_scope(
            "is the laptop loan different at King and Gardner-Harvey?"
        )
        assert set(scope.all_campuses) == {"oxford", "middletown"}
        assert scope.campus not in scope.also_campuses

    def test_single_campus_leaves_also_empty(self):
        scope = resolve_scope("what time does King close today")
        assert scope.also_campuses == ()
        assert scope.all_campuses == ("oxford",)

    def test_all_campuses_never_repeats_the_primary(self):
        """Defensive: even if a caller hands us a duplicate, the where
        clause it feeds must not grow a redundant OR branch."""
        scope = resolve_scope("what time does King close today")
        dup = type(scope)(
            **{
                **{
                    f: getattr(scope, f)
                    for f in scope.__dataclass_fields__
                    if f != "also_campuses"
                },
                "also_campuses": ("oxford", "middletown"),
            }
        )
        assert dup.all_campuses == ("oxford", "middletown")


# --- Layer 2: retrieval must reach both campuses -------------------------

from src.retrieval.scope_filter import (  # noqa: E402
    ScopeFilter,
    build_where_clause,
)


def _campus_values(where: dict) -> set:
    """Every campus value anywhere in a where clause."""
    found = set()

    def walk(node):
        if isinstance(node, dict):
            if node.get("path") == ["campus"] and "valueText" in node:
                found.add(node["valueText"])
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(where)
    return found


def _library_values(where: dict) -> set:
    found = set()

    def walk(node):
        if isinstance(node, dict):
            if node.get("path") == ["library"] and "valueText" in node:
                found.add(node["valueText"])
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(where)
    return found


class TestWhereClause:
    def test_single_campus_clause_is_unchanged(self):
        """The ordinary turn must be byte-identical to what it was --
        this change is not allowed to move retrieval for the other 99%
        of traffic."""
        plain = build_where_clause(ScopeFilter(campus="oxford", library="king"))
        with_empty = build_where_clause(
            ScopeFilter(campus="oxford", library="king", also_campuses=())
        )
        assert plain == with_empty
        assert _campus_values(plain) == {"oxford", "all"}

    def test_second_campus_is_reachable(self):
        where = build_where_clause(
            ScopeFilter(
                campus="middletown",
                library="gardner_harvey",
                also_campuses=("oxford",),
            )
        )
        assert _campus_values(where) == {"middletown", "oxford", "all"}

    def test_library_narrowing_yields_to_a_comparison(self):
        """The bug the campus OR alone did not fix.

        scope.library is a HARD filter. A comparison resolves to exactly
        one library -- whichever alias matched longest -- so leaving the
        narrowing in place drops every chunk from the other building,
        which is precisely the half being compared. Widening campus while
        library still narrows accomplishes nothing at all."""
        where = build_where_clause(
            ScopeFilter(
                campus="middletown",
                library="gardner_harvey",
                also_campuses=("oxford",),
            )
        )
        assert _library_values(where) == set(), (
            "a two-campus question must not hard-filter to one building"
        )

    def test_library_still_narrows_when_one_campus(self):
        where = build_where_clause(ScopeFilter(campus="oxford", library="king"))
        assert _library_values(where) == {"king", "all"}


# --- Layer 3: the guard must admit the second campus ---------------------

from src.synthesis.post_processor import (  # noqa: E402
    Citation,
    SynthesizerOutput,
    process_synthesizer_output,
)

_KING = "https://www.lib.miamioh.edu/about/locations/king-library/"
_GH = "https://www.mid.miamioh.edu/library/"


def _two_campus_output() -> SynthesizerOutput:
    return SynthesizerOutput(
        answer="King loans laptops for 4 hours [1]; Gardner-Harvey for 3 days [2].",
        citations=[
            Citation(n=1, url=_KING, snippet="4 hours.", chunk_id="a",
                     campus="oxford", library="king"),
            Citation(n=2, url=_GH, snippet="3 days.", chunk_id="b",
                     campus="middletown", library="gardner_harvey"),
        ],
        confidence="high",
    )


class TestCrossCampusGuard:
    def test_named_second_campus_is_allowed(self):
        result = process_synthesizer_output(
            _two_campus_output(),
            scope_campus="middletown",
            also_campuses=("oxford",),
            url_allowlist={_KING, _GH},
        )
        assert not result.is_refusal, result.message

    def test_unnamed_campus_is_still_rejected(self):
        """This is the whole point of the guard and it must survive.

        Same evidence, but the patron never mentioned Oxford -- an Oxford
        citation is then an answer about a building they are not standing
        in, which is the failure the guard exists to catch."""
        result = process_synthesizer_output(
            _two_campus_output(),
            scope_campus="middletown",
            url_allowlist={_KING, _GH},
        )
        assert result.is_refusal

    def test_third_campus_is_rejected_even_during_a_comparison(self):
        """Naming two campuses licenses those two, not any campus."""
        out = _two_campus_output()
        out.citations.append(
            Citation(n=3, url=_KING, snippet="Rentschler.", chunk_id="c",
                     campus="hamilton", library="rentschler")
        )
        result = process_synthesizer_output(
            out,
            scope_campus="middletown",
            also_campuses=("oxford",),
            url_allowlist={_KING, _GH},
        )
        assert result.is_refusal
