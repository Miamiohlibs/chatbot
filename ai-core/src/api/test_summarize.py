"""The ticket subject line handed to a librarian.

This one line is what a librarian reads before deciding what to do with a
ticket, and it lands in LibAnswers' QUESTION field, which truncates at
150 characters. Both properties are load-bearing: too long and it is cut
mid-word in their queue, wrong content and they re-read a transcript the
summary was supposed to spare them.
"""
from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent.parent))

from src.api import summarize as S  # noqa: E402


# --- subject fitting -----------------------------------------------------


def test_a_short_subject_is_left_alone():
    assert S._fit_subject("Renewing OhioLINK books") == "Renewing OhioLINK books"


def test_whitespace_is_collapsed():
    assert S._fit_subject("  two   lines\nof  text ") == "two lines of text"


def test_a_long_subject_is_cut_at_a_word_boundary():
    """LibAnswers showed "...library hours, leade" in the queue before
    this -- a subject chopped mid-word reads as a broken ticket."""
    text = ("Finding peer-reviewed articles about insomnia and academic "
            "performance for a PSY 301 literature review due next Friday, "
            "plus how to get the two that are only held at Hamilton")
    assert len(text) > S.SUBJECT_CHAR_LIMIT, "precondition: long enough to cut"
    out = S._fit_subject(text)
    assert len(out) <= S.SUBJECT_CHAR_LIMIT + 1     # +1 for the ellipsis
    assert out.endswith("…")
    assert not out[:-1].endswith(" ")
    # the last surviving word is whole
    assert text.startswith(out[:-1])
    assert text[len(out) - 1] in " " or len(out) - 1 == len(text)


def test_trailing_punctuation_is_not_left_dangling_before_the_ellipsis():
    out = S._fit_subject("word " * 40 + "trailing")
    assert "…" in out
    assert " …" not in out and ",…" not in out


def test_empty_input_does_not_crash():
    assert S._fit_subject("") == ""
    assert S._fit_subject(None) == ""


# --- what the prompt asks for -------------------------------------------
#
# The prompt is the whole behaviour of this endpoint, so its load-bearing
# instructions are pinned here. Before 2026-08-10 it asked only for "the
# user's main question(s)" and ended the user turn with "Subject:", which
# produced a summary of the LAST exchange -- students routinely open with
# something small, get it answered, then ask the thing they came for, and
# that was the part the librarian never saw.


def _prompt() -> str:
    import inspect
    return inspect.getsource(S.summarize_chat)


def test_the_prompt_demands_the_whole_conversation():
    p = _prompt()
    assert "WHOLE conversation" in p
    assert "oldest message first" in p, (
        "the transcript needs an explicit orientation, or the model "
        "anchors on whichever end it sees last"
    )


def test_the_prompt_asks_for_what_is_unresolved_not_a_table_of_contents():
    p = _prompt()
    assert "STILL NEEDS" in p
    assert "LEAVE OUT anything the bot already handled" in p


def test_the_prompt_forbids_inventing_a_problem():
    """A chat that went fine must not be dressed up as a complaint --
    librarians already fear the bot generates work for them."""
    p = _prompt()
    assert "Do NOT invent a problem" in p


def test_the_length_budget_matches_the_libanswers_field():
    assert S.SUBJECT_CHAR_LIMIT <= 145, "LibAnswers QUESTION caps at 150"
    assert "~130 characters" in _prompt()
