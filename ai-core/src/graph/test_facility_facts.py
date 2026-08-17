"""Operator-provided building facts: do they fire, and do they NOT overfire?

These short-circuit ahead of the agent, so a false positive replaces a good
retrieved answer with a canned one. The negative cases matter more than the
positive ones.
"""
from __future__ import annotations

import pytest

from src.graph import facility_facts as F


def _ans(fn, q):
    r = fn(q)
    return r[0] if r else None


# --- quiet study: 2nd AND 3rd floor -------------------------------------


@pytest.mark.parametrize("q", [
    "where is the silent study area",
    "Where is the silent study area?",
    "is there a quiet floor",
    "quiet study space?",
    "where can i study quietly",
    "do you have silent areas",
    "which floor is quiet",
])
def test_quiet_fires_on_how_students_ask(q):
    a = _ans(F.quiet_study_answer, q)
    assert a is not None, q
    assert "second and third" in a.lower()


def test_quiet_answer_names_both_floors_not_just_one():
    """The gold said THIRD floor only; the operator says second AND third."""
    a = _ans(F.quiet_study_answer, "where is the silent study area")
    assert "second" in a.lower() and "third" in a.lower()


def test_quiet_answer_says_where_the_fact_came_from():
    """It is not on any page, so the answer must not imply a page said it."""
    a = _ans(F.quiet_study_answer, "quiet study area")
    assert "library staff" in a.lower()
    assert F.KING_PHONE in a


@pytest.mark.parametrize("q", [
    "can you be quiet about my fines",          # 'quiet' but not a space question
    "how do I renew a book",
    "who is my librarian",
])
def test_quiet_does_not_overfire(q):
    assert F.quiet_study_answer(q) is None, q


# --- reading rooms: both on the 2nd floor -------------------------------


@pytest.mark.parametrize("q", [
    "where is the graduate reading room",
    "is there a faculty reading room",
    "grad reading room location",
    "staff reading room",
])
def test_reading_room_fires(q):
    a = _ans(F.reading_room_answer, q)
    assert a is not None, q
    assert "second floor" in a.lower()


def test_reading_room_tells_undergrads_where_to_go_instead():
    """The rooms are restricted, so a bare "you can't" is a dead end."""
    a = _ans(F.reading_room_answer, "can I use the graduate reading room")
    assert "undergraduate" in a.lower()
    assert "quiet study" in a.lower()


def test_reading_room_cites_the_page_that_really_is_titled_that():
    r = F.reading_room_answer("graduate reading room")
    assert r[1][0]["url"] == F.READING_ROOMS_URL


# --- restrooms: every floor ---------------------------------------------


@pytest.mark.parametrize("q", [
    "where are the bathrooms at King Library",
    "is there a restroom",
    "where's the toilet",
    "mens room",
])
def test_restroom_fires(q):
    a = _ans(F.restroom_answer, q)
    assert a is not None, q
    assert "every floor" in a.lower()


def test_restroom_answer_carries_no_citation():
    """No page states this, so no page gets cited for it."""
    assert F.restroom_answer("where are the bathrooms")[1] == []


def test_restroom_offers_a_route_for_accessible_or_all_gender():
    a = _ans(F.restroom_answer, "where are the bathrooms")
    assert "accessible" in a.lower()


# --- nursing room: there isn't one --------------------------------------


@pytest.mark.parametrize("q", [
    "do you have a lactation room",
    "is there a nursing room",
    "where can I breastfeed",
    "is there a mothers room",
])
def test_nursing_fires(q):
    assert F.nursing_room_answer(q) is not None, q


def test_nursing_answer_is_an_honest_no_with_a_route():
    """A parent needs to know BEFORE they travel."""
    a = _ans(F.nursing_room_answer, "is there a nursing room")
    assert "does **not** have" in a or "does not have" in a
    assert F.KING_PHONE in a
    assert "elsewhere on campus" in a.lower()


# --- printing / scanning / wifi -----------------------------------------


@pytest.mark.parametrize("q", [
    "how do I print",
    "can I scan a document",
    "where is the scanner",
    "how do I connect to wifi",
    "what's the wireless network",
    "scan to email",
])
def test_print_scan_wifi_fires(q):
    a = _ans(F.printing_scanning_wifi_answer, q)
    assert a is not None, q


def test_print_answer_gives_the_actual_guides_not_a_shrug():
    """The old answer was "King Library offers printing/scanning services",
    retrieved from 231 characters of navigation menu."""
    r = F.printing_scanning_wifi_answer("how do I scan a document")
    a, cites = r
    urls = [c["url"] for c in cites]
    assert F.MUPRINT_GUIDE_URL in urls
    assert F.WIFI_SERVICE_URL in urls
    assert F.PRINTING_VIDEO_URL in urls
    assert "MUprint" in a
    assert "scan" in a.lower()


