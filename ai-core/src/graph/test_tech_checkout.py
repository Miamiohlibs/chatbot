"""Equipment questions answered from the tech-checkout page's own list.

The interesting cases are the NEGATIVE ones. This handler sits in the
short-circuit table ahead of the agent, so a false positive replaces a good
retrieved answer with a canned one -- which is exactly how the printing
pointer lost four correct answers on 2026-08-04 before it was narrowed twice.

The positive cases exist because the opposite failure was also real: on the
2026-08-05 gold run both `tech_charger` and `tech2_calculator_borrow` refused
while the answer sat in the retrieved evidence, unread, inside a nested
bullet list.
"""
from __future__ import annotations

import pytest

from src.graph import tech_checkout as T

# The live chunk, verbatim from Chunk_vv20260804_1110 on 2026-08-05. Pinned as
# a fixture rather than fetched: the parser's contract is with THIS markup, and
# a test that reads the live index would go green or red for reasons that have
# nothing to do with the parser.
PAGE = """Equipment to Checkout and Go
The libraries offer a wide range of technology you can checkout to support your coursework (and your enjoyment). Come to a library checkout desk with your university ID to borrow equipment. Log into computers/iPads while on-campus with your ID/password and you will be ready to go!
- Call or stop by to check availability
Sometimes items become overdue or broken, so availability can be unpredictable. Feel free to call in advance to check on availability or ask details about our equipment at (513) 529-4141. Loan Periods and Late Fees
- Chromebook laptops may be checked out for 30 days.
- Tablets, Cameras, and camcorders are 24 hour checkouts.
- Damaged or Loss charges are up to $2,000 for laptops and tablets and $495 for cameras/audio-visual equipment. Available Equipment
- Laptops & Tablets

  - Chromebook
  - iPad Pros and Apple Pencils â€“ available at Art & Architecture Library
- Audio equipment (available at King Library)

  - Digital Audio Recorders
  - Microphones (assorted portable and desktop)
  - Headphones
  - Portable microphone/speaker sets.
- Photography

  - Digital Cameras (assorted)
  - Camera Tripods
- Video

  - DVD Players
  - Projectors
- Calculators

  - Financial
  - Graphing
  - Scientific
- Chinese-English translators
- Cables and peripherals

  - External Disc Drive
  - Card Readers
  - Network cables
  - Adaptors
  - Mouses
  - Chargers (Mac, PC, assorted phones)"""


def _ans(q, page=PAGE):
    r = T.tech_checkout_answer(q, page)
    return r[0] if r else None


# --- the parser ---------------------------------------------------------


def test_parses_seven_categories_and_nineteen_items():
    cats = T.parse_equipment(PAGE)
    assert len(cats) == 7
    assert sum(len(v) for v in cats.values()) == 19


def test_parser_ignores_the_bullets_that_are_prose_not_inventory():
    """The bullets BEFORE "Available Equipment" are loan periods and advice.
    Reading them as equipment would have the bot claim the library lends
    "Call or stop by to check availability"."""
    cats = T.parse_equipment(PAGE)
    joined = " ".join(cats.keys()).lower()
    assert "call or stop by" not in joined
    assert "may be checked out for 30 days" not in joined
    assert "damaged or loss" not in joined


def test_unparseable_page_disables_the_handler_rather_than_guessing():
    assert T.parse_equipment("") == {}
    assert T.parse_equipment("no list here at all") == {}
    assert T.tech_checkout_answer("do you lend chargers", "no list here") is None


# --- the two cases that refused in production --------------------------


def test_charger_no_longer_refuses():
    a = _ans("do you lend chargers")
    assert a is not None
    assert "Chargers" in a


def test_graphing_calculator_no_longer_refuses():
    """gold tech2_calculator_borrow. The page says `Calculators` / `Graphing`,
    two nested list items, and the synthesizer would not commit to it."""
    a = _ans("Does the library lend graphing calculators?")
    assert a is not None
    assert "Graphing calculators" in a


