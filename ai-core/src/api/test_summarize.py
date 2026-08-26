"""What the ticket's AI Summary is allowed to leave out.

A real staff test on 2026-08-25 ran eleven turns -- a film studies guide,
a suicide-research topic, personal-vs-subject librarian, two course codes --
and reached the librarian as one line: "Film studies research guide link".
True, and the only thing a reader could see. The operator's word for it was
that it takes a part for the whole.

The subject line cannot be the fix on its own: LibAnswers caps it at 150
characters, and eleven turns do not fit. So the endpoint returns two things
now, and these tests are about both.
"""

from __future__ import annotations

import src.api.summarize as S


def test_the_response_carries_a_recap_as_well_as_a_subject() -> None:
    r = S.ChatSummaryResponse(summary="s", recap="- a -- b")
    assert r.summary == "s"
    assert r.recap == "- a -- b"


def test_a_missing_recap_is_not_an_error() -> None:
    """The subject is what a ticket cannot be filed without. A recap that
    failed to generate degrades to what we had before, not to nothing."""
    assert S.ChatSummaryResponse(summary="s").recap == ""


def test_the_subject_prompt_asks_for_every_unresolved_thing() -> None:
    """The eleven-turn chat had TWO unresolved threads -- the guide link and
    who their Personal Librarian is -- and naming one of them is how a
    librarian ends up solving the smaller problem."""
    import inspect

    src = inspect.getsource(S.summarize_chat)
    assert "MORE THAN ONE" in src
    assert '"; "' in src, "no separator specified for multiple items"


def test_the_recap_prompt_covers_what_went_fine_too() -> None:
    """The librarian is deciding where to start and needs to know what NOT
    to repeat, so a resolved topic still earns a line."""
    assert "WHOLE conversation" in S.RECAP_PROMPT
    assert "including the ones that went fine" in S.RECAP_PROMPT
    assert "refused" in S.RECAP_PROMPT


def test_the_recap_is_bounded() -> None:
    """It goes in a ticket body a human reads, not an archive."""
    assert "at most 6 short lines" in S.RECAP_PROMPT


def test_the_subject_still_fits_the_libanswers_field() -> None:
    """150 characters, minus the "[AI] " marker the form prepends."""
    assert S.SUBJECT_CHAR_LIMIT <= 145
    long = "Peer-reviewed articles on insomnia " * 20
    out = S._fit_subject(long)
    assert len(out) <= S.SUBJECT_CHAR_LIMIT + 1     # +1 for the ellipsis
    assert not out.rstrip("…").endswith(" ")


def test_a_short_subject_is_left_exactly_as_written() -> None:
    s = "Film studies guide link; whether a Personal Librarian is assigned"
    assert S._fit_subject(s) == s


def test_the_subject_is_never_cut_mid_word() -> None:
    out = S._fit_subject("supercalifragilistic " * 30)
    assert "supercalifragilisti…" not in out