def test_all_cited_urls_are_the_verified_canonical_forms():
    """Recorded post-redirect on 2026-08-04; a stale ArticleDet?ID= form would
    still work but would not match what we checked."""
    _a, cites = F.printing_scanning_wifi_answer("how do I print")
    for c in cites:
        assert c["url"].startswith("https://")
        assert "ArticleDet?ID=" not in c["url"], "use the canonical redirect target"
        assert c["snippet"].strip()


@pytest.mark.parametrize("q", [
    "does the makerspace have a 3d printer",
    "how much does printing cost",
    "what are the fines for printing",
    "how do I get a reprint permission",
    "3D printing services",
    # Added after the 2026-08-04 eval: this generic pointer replaced four
    # GOOD specific answers. It cannot confirm a capability it does not
    # state, and it cannot speak for one named building.
    "can I print in color",
    "does Wertz have printing",
    "is there scanning at all three campuses",
    "can I print black and white at Rentschler",
    "which library has a poster printer",
    "compare printing at Hamilton and Middletown",
])
def test_print_does_not_hijack_the_specific_cases(q):
    """3D printing, cost and reprints each have their own handler; this
    matcher is the broadest in the table and must yield to them.

    It must also decline anything it cannot actually answer. The generic
    MUprint pointer says nothing about colour, nothing about a specific
    building, and nothing per-campus -- so on those questions it was
    replacing a correct specific answer with a vaguer one."""
    assert F.printing_scanning_wifi_answer(q) is None, q


# --- shared -------------------------------------------------------------


def test_every_answer_is_nonempty_and_every_citation_is_numbered():
    cases = [
        (F.quiet_study_answer, "quiet study area"),
        (F.reading_room_answer, "graduate reading room"),
        (F.restroom_answer, "where are the bathrooms"),
        (F.nursing_room_answer, "lactation room"),
        (F.printing_scanning_wifi_answer, "how do I print"),
    ]
    for fn, q in cases:
        answer, cites = fn(q)
        assert answer.strip()
        for i, c in enumerate(cites, 1):
            assert c["n"] == i
            assert c["url"] and c["snippet"]
        # Every [n] marker in the text must have a matching citation.
        import re
        markers = {int(x) for x in re.findall(r"\[(\d+)\]", answer)}
        assert markers <= {c["n"] for c in cites}, (q, markers)


@pytest.mark.parametrize("q", [
    "Do all the libraries have scanners?",
    "does every library have a printer",
    "Where is the printing policy?",
    "what is the printing policy",
])
def test_print_yields_on_per_library_and_policy_questions(q):
    """Two more the generic pointer cannot serve, both caught by the
    2026-08-05 verification run:

      * "Do all the libraries have scanners?" needs a per-campus answer.
      * "Where is the printing policy?" wants ONE approved page, and the
        gold checks that only that page is cited -- a four-link answer
        fails by construction.
    """
    assert F.printing_scanning_wifi_answer(q) is None, q


# --- Kevin Messner's 1/5: "Who can help with my computer?" -----------------


def test_computer_help_does_not_reach_a_subject_librarian():
    """His worst-rated answer, 2026-08-13.

    The bot replied "Your subject librarian is Roger Justus at Oxford
    (justusra@miamioh.edu ...)". Traced the same day: our own alias table
    returns None for a bare "computer" -- the agent called lookup_librarian
    with it anyway and the LIVE LibGuides API fuzzy-matched it to "Computer
    Science and Software Engineering". The roster was right; the question was
    never understood.

    This answers before the agent, so no lookup happens.
    """
    from src.graph.facility_facts import computer_help_answer

    res = computer_help_answer("Who can help with my computer?")
    assert res is not None
    body, cites = res
    low = body.lower()
    # No person, no personal email.
    assert "@miamioh.edu" not in body
    assert "justus" not in low
    assert "subject librarian" in low, "it should say WHY no librarian is named"
    # Both real routes, and nothing invented.
    assert "information desk" in low
    assert "miami university it" in low
    assert cites and cites[0]["url"].endswith("/computer-labs/")


def test_computer_help_covers_the_device_and_login_shapes():
    from src.graph.facility_facts import computer_help_answer

    for q in ("who can help with my laptop",
              "my password isn't working",
              "I can't log in",
              "my computer is broken",
              "who can help me with my miami account"):
        assert computer_help_answer(q) is not None, q


def test_computer_help_never_steals_a_real_subject_question():
    """The whole risk of this fix is over-firing. Computer Science IS a
    subject with a real liaison, and these must reach him."""
    from src.graph.facility_facts import computer_help_answer

    for q in ("who is the computer science librarian",
              "who is the liaison for software engineering",
              "I need databases for CSE 174",
              "who is the electrical and computer engineering librarian",
              # things with their own better answers
              "how do I print from my laptop",
              "how do I connect my laptop to the wifi",
              "can I check out a laptop"):
        assert computer_help_answer(q) is None, q


