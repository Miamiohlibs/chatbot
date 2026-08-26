"""The multi-turn suite's own contract.

These do not talk to production -- they check that the suite is testing
what it claims to, since a scenario file that drifts into single-turn
questions would quietly stop earning its runtime.
"""

from __future__ import annotations

from src.eval.multiturn.scenarios import SCENARIOS


def test_every_scenario_needs_more_than_one_turn() -> None:
    """A case that behaves identically as one turn belongs in the golden
    set, where it is cheaper to run."""
    for s in SCENARIOS:
        assert len(s.turns) >= 2, s.id


def test_every_scenario_says_what_the_final_answer_must_do() -> None:
    """`expect` is read by the judge. Without it there is nothing to grade
    against and the verdict is the judge's taste."""
    for s in SCENARIOS:
        assert len(s.expect.split()) >= 15, s.id


def test_ids_are_unique() -> None:
    ids = [s.id for s in SCENARIOS]
    assert len(ids) == len(set(ids))


def test_every_kind_is_one_we_defined() -> None:
    for s in SCENARIOS:
        assert s.kind in {"anaphora", "flow_state", "carry_over",
                          "correction"}, s.id


def test_the_scenario_that_started_this_is_in_here() -> None:
    """The operator hit it by hand on 2026-08-25: a good film-studies
    answer, then "where is the link", answered with the ILL url. The
    golden set scored 76.9% the same night and could not have seen it."""
    ids = {s.id for s in SCENARIOS}
    assert "anaphora_guide_link" in ids


def test_the_runner_marks_its_conversations_as_staff() -> None:
    """These run against the production socket and write real rows. They
    must never be countable as patron traffic."""
    from src.eval.multiturn import run

    assert run.STAFF_COOKIE == "mu_chat_origin=staff"


def test_the_runner_talks_to_the_widget_path() -> None:
    from src.eval.multiturn import run

    assert run.SOCKET_PATH == "/smartchatbot/socket.io"


def test_the_judge_is_told_not_to_fact_check() -> None:
    """Fact accuracy is the golden set's job. Grading it here would make a
    factually thin but context-correct answer look like a threading bug."""
    from src.eval.multiturn.run import JUDGE_SYSTEM

    assert "do not fact-check" in JUDGE_SYSTEM.lower()
    assert "multi-turn" in JUDGE_SYSTEM.lower()
