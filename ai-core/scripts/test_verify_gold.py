"""Tests for the gold verifier.

The two that matter are both about NOISE. A checker whose output is mostly
false positives does not get read, and the first version produced forty of
them -- it joined the last word of one sentence to the first of the next
("PDF. Copyright", "ID. It"), and it flagged its own correction notes for
quoting the wrong name they exist to record.
"""
from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))
sys.path.insert(0, str(_HERE))

import verify_gold as V  # noqa: E402

ALL = {"names", "people", "phones", "urls"}


def _src(text="", people=(), emails=(), urls=(), phones=()):
    return {"blob": text.lower(), "text": [], "people": set(people),
            "emails": set(emails), "urls": set(urls), "phones": set(phones)}


def _row(answer, **kw):
    r = {"id": "t", "question": "q", "expected_answer": answer,
         "allowed_urls": [], "notes": None}
    r.update(kw)
    return r


def test_it_finds_a_library_that_does_not_exist():
    """The finding this was written for."""
    got = V.check_row(_row("The Amelia Hoover Music Library is closed."),
                      _src("the amos music library closed in 2023"), {"names"})
    assert any("Amelia Hoover" in m for _, m in got), got


def test_a_name_we_do_hold_is_not_flagged():
    got = V.check_row(_row("The Amos Music Library closed in 2023."),
                      _src("the amos music library closed in 2023"), {"names"})
    assert got == []


def test_a_sentence_boundary_is_not_a_name():
    """"...install it on your own device. Adobe also..." must not become
    the proper noun "device. Adobe"."""
    got = V.check_row(
        _row("Check out the licence and install it on your own device. "
             "Acrobat Pro comes with it. The MakerSpace can help."),
        _src("acrobat pro makerspace licence"), {"names"})
    assert got == [], got


def test_the_first_word_of_a_sentence_is_not_a_name():
    got = V.check_row(_row("Miami University Libraries lends chargers."),
                      _src("miami university libraries lends chargers"),
                      {"names"})
    assert got == []


def test_a_correction_note_may_quote_the_wrong_name():
    """The note records what went wrong; quoting it there is the point."""
    got = V.check_row(
        _row("The Amos Music Library closed in 2023.",
             notes="This row first said the Amelia Hoover Music Library."),
        _src("the amos music library closed in 2023"), {"names"})
    assert got == [], got


def test_an_email_not_in_the_roster_is_flagged():
    got = V.check_row(_row("Contact Jane Doe (doej@miamioh.edu)."),
                      _src(people=["jane doe"], emails=["real@miamioh.edu"]),
                      {"people"})
    assert any("doej@miamioh.edu" in m for _, m in got), got


def test_a_roster_email_passes():
    got = V.check_row(_row("Contact Ginny Boehme (boehmemv@miamioh.edu)."),
                      _src(people=["ginny boehme"],
                           emails=["boehmemv@miamioh.edu"]), {"people"})
    assert got == []


def test_a_url_the_crawler_has_never_fetched_is_flagged():
    got = V.check_row(_row("x", allowed_urls=["https://example.edu/nope"]),
                      _src(urls={"https://example.edu/yes"}), {"urls"})
    assert any("nope" in m for _, m in got), got


def test_a_trailing_slash_is_not_a_different_url():
    got = V.check_row(_row("x", allowed_urls=["https://example.edu/page/"]),
                      _src(urls={"https://example.edu/page"}), {"urls"})
    assert got == []


def test_the_service_desk_number_is_not_a_finding():
    """It is on every page and in every answer; flagging it is noise."""
    got = V.check_row(_row("Call the desk on (513) 529-4141."),
                      _src(), {"phones"})
    assert got == []
