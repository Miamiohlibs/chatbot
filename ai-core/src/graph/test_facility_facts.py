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


# --- building facts go to the desk (operator ruling 2026-08-17) ----------
#
# THE PREMISE OF THESE TESTS CHANGED, so they are rewritten rather than
# deleted. They used to assert the OLD policy: quiet areas "second and third
# floor", reading rooms "second floor", restrooms "every floor", and "there is
# no lactation room" -- all four answered from the operator's own knowledge,
# because on 2026-08-04 the ruling was that refusing a question staff can
# answer in one sentence is the worst kind of unhelpful.
#
# On 2026-08-17 the same operator reversed it for the physical plant: if it is
# not on the website, do not answer from memory, send them to the desk. Those
# old assertions were pinning floor numbers that no page backs and that nobody
# reading the answer could check.


@pytest.mark.parametrize("q", [
    "where are the bathrooms at King Library",
    "is there a restroom",
    "where's the toilet",
    "mens room",
    "where is the silent study area",
    "is there a quiet floor",
    "which floor is quiet",
    "do you have a lactation room",
    "is there a nursing room",
    "where can I breastfeed",
    "where is the elevator",
    "is there a water fountain on the third floor",
])
def test_unsourced_building_questions_go_to_the_desk(q):
    a = _ans(F.building_facility_answer, q)
    assert a is not None, q
    assert F.KING_PHONE in a, q
    # And it must NOT assert a floor it cannot source.
    for invented in ("second and third", "every floor", "does not have"):
        assert invented not in a.lower(), f"{q!r} still guesses: {invented!r}"


def test_it_says_why_rather_than_just_refusing():
    """"I don't know" is a dead end; "it isn't on the site, the desk knows" is
    a route. The distinction is the whole reason this is not a refusal."""
    a = _ans(F.building_facility_answer, "where are the bathrooms")
    low = a.lower()
    assert "can't find that on the" in low or "cannot find that on the" in low
    assert "desk" in low


def test_reading_rooms_still_hand_over_the_page_they_do_have():
    """A navigator does not withhold a page it holds. The Reading Rooms page
    genuinely describes the rooms and who may use them -- it just does not say
    which floor, and that part goes to the desk."""
    r = F.building_facility_answer("where is the graduate reading room")
    assert r is not None
    body, cites = r
    assert cites and cites[0]["url"] == F.READING_ROOMS_URL
    assert "graduate reading room" in body.lower()
    assert "second floor" not in body.lower(), "the floor is not on that page"
    assert F.KING_PHONE in body


def test_the_nursing_librarian_carve_out_survived_the_rewrite():
    """Regression from 2026-08-12: "who is the nursing librarian" was answered
    with "King Library has no lactation room". The academic sense of the word
    must keep reaching the liaison path."""
    for q in ("who is the nursing librarian",
              "nursing databases",
              "I need help with my nursing degree"):
        assert F.building_facility_answer(q) is None, q