# --- how students actually type ----------------------------------------


@pytest.mark.parametrize("q", [
    "do you lend chargers",
    "do you have chargers",
    "can I borrow a phone charger",
    "got a laptop charger i can borrow",
    "any cables i can check out",
    "do you have calculators",
    "can i check out a scientific calculator",
    "do you lend laptops",
    "do you lend chromebooks",
    "can i borrow an ipad",
    "can i borrow an apple pencil",
    "do you have tripods",
    "can I check out a projector",
    "do you have microphones i can borrow",
    "do you lend headphones",
    "do you have dvd players",
    "can i check out an audio recorder",
    "do you lend network cables",
])
def test_fires_on_real_phrasings(q):
    assert _ans(q) is not None, q


# --- what it must NOT touch --------------------------------------------


@pytest.mark.parametrize("q", [
    # loan periods, fees and damages are on the page but are not inventory,
    # and each has its own handler or gold expectation
    "how long can i keep a laptop",
    "what's the late fee for a camera",
    "how much if i lose the ipad",
    "what's the loan period for calculators",
    "can i renew the laptop",
    "what is the tech checkout policy",
    "can i reserve a camera in advance",
    # counts are not on the page at all
    "how many laptops do you have",
    # not a borrowing question despite naming an item
    "where do i plug in my charger",
    # other domains entirely
    "how do I connect to wifi",
    "do you have study rooms",
    "where is the makerspace",
    # equipment the page does not list -- must fall through to the agent
    # rather than assert a "no" this handler cannot support
    "do you lend gopros",
    "can i borrow an umbrella",
    "do you have a 3d printer",
    # Named interfaces the page never mentions. A generic "Adaptors" or
    # "Network cables" entry must not stand in for them -- that is how
    # tech2_hdmi_cable became a WRONG answer on 2026-08-05.
    "do you have hdmi adapters",
    "can i borrow an hdmi cable",
    "do you have a usb-c dongle",
    "got an aux cord i can borrow",
])
def test_does_not_overfire(q):
    assert T.tech_checkout_answer(q, PAGE) is None, q


# --- answer hygiene -----------------------------------------------------


def test_answer_repairs_the_pages_mis_encoded_dash():
    """The chunk carries a UTF-8 em dash read as Latin-1. Echoing it verbatim
    makes the bot look broken."""
    a = _ans("can i borrow an apple pencil")
    assert "â" not in a
    assert "Apple Pencils" in a


def test_every_citation_is_numbered_and_matches_a_marker():
    import re
    answer, cites = T.tech_checkout_answer("do you lend chargers", PAGE)
    assert cites
    for i, c in enumerate(cites, 1):
        assert c["n"] == i
        assert c["url"] and c["snippet"]
    markers = {int(x) for x in re.findall(r"\[(\d+)\]", answer)}
    assert markers <= {c["n"] for c in cites}


def test_answer_cites_only_the_tech_checkout_page():
    _a, cites = T.tech_checkout_answer("do you have calculators", PAGE)
    assert [c["url"] for c in cites] == [T.TECH_CHECKOUT_URL]


def test_answer_tells_the_student_to_ring_ahead():
    """Availability is explicitly unpredictable on the page; an answer that
    promises a charger is on the shelf would be over-claiming."""
    a = _ans("do you lend chargers")
    assert T.KING_PHONE in a
    assert "ID" in a


def test_the_answer_follows_the_page_not_a_hardcoded_list():
    """The inventory must be read from the page every time.

    Asserted behaviourally rather than by grepping the source: rename an item
    on the page and the answer must rename with it. A hardcoded list would keep
    citing the old wording, which is how a bot ends up confidently naming
    equipment the library retired two years ago.
    """
    # Reword an item the synonym table DOES cover. The synonym ("charger")
    # still matches, so the handler still fires -- but the wording it quotes
    # has to be the page's new wording, not the old string.
    reworded = PAGE.replace("Chargers (Mac, PC, assorted phones)",
                            "Power bricks and chargers (all types)")
    a = _ans("do you lend chargers", reworded)
    assert a is not None
    assert "Power bricks and chargers (all types)" in a
    assert "Mac, PC, assorted phones" not in a

    # And an item whose wording no longer mentions what was asked stops
    # being offered under the old name.
    dropped = PAGE.replace("Camera Tripods", "Lighting kits")
    a2 = _ans("do you have tripods", dropped)
    assert a2 is None or "Camera Tripods" not in a2


