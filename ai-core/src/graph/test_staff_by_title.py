"""Everyone on the staff page is findable, by job title as well as by name.

"Who is the web services librarian?" was answered "Miami doesn't have a
subject librarian listed for 'Web Services'". Two people hold that title
and both are in the roster with an email and a desk phone -- and they are
the colleagues who reported it. Not being a subject liaison is not a
reason to be unfindable, and saying so about a named colleague is a
slight as well as a wrong answer. Raised by the web team 2026-08-27.

52 of the 74 people we hold carry no subject at all, so this is most of
the directory, not an edge case.

REWRITTEN 2026-08-31. The version below this line used to stub a tool
registry, because `_staff_by_title` asked `lookup_librarian` for a
`title` -- a filter that tool does not take. It dropped the argument, its
"at least one filter" guard rejected the call, and the function returned
None on every question it was ever asked. The tests passed against a
stub of a call that could never have worked; nothing exercised the
answer a patron would get.

They read the staff export now, which is the only place job titles live.
"""

import pytest

from src.api.admin import staff_directory as SD
from src.graph.new_orchestrator import _staff_by_title

_ROSTER = [
    {"name": "Ken Irwin", "title": "Web Services Librarian",
     "email": "irwinkr@miamioh.edu", "phone": "", "campus": "King",
     "uid": "irwinkr"},
    {"name": "Jerry Yarnetsky", "title": "Web Services Librarian",
     "email": "yarnete@miamioh.edu", "phone": "529-2129", "campus": "King",
     "uid": "yarnete"},
    {"name": "Samantha Bobbitt", "title": "Acquisitions Librarian",
     "email": "bobbitsj@miamioh.edu", "phone": "529-2886", "campus": "King",
     "uid": "bobbitsj"},
] + [
    {"name": f"Associate {n}", "title": "Library Associate",
     "email": f"assoc{n}@miamioh.edu", "phone": "", "campus": "King",
     "uid": f"assoc{n}"}
    for n in range(1, 6)
]


class _Deps:
    pass


@pytest.fixture(autouse=True)
def roster(monkeypatch):
    monkeypatch.setattr(SD, "load_staff_roster", lambda **_: _ROSTER)


def _ask(q, campus=""):
    return _staff_by_title(_Deps(), q, campus)


class TestItFindsPeopleWithNoSubject:
    def test_one_holder_is_named_with_contact(self):
        ans, _ = _ask("who is the acquisitions librarian?")
        assert "Samantha Bobbitt" in ans
        assert "bobbitsj@miamioh.edu" in ans and "529-2886" in ans

    def test_two_holders_are_both_named(self):
        ans, _ = _ask("who is the web services librarian?")
        assert "Ken Irwin" in ans and "Jerry Yarnetsky" in ans
        assert "2 people hold that title" in ans

    @pytest.mark.parametrize("asked", [
        "who is the web services librarian",
        "who are the web services librarians?",
        "can you tell me the web services librarian please",
        "web services librarian",
    ])
    def test_the_title_is_matched_through_the_question_s_filler(self, asked):
        ans, _ = _ask(asked)
        assert "Jerry Yarnetsky" in ans or "Ken Irwin" in ans

    def test_a_crowded_title_names_three_and_counts_the_rest(self):
        """Naming all five is a list, not an answer."""
        ans, _ = _ask("who is a library associate?")
        assert "5 people hold that title" in ans
        assert ans.count("@miamioh.edu") == 3
        assert "and 2 more" in ans

    def test_it_cites_the_staff_directory(self):
        _, cites = _ask("who is the acquisitions librarian?")
        assert cites and cites[0]["url"].endswith("/organization/staff/")


class TestItGetsOutOfTheWay:
    def test_a_title_nobody_holds_returns_none(self):
        assert _ask("who is the quidditch librarian?") is None

    def test_an_empty_ask_returns_none(self):
        assert _ask("   ") is None

    def test_a_subject_question_is_left_to_the_liaison_table(self):
        """52 of the 75 people carry no subject, but the ones who DO are
        answered from LibrarianSubject, and this must not intercept them."""
        assert _ask("who is the biology librarian") is None

    def test_a_roster_failure_returns_none_rather_than_raising(self, monkeypatch):
        def boom(**_):
            raise RuntimeError("csv gone")

        monkeypatch.setattr(SD, "load_staff_roster", boom)
        assert _ask("acquisitions librarian") is None

    def test_a_row_with_no_email_is_not_offered_as_a_contact(self, monkeypatch):
        monkeypatch.setattr(SD, "load_staff_roster", lambda **_: [
            {"name": "No Contact", "title": "Acquisitions Librarian",
             "email": "", "phone": "", "campus": "King", "uid": "nc"}])
        assert _ask("acquisitions librarian") is None


class TestItRunsBeforeTheRefusal:
    def test_the_no_such_subject_refusal_asks_the_title_lookup_first(self):
        """"Miami doesn't have a subject librarian listed for X" must not
        be reachable while somebody holds X as a job title."""
        import inspect

        from src.graph import new_orchestrator as NO

        src = inspect.getsource(NO._subject_liaison_short_circuit)
        assert "title_lookup" in src
