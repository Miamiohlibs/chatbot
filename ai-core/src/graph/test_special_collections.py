"""The Special Collections department's own answers.

Per the operator (2026-08-13), the colleague who runs the service supplied a
written Q&A and it takes precedence over what we held. These tests pin the
parts that are easy to get wrong later:

  * the LOCKER ambiguity, which is why this module exists at all
  * that unpublished facts are labelled as coming from staff, never cited to
    a page that does not say them
  * that "drop-ins are welcome" survives, since every previous answer said
    the opposite
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.graph.special_collections import (  # noqa: E402
    ARCHIVES_EMAIL,
    SPEC_HOME_URL,
    dropins_answer,
    hours_rider,
    learn_more_answer,
    other_collections_answer,
    reading_room_items_answer,
    sc_locker_answer,
    who_may_use_answer,
)

ALL = (other_collections_answer, who_may_use_answer, reading_room_items_answer,
       dropins_answer, sc_locker_answer, learn_more_answer)

_ORCHESTRATOR = Path(__file__).resolve().parent / "new_orchestrator.py"


def _registered_order() -> "list[str]":
    """The sc_* short-circuit names, in the order new_orchestrator runs them.

    Parsed out of the source rather than copied, because a copied list is a
    list that goes stale. The whole point of the routing test below is to
    catch an ORDERING mistake, and it cannot do that against a stale copy of
    the ordering.
    """
    import ast

    tree = ast.parse(_ORCHESTRATOR.read_text(encoding="utf-8"))
    names: "list[str]" = []
    for node in ast.walk(tree):
        # The registration table is a tuple of ("name", fn) tuples.
        if not isinstance(node, ast.Tuple) or len(node.elts) != 2:
            continue
        first, second = node.elts
        if not (isinstance(first, ast.Constant) and isinstance(first.value, str)):
            continue
        # Only the ones dispatching into this module.
        if isinstance(second, ast.Attribute) and isinstance(second.value, ast.Name):
            if second.value.id == "_spec":
                names.append(first.value)
    return names


# --- the lockers, which are the whole reason for this module ---------------


def test_sc_locker_fires_on_the_operators_question():
    res = sc_locker_answer("are there lockers in special collections")
    assert res is not None
    body, _ = res
    assert "free" in body.lower() and "secure" in body.lower()
    # It must NOT repeat the eligibility restriction as if it applied here.
    # That restriction is what made the old answer wrong for undergraduates
    # and community researchers.
    first_para = body.split("\n\n")[0]
    assert "faculty" not in first_para.lower()
    assert "graduate" not in first_para.lower()


def test_sc_locker_names_the_other_lockers_without_confusing_them():
    """Both services exist. Saying so prevents the next person re-reporting
    the King lockers as a bug."""
    body, _ = sc_locker_answer("special collections lockers")
    assert "Faculty and Graduate Reading Rooms" in body
    assert "separate" in body.lower()


def test_sc_locker_does_not_hijack_the_faculty_grad_locker_question():
    """Bare locker questions belong to the existing King answer."""
    assert sc_locker_answer("lockers") is None
    assert sc_locker_answer("are there lockers at King?") is None
    assert sc_locker_answer("how do I get a locker for the year") is None


# --- drop-ins: the correction with the most at stake ----------------------


def test_dropins_says_welcome_not_appointment_only():
    body, cites = dropins_answer(
        "do I need an appointment for special collections or can I drop in")
    assert "Drop-ins are welcome" in body
    # The old wording, which the department contradicts.
    assert "is by appointment" not in body
    assert cites and cites[0]["url"] == SPEC_HOME_URL


def test_dropins_still_encourages_booking():
    """Welcome != no reason to book. Staff retrieve materials in advance."""
    body, _ = dropins_answer("can I just show up at special collections")
    assert "encourage" in body.lower()
    assert "retrieve" in body.lower()


# --- who may use ----------------------------------------------------------


def test_who_may_use_says_everyone_and_names_the_id():
    body, _ = who_may_use_answer("who is allowed to use special collections")
    assert "open to everyone" in body.lower()
    assert "community" in body.lower()
    assert "visiting scholars" in body.lower()
    assert "photo id" in body.lower()


def test_who_may_use_covers_the_unaffiliated_phrasing():
    for q in ("can the public use special collections",
              "I'm not a student, can I visit university archives",
              "do I need an ID for special collections"):
        assert who_may_use_answer(q) is not None, q


# --- reading room items ---------------------------------------------------


def test_reading_room_items_lists_both_sides():
    body, cites = reading_room_items_answer(
        "what can I bring into the special collections reading room")
    for permitted in ("pencils", "laptops", "cameras"):
        assert permitted in body.lower()
    for banned in ("pens", "backpacks", "food", "drink"):
        assert banned in body.lower()
    # Not on any page we hold -> no citation pointing at one.
    assert cites == []


def test_reading_room_items_answers_the_pen_question_directly():
    assert reading_room_items_answer("can I use a pen in special collections") is not None
    assert reading_room_items_answer(
        "can I take photos in the special collections reading room") is not None


def test_reading_room_items_mentions_the_lockers():
    """Bags are banned, so "where does my bag go" is the immediate next
    question. Answering it in the same breath saves a turn."""
    body, _ = reading_room_items_answer("can I bring my backpack into special collections")
    assert "locker" in body.lower()


# --- other collections ----------------------------------------------------


def test_other_collections_names_all_three_archives():
    body, cites = other_collections_answer(
        "what other collections are in special collections")
    for name in ("Miami University", "Western College", "Oxford College"):
        assert name in body
    assert cites and len(cites) == 2


def test_other_collections_yields_to_digital_collections():
    """"Digital Collections" is a different service with its own answer."""
    assert other_collections_answer(
        "what is in the digital collections") is None
    assert other_collections_answer(
        "what government documents does special collections hold") is None


# --- learn more -----------------------------------------------------------


def test_learn_more_hands_over_the_url_in_the_text():
    """She asked for the URL to be given, not merely cited. A citation
    marker is not a clickable answer to "where do I read more"."""
    body, _ = learn_more_answer("where can I learn more about special collections")
    assert SPEC_HOME_URL in body


# --- provenance discipline ------------------------------------------------


def test_unpublished_answers_say_where_the_facts_came_from():
    """The three answers built on her document alone must name staff as the
    source and give a way to check. Otherwise the bot is asserting facts no
    page backs."""
    for fn, q in ((who_may_use_answer, "who can use special collections"),
                  (reading_room_items_answer,
                   "what can I bring into special collections"),
                  (sc_locker_answer, "special collections lockers")):
        body, _ = fn(q)
        assert "Special Collections staff rather than a web page" in body, fn.__name__
        assert ARCHIVES_EMAIL in body, fn.__name__


def test_no_answer_fires_on_an_unrelated_question():
    for q in ("what time does king library close",
              "who is the chemistry librarian",
              "how do I renew a book",
              "where is the makerspace"):
        for fn in ALL:
            assert fn(q) is None, f"{fn.__name__} fired on {q!r}"


# --- routing: the test that would have caught the real bug ----------------
#
# Every function-level test above passed while the DEPLOYED bot answered two
# of her nine questions with the wrong one of these answers. The bug was not
# in any single matcher: it was in the overlap between two of them plus the
# order they run in. So this walks the real order, from the real source.

_BY_NAME = {
    "sc_lockers": sc_locker_answer,
    "sc_dropins": dropins_answer,
    "sc_learn_more": learn_more_answer,
    "sc_reading_room_items": reading_room_items_answer,
    "sc_who_may_use": who_may_use_answer,
    "sc_other_collections": other_collections_answer,
}


def _route(question: str) -> "str | None":
    """Which sc_* short-circuit wins, running them in the registered order."""
    for name in _registered_order():
        fn = _BY_NAME.get(name)
        if fn is None:
            continue
        if fn(question) is not None:
            return name
    return None


def test_every_registered_sc_name_is_known_to_this_test():
    """If someone adds a short-circuit and not a routing case, say so here
    rather than letting it go unrouted and untested."""
    registered = set(_registered_order())
    assert registered, "parsed no sc_* registrations -- has the table moved?"
    assert registered <= set(_BY_NAME), (
        f"unrouted: {sorted(registered - set(_BY_NAME))}")


# (her question, the answer it must reach)
HER_QUESTIONS = [
    ("where can I learn more about special collections", "sc_learn_more"),
    ("what can I bring into the special collections reading room",
     "sc_reading_room_items"),
    ("who is allowed to use special collections", "sc_who_may_use"),
    ("do I need an appointment for special collections or can I drop in",
     "sc_dropins"),
    ("are there lockers in special collections", "sc_lockers"),
    ("what other collections are in special collections",
     "sc_other_collections"),
    # Phrasings that broke on the deployed bot, kept as named regressions.
    ("can I use a pen in special collections", "sc_reading_room_items"),
    ("can I bring my backpack into special collections",
     "sc_reading_room_items"),
    ("can I visit special collections", "sc_who_may_use"),
    ("what is the special collections website", "sc_learn_more"),
]


def test_every_sc_short_circuit_is_exempt_from_the_research_banner():
    """These are factual notices, not research help.

    `special_collections` is in _RESEARCH_DISCLAIMER_INTENTS, so without an
    explicit exemption every one of these answers gets "If this is a research
    question you should consult a librarian" pasted in front of it. Measured
    on the deployed bot 2026-08-13: "are there lockers in special collections"
    did exactly that.

    The exemption is matched by STRING, so a typo in either place silently
    does nothing -- which is the failure mode that has bitten this repo
    before (a rate limit configured, documented, unit-tested and never
    called). Deriving both sides from the source is what makes that
    impossible.
    """
    from src.graph.new_orchestrator import _DISCLAIMER_EXEMPT_REASONS

    missing = [f"{name}_short_circuit" for name in _registered_order()
               if f"{name}_short_circuit" not in _DISCLAIMER_EXEMPT_REASONS]
    assert not missing, (
        "these short-circuits will get the research banner: " + str(missing))


def test_her_questions_route_to_the_right_answer():
    wrong = []
    for question, expected in HER_QUESTIONS:
        got = _route(question)
        if got != expected:
            wrong.append(f"{question!r}: expected {expected}, got {got}")
    assert not wrong, "misrouted:\n  " + "\n  ".join(wrong)


def test_the_two_bare_can_i_phrasings_no_longer_hit_who_may_use():
    """The exact regression, named. A bare "can i" used to match the
    who-may-use matcher, which runs early."""
    assert who_may_use_answer(
        "where can I learn more about special collections") is None
    assert who_may_use_answer(
        "what can I bring into the special collections reading room") is None
    # ...while the genuine access phrasing still works.
    assert who_may_use_answer("can I use special collections") is not None


# --- hours rider ----------------------------------------------------------


def test_hours_rider_carries_the_semester_split_and_drops_appointment_only():
    r = hours_rider()
    assert "Fall and Spring" in r and "Summer and Winter" in r
    assert "8:00am-4:00pm" in r and "9:00am-4:00pm" in r
    assert "promptly at 4:00pm" in r
    assert "university holidays" in r
    # The wording the department contradicts must be gone.
    assert "access is by appointment" not in r
    assert "Drop-ins are welcome" in r
