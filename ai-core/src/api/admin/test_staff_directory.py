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


def test_only_identifiers_are_loaded_never_the_person_columns(directory):
    """The name columns are not read.

    An address inevitably CONTAINS a surname -- abbotta@miamioh.edu is
    derived from it, and no loader can undo that. The property worth
    asserting is the one we control: nothing but `email` and `uniqueid` is
    read, so title, phone, supervisor, start date and pronouns never enter
    the process at all.
    """
    ids = load_staff_identifiers()
    assert set(ids) == {"emails", "netids"}

    import inspect

    from src.api.admin import staff_directory
    src = inspect.getsource(staff_directory)
    for column in ("first-name", "last-name", "legal-first-name", "title",
                   "phone", "Supervisor", "start-date", "pronouns",
                   "workday_department"):
        assert f'"{column}"' not in src and f"'{column}'" not in src, \
            f"the loader reads {column}, which it has no use for"


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