def test_an_item_removed_from_the_page_stops_being_offered():
    """The other direction: drop chargers from the page and the charger
    question must fall through to the agent, not keep answering yes."""
    without = PAGE.replace("  - Chargers (Mac, PC, assorted phones)", "")
    assert T.tech_checkout_answer("do you lend chargers", without) is None


# --- the cheap pre-filter used by step 3.60 -----------------------------


@pytest.mark.parametrize("q", [
    "do you lend chargers",
    "can I borrow a phone charger",
    "Does the library lend graphing calculators?",
])
def test_prefilter_lets_equipment_questions_through(q):
    assert T.looks_like_equipment_question(q) is True, q


@pytest.mark.parametrize("q", [
    "what are your hours",
    "how long can i keep a laptop",
    "what's the late fee for a camera",
    "who is my subject librarian",
    "where is the makerspace",
])
def test_prefilter_skips_the_fetch_for_everything_else(q):
    assert T.looks_like_equipment_question(q) is False, q


def test_prefilter_agrees_with_the_real_decision_on_negatives():
    """If the pre-filter says no, the full path must also say no -- otherwise
    the orchestrator would skip a fetch that would have produced an answer."""
    for q in ("what are your hours", "how long can i keep a laptop",
              "who is my subject librarian", "what is the tech checkout policy"):
        assert not T.looks_like_equipment_question(q)
        assert T.tech_checkout_answer(q, PAGE) is None


# --- the two defects the 2026-08-05 service run exposed ------------------


def test_a_specific_connector_is_not_satisfied_by_a_generic_adaptor():
    """gold tech2_hdhi_cable went partial -> WRONG.

    The page lists "Adaptors" with no connector types. Answering "Yes --
    includes Adaptors" to "can I borrow an HDMI cable?" asserts something the
    page does not support. A specific item must not be satisfied by a generic
    list entry; that question belongs to the agent, which can hedge.
    """
    assert T.tech_checkout_answer("Can I borrow an HDMI cable from the library?", PAGE) is None
    assert T.tech_checkout_answer("do you have a vga adapter", PAGE) is None
    assert T.tech_checkout_answer("got a usb-c dongle", PAGE) is None


def test_a_generic_adaptor_question_still_works():
    """The page does say "Adaptors", so the generic ask is grounded."""
    a = _ans("do you lend adaptors")
    assert a is not None and "Adaptors" in a


def test_loan_period_is_carried_when_the_page_states_one():
    """gold tech_borrow_laptop wants "Chromebooks, 30 days". The page says it,
    in the prose above the equipment list, and the first version of this
    module dropped it -- turning a passing case into a partial."""
    a = _ans("Can I borrow a laptop?")
    assert a is not None
    assert "30 days" in a


def test_loan_periods_parse_but_are_not_treated_as_equipment():
    periods = T.parse_loan_periods(PAGE)
    assert any("30 days" in p for p in periods)
    assert any("24 hour" in p for p in periods)
    assert "Chromebook laptops may be checked out for 30 days." not in T.parse_equipment(PAGE)


def test_no_loan_period_is_invented_for_an_item_that_has_none():
    """Calculators have no stated period. The answer must not borrow the
    laptop's 30 days."""
    a = _ans("do you have calculators")
    assert a is not None
    assert "30 days" not in a and "24 hour" not in a


