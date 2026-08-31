"""Finding a colleague by their job title, or by their name.

WHAT WENT WRONG, AND FOR HOW LONG
    `_staff_by_title` asked `lookup_librarian` for `{"title": ...}`. That
    tool takes only subject / name / campus, so `title` was dropped, its
    "at least one filter" guard then rejected the call, and the function
    returned None on every question it was ever asked. It had never once
    produced an answer.

    The tool could not have worked whatever it was passed: it is backed by
    LibrarianSubject -- the subject-liaison table -- and a job title is not
    a subject. Found 2026-08-31 from a thumbs-down a colleague left in
    August on "who are the web services librarians?", about two people
    whose job title is exactly that.
"""

from __future__ import annotations

from src.api.admin import staff_directory as SD
from src.graph.new_orchestrator import _staff_person_rescue

ROSTER = [
    {"name": "Jerry Yarnetsky", "title": "Web Services Librarian",
     "email": "yarnete@miamioh.edu", "phone": "529-2129", "campus": "King",
     "uid": "yarnete"},
    {"name": "Ken Irwin", "title": "Web Services Librarian",
     "email": "irwinkr@miamioh.edu", "phone": "", "campus": "King",
     "uid": "irwinkr"},
    {"name": "Barry Zaslow", "title": "Music Librarian",
     "email": "zaslowbj@miamioh.edu", "phone": "529-3070",
     "campus": "King Library", "uid": "zaslowbj"},
    {"name": "Christopher Smith", "title": "Library Associate",
     "email": "smithc@miamioh.edu", "phone": "", "campus": "King",
     "uid": "smithc"},
]


class _Scope:
    campus = None


# --- by title -------------------------------------------------------------


def test_a_job_title_that_is_not_a_subject_is_still_findable():
    """The reported failure. Not being a subject liaison is not a reason
    to be unfindable."""
    got = SD.find_by_title("who are the web services librarians?",
                           roster=ROSTER)
    assert [p["name"] for p in got] == ["Jerry Yarnetsky", "Ken Irwin"]


def test_singular_and_plural_are_the_same_job():
    a = SD.find_by_title("who is the web services librarian?", roster=ROSTER)
    b = SD.find_by_title("who are the web services librarians?", roster=ROSTER)
    assert [p["name"] for p in a] == [p["name"] for p in b]


def test_one_generic_word_is_not_a_title_question():
    """Without this, "who is the librarian?" names three of the forty
    people whose title ends in the word."""
    assert SD.find_by_title("who is the librarian?", roster=ROSTER) == []
    assert SD.find_by_title("who is the head?", roster=ROSTER) == []


def test_a_subject_question_is_left_alone():
    """Subjects go to the liaison table; this must not intercept them."""
    assert SD.find_by_title("who is the biology librarian", roster=ROSTER) == []


def test_the_tighter_title_wins():
    got = SD.find_by_title("music librarian", roster=ROSTER)
    assert got and got[0]["name"] == "Barry Zaslow"


# --- by name --------------------------------------------------------------


def test_a_named_colleague_is_found():
    got = SD.find_by_name("Does Jerry Yarnetsky work here?", roster=ROSTER)
    assert [p["name"] for p in got] == ["Jerry Yarnetsky"]
    assert got[0]["match"] == "full"


def test_a_surname_in_front_of_a_place_word_is_a_place():
    """"Who is Smith Library" matched a colleague called Smith."""
    assert SD.find_by_name("who is Smith Library", roster=ROSTER) == []


def test_a_full_name_beats_a_bare_surname_in_the_same_sentence():
    got = SD.find_by_name("did Ken Irwin ask Smith about it", roster=ROSTER)
    assert [p["name"] for p in got] == ["Ken Irwin"]


def test_somebody_who_has_left_is_not_here(tmp_path, monkeypatch):
    """`last-date` is the export's own leaving date. Answering with it
    sends a patron to a desk nobody sits at."""
    csv_path = tmp_path / "staff.csv"
    csv_path.write_text(
        "first-name,last-name,title,email,phone,library,uniqueid,last-date\n"
        "Stan,Brownfield,Director of Library Technology,s@x.edu,,King,sb,\n"
        "Gone,Persson,Music Librarian,g@x.edu,,King,gp,2026-01-31\n",
        encoding="utf-8")
    monkeypatch.setattr(SD, "_path", lambda: csv_path)
    roster = SD.load_staff_roster(refresh=True)
    assert [p["name"] for p in roster] == ["Stan Brownfield"]
    SD.load_staff_roster(refresh=True)  # leave no cache behind


# --- the out-of-scope rescue ---------------------------------------------


def _rescue(q, monkeypatch):
    monkeypatch.setattr(SD, "load_staff_roster", lambda **_: ROSTER)
    return _staff_person_rescue(q, _Scope())


def test_a_named_colleague_is_not_out_of_scope(monkeypatch):
    """It was answered "the question you asked is outside that scope" --
    to the colleague it was about."""
    got = _rescue("Does Jerry Yarnetsky work here?", monkeypatch)
    assert got and got[0].startswith("Yes — Jerry Yarnetsky is the Web Services")


def test_a_full_name_needs_no_permission_slip(monkeypatch):
    """The phrasing gate guards the WEAK match. A full name in a sentence
    is unambiguous whatever the sentence says."""
    got = _rescue("what is Ken Irwin email", monkeypatch)
    assert got and "Ken Irwin" in got[0]


def test_yes_is_only_said_when_something_was_asked_yes_or_no(monkeypatch):
    assert not _rescue("Barry Zaslow", monkeypatch)[0].startswith("Yes")
    assert _rescue("is Barry Zaslow here?", monkeypatch)[0].startswith("Yes")


def test_an_ordinary_question_is_still_refused(monkeypatch):
    """This only ever rescues a turn that was going to be refused, so a
    false hit puts a colleague's desk phone in front of somebody who did
    not ask for it."""
    for q in ("who won the Bengals game",
              "who is allowed in King after 10pm",
              "is there a green study room",
              "who is Smith Library"):
        assert _rescue(q, monkeypatch) is None, q