def test_disclosing_an_account_name_is_not_an_it_help_request():
    """A regression I introduced and caught by re-running Kevin's own list.

    "My account is messnekr" is a patron DISCLOSING their username -- his
    literal test input. The first version of the matcher needed only the noun,
    so "my account" fired the IT-desk answer and displaced the correct one
    ("I don't have access to your library account, check it at ... or call
    ...").

    A device noun alone is a statement; a device noun PLUS trouble is a
    request. Both are required now.
    """
    from src.graph.facility_facts import computer_help_answer

    for q in ("My account is messnekr",
              "my account is jsmith",
              "what is on my account",
              "my email is burkejj@miamioh.edu",
              "my library account balance"):
        assert computer_help_answer(q) is None, q


def test_the_trouble_shapes_still_reach_it():
    """The fix must not have bought precision with coverage."""
    from src.graph.facility_facts import computer_help_answer

    for q in ("Who can help with my computer?",
              "my password isn't working",
              "I can't log in",
              "I forgot my password",
              "my laptop won't connect",
              "my computer is broken",
              "who can help me with my miami account"):
        assert computer_help_answer(q) is not None, q


# --- "Is there free printing?" -- a real student, first week of beta --------


def test_free_printing_gets_a_price_not_a_how_to_guide():
    """A real student asked this on 2026-08-15 and got the MUprint and Wi-Fi
    guides -- how to print, when they asked what it costs.

    _NOT_PRINTING_RE already excluded cost questions (cost, price, how much,
    charge, fines); it just did not list the words people actually use.
    "Free" and "pay" were missing, so these fell through to the generic
    pointer.

    We know the answer exactly (FAQ 163327), so the fix is to give it. "Is it
    free?" deserves yes or no, not a link.
    """
    from src.graph.facility_facts import printing_cost_answer

    body, cites = printing_cost_answer("Is there free printing?")
    low = body.lower()
    assert "not free" in low, "answer the question that was asked"
    assert "$0.10" in body and "$0.25" in body
    assert "mulaa" in low, "say how they pay, or the price is not actionable"
    assert cites and "163327" in cites[0]["url"]


def test_the_cost_phrasings_people_actually_use():
    from src.graph.facility_facts import printing_cost_answer

    for q in ("Is there free printing?", "is printing free",
              "do I have to pay to print", "how much does printing cost",
              "printing charges", "how much is color printing",
              "what does it cost per page to print"):
        assert printing_cost_answer(q) is not None, q


def test_cost_answer_does_not_take_the_how_to_questions():
    """The step-by-step guides are still the right answer for those."""
    from src.graph.facility_facts import printing_cost_answer

    for q in ("how do I print", "how do I connect to wifi",
              "where can I scan something",
              "how much does 3d printing cost"):
        assert printing_cost_answer(q) is None, q


def test_a_scanning_only_cost_question_is_not_given_printing_prices():
    """The FAQ prices PRINTING. We hold no scanning price, and quoting the
    printing figure would be a new wrong answer in place of a vague one."""
    from src.graph.facility_facts import printing_cost_answer

    assert printing_cost_answer("is scanning free") is None
    assert printing_cost_answer("how much does it cost to scan") is None


def test_every_answer_in_this_module_is_actually_registered():
    """The bug that keeps happening, caught for the whole module at once.

    `printing_cost_answer` was written, given four passing tests, and never
    registered in new_orchestrator -- so it was dead code and the live bot
    kept answering "is there free printing?" with the how-to guide. Found by
    asking the deployed bot, not by any test, because every test called the
    function directly.

    That is the FIFTH time this shape has bitten this project (a rate limit
    keyed on the wrong thing, an unused turn cap, an exemption list that went
    stale, a backup cron missing a `cd`, and now this). So this asserts the
    RULE rather than the instance: every public `*_answer` this module
    exports must appear in new_orchestrator.py. A new one is covered the day
    it is written, with nothing to remember.
    """
    from pathlib import Path

    from src.graph import facility_facts as ff

    orch = (Path(__file__).resolve().parent / "new_orchestrator.py").read_text(
        encoding="utf-8")
    exported = [
        n for n in dir(ff)
        if n.endswith("_answer") and callable(getattr(ff, n))
        and not n.startswith("_")
    ]
    assert exported, "found no answer functions -- has the naming changed?"
    unwired = [n for n in exported if f"_ff.{n}" not in orch]
    assert not unwired, (
        f"defined but never registered, so they are dead code: {unwired}")