def test_charging_the_gerund_is_not_a_charger():
    """A librarian's real question, 2026-08-17:

        "Since Inside Higher Ed has started CHARGING, will we also get an
         online subscription to that for the university?"

    answered "Yes -- the libraries' equipment checkout list includes Chargers
    (Mac, PC, assorted phones)". Three things had to line up: _BORROW_RE
    contains a bare `has`, so "has started" opened the gate; the charger
    synonym allowed `charg(er|ers|ing)` with the trailing noun OPTIONAL, so
    bare "charging" resolved to the page's Chargers entry; and this
    short-circuit runs at step 3.60, ahead of the agent and ungated by intent.

    The classifier was not the problem and is worth recording, because that
    was the first hypothesis and it was wrong: the question scores `newspapers`
    at 0.6444, nearest exemplar "Do employees get free online access to the
    Chronicle for Higher Education?", and tech_checkout is not in the top five.

    "charger" is a noun and stands alone. "charging" is a gerund and needs its
    object.
    """
    import re
    from src.graph.tech_checkout import _SYNONYMS

    pat = next(p for p, canon in _SYNONYMS if canon == "charger")

    for q in ("do you lend chargers",
              "can I borrow a phone charger",
              "got a laptop charger i can borrow",
              "do u have chargers for macbooks",
              "Does the library have dell chargers for rent/sale?",
              # The gerund WITH its object is still the thing itself.
              "do you have a charging cable",
              "any charging cords available",
              "where can I get a charging brick",
              "do you lend power adapters"):
        assert re.search(pat, q, re.IGNORECASE), q

    for q in ("Since Inside Higher Ed has started charging, will we also get "
              "an online subscription to that for the university?",
              "are study rooms a charge to your Miami ID",
              "is the library charging for printing now",
              "do you have a charging policy"):
        assert not re.search(pat, q, re.IGNORECASE), q


# --- a device the page never names is not a "yes" ------------------------
#
# Production, 2026-08-27 03:02: "Do you have iPhone chargers I can borrow?"
# -> "Yes — the libraries' equipment checkout list includes **Chargers (Mac,
# PC, assorted phones)**". The page has no "iPhone" in it and promises
# nothing about one; "assorted phones" is a category, and the student walks
# over believing a cable that fits theirs is waiting.
#
# Synthesizer rule 16 forbids exactly this and could not reach it: this path
# answers deterministically and never calls the model. The rule was measured
# 3/3 overclaiming before and 0/5 after -- on the SYNTHESIZER. The
# measurement never touched the path production actually used for this
# question, which is the same verification gap that hid the cross-campus
# classifier misroute earlier the same day.

class TestDeviceNamesThePageNeverMentions:
    @pytest.mark.parametrize("q", [
        "Do you have iPhone chargers I can borrow?",
        "can I borrow a Samsung charger",
        "do you lend iPad chargers",
        "can I check out an Android cable",
    ])
    def test_it_hands_the_turn_back_instead_of_answering(self, q):
        from src.graph.tech_checkout import tech_checkout_answer

        assert tech_checkout_answer(q, PAGE) is None, (
            "answering from the category promises a fit the page does not"
        )

    @pytest.mark.parametrize("q", [
        "do you lend Chromebooks",
        "can I borrow an iPad",
    ])
    def test_a_device_the_matched_entry_does_name_still_answers(self, q):
        """The guard fires on absence FROM THE MATCHED ENTRY, not on the
        word. Losing these would trade one overclaim for a refusal on
        something the page really does list."""
        from src.graph.tech_checkout import tech_checkout_answer

        out = tech_checkout_answer(q, PAGE)
        assert out is not None and out[0]

    @pytest.mark.parametrize("q", [
        "do you have chargers",
        "do you lend graphing calculators",
        "can I borrow a mouse",
    ])
    def test_an_unqualified_question_is_untouched(self, q):
        """Nobody asked about a specific device, so there is no gap to
        name and the direct answer is the right one."""
        from src.graph.tech_checkout import tech_checkout_answer

        assert tech_checkout_answer(q, PAGE) is not None
