"""Everyone on the staff page is findable, by job title as well as by name.

"Who is the web services librarian?" was answered "Miami doesn't have a
subject librarian listed for 'Web Services'". Two people hold that title
and both are in the roster with an email and a desk phone -- and they are
the colleagues who reported it. Not being a subject liaison is not a
reason to be unfindable, and saying so about a named colleague is a
slight as well as a wrong answer. Raised by the web team 2026-08-27.

52 of the 74 people we hold carry no subject at all, so this is most of
the directory, not an edge case.
"""

from types import SimpleNamespace as NS

import pytest

from src.graph.new_orchestrator import _staff_by_title

_ROSTER = {
    "web services librarian": [
        {"name": "Ken Irwin", "title": "Web Services Librarian",
         "email": "irwinkr@miamioh.edu", "phone": "(513) 529-4212",
         "campus": "Oxford"},
        {"name": "Jerry Yarnetsky", "title": "Web Services Librarian",
         "email": "yarnete@miamioh.edu", "phone": "(513) 529-2129",
         "campus": "Oxford"},
    ],
    "acquisitions librarian": [
        {"name": "Samantha Bobbitt", "title": "Acquisitions Librarian",
         "email": "bobbitsj@miamioh.edu", "phone": "(513) 529-2886",
         "campus": "Oxford"},
    ],
    "library associate": [
        {"name": f"Person {i}", "title": "Library Associate",
         "email": f"p{i}@miamioh.edu", "phone": "", "campus": "Oxford"}
        for i in range(5)
    ],
}


def _deps(roster=None, blow_up=False, no_email=False):
    data = _ROSTER if roster is None else roster

    def _dispatch(call):
        if blow_up:
            raise RuntimeError("the registry is down")
        # Normalised the way the real backend does, so the stub cannot
        # pass on wording the live lookup would miss.
        from src.eval.real_backends import _title_key

        want = _title_key(call.arguments.get("title") or "")
        rows = next((v for k, v in data.items() if _title_key(k) == want), [])
        if no_email:
            rows = [{**r, "email": ""} for r in rows]
        return NS(error=None, data={"librarians": rows})

    return NS(tool_registry=NS(dispatch=_dispatch))


class TestItFindsPeopleWithNoSubject:
    def test_one_holder_is_named_with_contact(self):
        out = _staff_by_title(_deps(), "acquisitions librarian")
        assert out is not None
        answer = out[0]
        assert "Samantha Bobbitt" in answer
        assert "bobbitsj@miamioh.edu" in answer
        assert "(513) 529-2886" in answer

    def test_two_holders_are_both_named(self):
        """Naming one and hiding the other is a worse answer than naming
        neither -- the reader would write to the wrong person and never
        know there was a second."""
        answer = _staff_by_title(_deps(), "web services librarian")[0]
        assert "Ken Irwin" in answer
        assert "Jerry Yarnetsky" in answer

    @pytest.mark.parametrize("asked", [
        "web services librarian",
        "the web services librarian",
        "Web Services Librarian",
        "our web services librarian",
    ])
    def test_the_title_is_matched_through_the_question_s_filler(self, asked):
        """"who is THE web services librarian" and "Web Services
        Librarian" have to reduce to the same thing. The question carries
        filler a job title never does."""
        assert _staff_by_title(_deps(), asked) is not None, asked

    def test_a_crowded_title_names_three_and_counts_the_rest(self):
        """Five Library Associates in one sentence is a list, not an
        answer."""
        answer = _staff_by_title(_deps(), "library associate")[0]
        assert "5 people hold that title" in answer
        assert "2 more" in answer

    def test_it_cites_the_staff_directory(self):
        _answer, cites = _staff_by_title(_deps(), "acquisitions librarian")
        assert cites and "organization/staff" in cites[0]["url"]


class TestItGetsOutOfTheWay:
    def test_a_title_nobody_holds_returns_none(self):
        """None hands the turn back to the subject path, which is right
        for a real subject question -- this must not swallow them."""
        assert _staff_by_title(_deps(), "quantum wizard") is None

    def test_an_empty_ask_returns_none(self):
        assert _staff_by_title(_deps(), "") is None
        assert _staff_by_title(_deps(), "   ") is None

    def test_a_registry_failure_returns_none_rather_than_raising(self):
        assert _staff_by_title(_deps(blow_up=True), "acquisitions librarian") is None

    def test_a_row_with_no_email_is_not_offered_as_a_contact(self):
        """The answer's whole value is being able to write to them."""
        assert _staff_by_title(_deps(no_email=True),
                               "acquisitions librarian") is None


class TestItRunsBeforeTheRefusal:
    def test_the_no_such_subject_refusal_asks_the_title_lookup_first(self):
        """The ordering IS the fix. Behind the refusal it would never
        run."""
        from pathlib import Path

        src = Path("src/graph/new_orchestrator.py").read_text(encoding="utf-8")
        i_title = src.index("by_title = title_lookup(subject_asked)")
        i_refusal = src.index("Miami doesn't have a subject librarian listed")
        assert i_title < i_refusal


class TestTheTitleKey:
    """The normalisation itself, where the matching actually happens."""

    def test_filler_words_are_dropped(self):
        from src.eval.real_backends import _title_key

        assert (_title_key("the web services librarian")
                == _title_key("Web Services Librarian"))

    def test_punctuation_in_a_real_title_does_not_block_a_match(self):
        """These are live titles: "Director, Regional Campus Library",
        "Head, Advise & Instruct Department"."""
        from src.eval.real_backends import _title_key

        assert (_title_key("Head, Advise & Instruct Department")
                == _title_key("head advise instruct department"))

    def test_two_different_titles_stay_different(self):
        from src.eval.real_backends import _title_key

        assert _title_key("Acquisitions Librarian") != _title_key(
            "Business Librarian")
