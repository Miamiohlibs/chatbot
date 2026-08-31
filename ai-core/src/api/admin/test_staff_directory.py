"""Matching staff by address or NetID, without recording who.

The operator asked for conversations from staff to be marked and explicitly
said they do not need to know which staff member. That is a design
constraint, not a nicety: a dashboard that names the librarian who typed
something turns a usage measurement into a record of who was testing when.
"""

import pytest

from src.api.admin.staff_directory import (
    MIN_NETID_LEN,
    load_staff_identifiers,
    looks_like_staff,
)


@pytest.fixture
def directory(tmp_path, monkeypatch):
    csv = tmp_path / "staff.csv"
    csv.write_text(
        "first-name,last-name,email,uniqueid\n"
        "Ann,Abbott,abbotta@miamioh.edu,abbotta\n"
        "Bo,Chen,chenb2@miamioh.edu,chenb2\n"
        "Cy,Diaz,diazc@miamioh.edu,qum\n"          # a 3-char NetID
        "No,Id,,\n",                                # a row with neither
        encoding="utf-8")
    monkeypatch.setenv("STAFF_DIRECTORY_CSV", str(csv))
    load_staff_identifiers(refresh=True)
    yield
    monkeypatch.delenv("STAFF_DIRECTORY_CSV", raising=False)
    load_staff_identifiers(refresh=True)


# --- what it matches -------------------------------------------------------


def test_a_staff_address_is_matched(directory):
    assert looks_like_staff("book a room for abbotta@miamioh.edu") is True


def test_a_staff_netid_on_its_own_is_matched(directory):
    assert looks_like_staff("my netid is chenb2") is True


def test_a_patron_address_is_not(directory):
    assert looks_like_staff("student99@miamioh.edu wants a room") is False


def test_matching_ignores_case(directory):
    assert looks_like_staff("ABBOTTA@MIAMIOH.EDU") is True


# --- what it must NOT do ---------------------------------------------------


def test_it_answers_whether_not_who(directory):
    # A boolean by construction. There is nothing for a caller to leak.
    assert looks_like_staff("abbotta@miamioh.edu") is True
    assert isinstance(looks_like_staff("abbotta@miamioh.edu"), bool)


def test_attribution_never_learns_a_name(directory):
    """The identifier load stays identifiers.

    An address inevitably CONTAINS a surname -- abbotta@miamioh.edu is
    derived from it, and no loader can undo that. What we control is that
    the set used to decide "is this conversation staff?" holds nothing but
    strings to match, so a conversation can never be attributed to a
    person by this path.
    """
    ids = load_staff_identifiers()
    assert set(ids) == {"emails", "netids"}
    for value in list(ids["emails"]) + list(ids["netids"]):
        assert isinstance(value, str)


def test_the_columns_nobody_should_ever_read_are_never_read(directory):
    """Two different jobs live in this module now, and only one of them is
    allowed to know anything about a person.

    `load_staff_roster` reads names, titles, phones and campus, because a
    PATRON asks "who is the web services librarian?" out loud and every
    one of those is already published on the Libraries staff page. It was
    added 2026-08-31; before it, a colleague's own job title was not in
    the bot's world and the answer was "Miami doesn't have one".

    What stays unread is the HR half of the same export: legal names, who
    somebody reports to, when they started, their pronouns, their degrees.
    None of that is on the staff page and none of it answers a question
    anybody asked.
    """
    import inspect

    from src.api.admin import staff_directory
    src = inspect.getsource(staff_directory)
    for column in ("legal-first-name", "legal-last-name", "Supervisor",
                   "start-date", "pronouns", "degrees",
                   "workday_department", "leadership", "ask-me-about"):
        assert f'"{column}"' not in src and f"'{column}'" not in src, \
            f"the loader reads {column}, which it has no use for"


def test_the_roster_carries_only_what_the_staff_page_shows(directory):
    from src.api.admin.staff_directory import load_staff_roster

    for person in load_staff_roster():
        assert set(person) == {"name", "title", "email", "phone", "campus",
                               "uid"}, person


def test_a_short_netid_is_not_matched_bare(directory):
    # "qum" is three characters and lives inside ordinary words. Matching it
    # would label anybody asking about quantum physics as staff.
    assert looks_like_staff("do you have books on quantum physics") is False
    assert looks_like_staff("qum") is False
    # They are still caught by their address, which is what the booking flow
    # asks for anyway.
    assert looks_like_staff("diazc@miamioh.edu") is True


def test_a_netid_inside_a_longer_word_is_not_matched(directory):
    assert looks_like_staff("chenb2x is not a netid") is False
    assert looks_like_staff("xchenb2") is False


def test_only_netids_of_the_minimum_length_are_loaded(directory):
    assert all(len(n) >= MIN_NETID_LEN
               for n in load_staff_identifiers()["netids"])


# --- it must never break a page -------------------------------------------


def test_a_missing_file_matches_nothing_and_does_not_raise(monkeypatch):
    monkeypatch.setenv("STAFF_DIRECTORY_CSV", "/nonexistent/staff.csv")
    load_staff_identifiers(refresh=True)
    assert looks_like_staff("abbotta@miamioh.edu") is False
    monkeypatch.delenv("STAFF_DIRECTORY_CSV", raising=False)
    load_staff_identifiers(refresh=True)


def test_a_malformed_file_matches_nothing_and_does_not_raise(tmp_path,
                                                             monkeypatch):
    bad = tmp_path / "bad.csv"
    bad.write_bytes(b"\xff\xfe not a csv at all \x00")
    monkeypatch.setenv("STAFF_DIRECTORY_CSV", str(bad))
    load_staff_identifiers(refresh=True)
    assert looks_like_staff("anything") is False
    monkeypatch.delenv("STAFF_DIRECTORY_CSV", raising=False)
    load_staff_identifiers(refresh=True)


@pytest.mark.parametrize("junk", ["", None])
def test_empty_input_is_not_staff(junk, directory):
    assert looks_like_staff(junk) is False


def test_the_real_file_is_not_in_the_repository():
    """132 colleagues' contact details do not belong in a git history."""
    import subprocess
    out = subprocess.run(
        ["git", "ls-files", "staff-members.csv"],
        cwd="/opt/chatbot", capture_output=True, text=True).stdout.strip()
    assert out == "", "staff-members.csv is tracked by git"