@pytest.mark.parametrize("q", [
    "can you be quiet about my fines",
    "how do I renew a book",
    "who is my librarian",
    "how do I print",
    "what are the hours",
])
def test_building_answer_does_not_overfire(q):
    assert F.building_facility_answer(q) is None, q


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
    retrieved from 231 characters of navigation menu.

    It used to return all four links for every question, which this test used
    to assert. The 2026-08-18 eval scored "How do I print from my laptop?" and
    "Can I print here?" `partial` for citing the Wi-Fi page and a video that
    neither question asked for, so the answer is now built from the part that
    WAS asked -- and the test asserts that rule instead of the old fixed list.
    """
    a, cites = F.printing_scanning_wifi_answer("how do I scan a document")
    urls = [c["url"] for c in cites]
    assert F.MUPRINT_GUIDE_URL in urls
    assert F.PRINTING_PAGE_URL in urls
    assert F.WIFI_SERVICE_URL not in urls, "nobody asked about Wi-Fi"
    assert "MUprint" in a
    assert "scan" in a.lower()


def test_print_answer_includes_only_the_part_that_was_asked():
    P = F.printing_scanning_wifi_answer

    def urls(q):
        r = P(q)
        assert r is not None, q
        return [c["url"] for c in r[1]]

    # Printing only.
    u = urls("How do I print from my laptop?")
    assert F.MUPRINT_GUIDE_URL in u and F.WIFI_SERVICE_URL not in u
    # ... and a how-to gets the video, a yes/no does not.
    assert F.PRINTING_VIDEO_URL in u
    u = urls("Can I print here?")
    assert F.MUPRINT_GUIDE_URL in u
    assert F.PRINTING_VIDEO_URL not in u and F.WIFI_SERVICE_URL not in u
    # Wi-Fi only.
    u = urls("how do I connect to the wifi")
    assert F.WIFI_SERVICE_URL in u and F.MUPRINT_GUIDE_URL not in u
    # Both, when both are asked about.
    u = urls("is there wifi and printing here")
    assert F.WIFI_SERVICE_URL in u and F.MUPRINT_GUIDE_URL in u
    # The Libraries' own page is always there -- it is the one page a patron
    # can navigate to, and the allowed_urls in gold are built on it.
    for q in ("How do I print from my laptop?", "Can I print here?",
              "how do I connect to the wifi"):
        assert F.PRINTING_PAGE_URL in urls(q), q


def test_room_with_a_whiteboard_is_a_booking_not_a_fixture_hunt():
    """gold rb_king_4_people_whiteboard, whose allowed url is LibCal. The desk
    referral was taking it because `whiteboard` is in the fixture list."""
    B = F.building_facility_answer
    for q in ("Need a room for 4 with a whiteboard at King.",
              "I need a study room with a whiteboard",
              "can I book a room with a whiteboard",
              "looking for a room for 6 people"):
        assert B(q) is None, q
    # The fixture sense survives: this really is a "where is it" question.
    for q in ("is there a whiteboard I can use in King",
              "where are the bathrooms at King Library",
              "where can I charge my laptop",
              "is there a lactation room at King"):
        assert B(q) is not None, q


def test_parking_answer_declines_to_sell_a_permit():
    """gold oos2_parking_pass expects a refusal: buying a permit is Parking &
    Transportation's process and none of it is on a library page. The 2026-08-18
    eval scored this answered_should_have_refused."""
    P = F.parking_answer
    for q in ("How do I buy a parking pass?",
              "where do I purchase a parking permit",
              "how much does a parking pass cost",
              "can I renew my parking permit online",
              "how do I get a parking decal"):
        assert P(q) is None, q
    # Where to park IS ours -- it is on the FAQ.
    for q in ("where can I park at King Library",
              "is there parking near the library",
              "where can I park at Rentschler",
              "do I need a permit to park on campus"):
        assert P(q) is not None, q


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
        (F.building_facility_answer, "quiet study area"),
        (F.building_facility_answer, "graduate reading room"),
        (F.building_facility_answer, "where are the bathrooms"),
        (F.building_facility_answer, "lactation room"),
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


# --- a report is not a question ---------------------------------------------


def test_a_broken_fixture_report_gets_the_desk_not_a_map():
    """Live traffic, 2026-08-17: "There is a toilet running on the second
    floor" was answered with where the restrooms ARE. The patron was not lost,
    they were doing us a favour, and got a map.

    Nobody files a work order through a chatbot, so the honest answer says so
    and hands over the desk -- what a member of staff would do.
    """
    from src.graph.facility_facts import facility_problem_answer

    body, cites = facility_problem_answer(
        "There is a toilet running on the second floor")
    low = body.lower()
    assert "(513) 529-4141" in body
    assert "can't file a repair request" in low or "cannot file" in low
    assert cites


def test_the_report_phrasings_people_use():
    from src.graph.facility_facts import facility_problem_answer

    for q in ("There is a toilet running on the second floor",
              "the sink on 3 is leaking",
              "a light is out near the elevator",
              "the printer on floor 2 is jammed",
              "an outlet is broken in the quiet area"):
        assert facility_problem_answer(q) is not None, q


def test_questions_about_fixtures_keep_their_own_answers():
    """A report STATES a condition; a question asks about one. Confusing the
    two is how this bug happened in the first place, just in reverse."""
    from src.graph.facility_facts import facility_problem_answer

    for q in ("where are the restrooms",
              "is there a water fountain on the third floor",
              "are the elevators working?",
              "how do I print",
              "can I use a computer in the library"):
        assert facility_problem_answer(q) is None, q


# --- the ORDER is the mechanism, so the order is what gets tested ------------


def _registered_single_arg_chain():
    """The short-circuit names in the order new_orchestrator runs them.

    Parsed out of the source, not copied. A copied order goes stale, and a
    stale copy cannot catch an ordering mistake -- which is the only thing
    this exists to catch. Same approach as the Special Collections routing
    test, for the same reason.
    """
    import ast
    from pathlib import Path

    src = (Path(__file__).resolve().parent / "new_orchestrator.py").read_text(
        encoding="utf-8")
    tree = ast.parse(src)
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Tuple) or len(node.elts) != 2:
            continue
        first, second = node.elts
        if not (isinstance(first, ast.Constant)
                and isinstance(first.value, str)):
            continue
        if isinstance(second, ast.Attribute) and isinstance(second.value, ast.Name):
            if second.value.id in ("_ff", "_spec"):
                out.append((first.value, second.value.id, second.attr))
        elif isinstance(second, ast.Name):
            out.append((first.value, None, second.id))
    return out


def test_the_infrastructure_fallback_runs_after_every_page_backed_answer():
    """Operator rule, restated 2026-08-18: on the site, answer from the site;
    NOT on the site, send them to the desk.

    Position is how that is implemented. `building_facility` has a deliberately
    broad matcher -- doors, heat, lighting, outlets, bins -- and that is only
    safe because every page-backed answer runs BEFORE it. It originally sat
    third in the group, ahead of computers and printing, and would have stolen
    them once broadened.
    """
    order = [name for name, _, _ in _registered_single_arg_chain()]
    assert "building_facility" in order, "the fallback is not registered"
    i = order.index("building_facility")
    for page_backed in ("computer_help", "printing_cost", "print_scan_wifi",
                        "sc_lockers", "sc_reading_room_items"):
        assert page_backed in order, page_backed
        assert order.index(page_backed) < i, (
            f"{page_backed} runs AFTER the infrastructure fallback, so the "
            f"fallback will steal its questions")
    # ...and it must not be last either: finding_help is broader still.
    assert order.index("finding_help") > i


def test_page_backed_questions_survive_the_broadened_matcher():
    """Walk the real chain. Individually-correct matchers that overlap are
    exactly how a working answer gets stolen."""
    import src.graph.facility_facts as _ff_mod
    import src.graph.new_orchestrator as _orch
    import src.graph.special_collections as _spec_mod

    mods = {"_ff": _ff_mod, "_spec": _spec_mod}

    def route(q):
        for name, mod, attr in _registered_single_arg_chain():
            fn = getattr(mods[mod], attr) if mod else getattr(_orch, attr, None)
            if fn is None or not callable(fn):
                continue
            try:
                if fn(q) is not None:
                    return name
            except TypeError:
                continue          # needs deps/scope, not part of this chain
        return None

    expected = {
        "how do I print": "print_scan_wifi",
        "Is there free printing?": "printing_cost",
        "who can help with my computer": "computer_help",
        "are there lockers in special collections": "sc_lockers",
        "where are the bathrooms": "building_facility",
        "where is the elevator": "building_facility",
        "is there a lactation room": "building_facility",
        "where is the silent study area": "building_facility",
        "the toilet on the second floor is running": "facility_problem",
    }
    wrong = []
    for q, want in expected.items():
        got = route(q)
        if got != want:
            wrong.append(f"{q!r}: expected {want}, got {got}")
    assert not wrong, "misrouted:\n  " + "\n  ".join(wrong)


# --- parking / temporary / game night (operator ruling 2026-08-18) -----------


def test_parking_is_answered_because_it_is_documented():
    """The operator listed parking among the things to defer to the desk. It
    is one of the better-documented topics we have -- libanswers 176243 plus
    the campus pages -- so deferring it would withhold pages we hold, which is
    the mistake they themselves ruled out with the reading-room example.
    """
    body, cites = F.parking_answer("where can I park")
    low = body.lower()
    assert "permit" in low
    assert "garage" in low and "meter" in low
    assert cites and "176243" in cites[0]["url"]


def test_parking_names_the_hamilton_lot_when_hamilton_is_named():
    body, cites = F.parking_answer("is there parking at Rentschler")
    assert "free visitor parking" in body.lower()
    assert cites[0]["url"] == F.HAMILTON_ABOUT_URL


def test_parking_defers_only_the_live_state():
    """What is on no page is whether a garage is FULL right now. The answer
    says so and hands that part to the desk."""
    body, _ = F.parking_answer("where can I park")
    assert F.KING_PHONE in body
    assert "full" in body.lower()


def test_temporary_and_current_state_go_to_the_desk():
    """A crawl is a snapshot. This content changes, so it is deferred by
    definition rather than because it happens to be missing."""
    for q in ("is the elevator out of service",
              "is there construction in the library",
              "why is the third floor closed",
              "is anything different over winter break?"):
        r = F.temporary_notice_answer(q)
        assert r is not None, q
        assert F.KING_PHONE in r[0], q


def test_hours_are_the_explicit_carve_out_and_never_deferred():
    """The operator named hours as the exception: they come live from LibCal,
    holiday and break hours included, and must keep that path."""
    for q in ("what are the hours",
              "what time does the library close on Thanksgiving",
              "are you open over spring break",
              "when does King open tomorrow",
              "are you closed on Christmas"):
        assert F.temporary_notice_answer(q) is None, q


def test_game_night_gives_the_durable_half_and_navigates_to_the_dates():
    """The one event the operator handed over. The page's indexed text carries
    what it IS and who it is for, but not the schedule -- which is exactly the
    date-bearing content the navigator rule says to link rather than repeat."""
    body, cites = F.games_night_answer("when is library game night")
    low = body.lower()
    assert "meeples" in low
    assert "welcome" in low
    assert F.GAMES_NIGHT_EMAIL in body
    assert "check the page" in low, "the schedule must be navigated to"
    assert cites[0]["url"] == F.GAMES_NIGHT_URL
    # It must not invent a day or time.
    import re as _re
    assert not _re.search(r"\b(monday|tuesday|wednesday|thursday|friday|"
                          r"saturday|sunday|\d{1,2}\s*(am|pm))\b", low), \
        "invented a schedule"


def test_printing_pointer_yields_when_scan_is_not_about_our_scanner():
    """Two real asks on 2026-08-17 got the MUprint guide because the word
    "scan" appeared in them at all -- one was an interlibrary loan question,
    the other was about OCR software."""
    from src.graph.facility_facts import printing_scanning_wifi_answer as P

    for q in ("I need to access O Globo's digital archive to find an image. "
              "Can I use interlibrary loan if I only need a photo or a scan "
              "of an image from a 2001 issue?",
              "I am trying to find an OCR software capable of scanning and "
              "translating Japanese. Do we have access to ABBYY?",
              "does the university have a subscription to a scanning service"):
        assert P(q) is None, q
    # The real thing still works.
    for q in ("how do I print at the library",
              "where can I scan a document",
              "how do I connect to the wifi"):
        assert P(q) is not None, q
