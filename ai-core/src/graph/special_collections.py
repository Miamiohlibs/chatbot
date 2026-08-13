"""Special Collections facts, supplied by the department that owns them.

PROVENANCE
Everything marked DEPT below came from the Special Collections colleague as a
written Q&A, handed over by the operator (Meng Qu, Libraries) on 2026-08-13.
The operator's ruling that day: where her document conflicts with what we
already hold, HERS WINS -- she owns the service.

That ruling has one live exception the operator should know about, recorded
here rather than buried in a commit message:

    HER HOURS DISAGREE WITH THE DEPARTMENT'S OWN WEBSITE.
    spec.lib.miamioh.edu/home/ states a flat "Book an Appointment
    M-F 9:00a-4:00p". She states Fall/Spring 8:00-4:00 and Summer/Winter
    breaks 9:00-4:00. Today (2026-08-13, summer) the two agree at 9-4, so
    nothing is visibly broken yet -- the split only bites when Fall term
    starts, within weeks of the beta launch. The website is the copy a
    patron can check us against, and it will then say something different
    from the bot. The fix is a website edit, not a code change.

WHY NOT IN THE SEARCH INDEX
Same reason as facility_facts: the index is a faithful copy of pages a patron
can read, and putting unpublished claims in it would break the promise that
every indexed sentence traces back to a real page. Anything here that later
appears on the website should be DELETED from this module, so there is one
source of truth.

WHAT IS CITED AND WHAT IS NOT
A fact that is not on a page does not get a citation marker pointing at that
page. The location, the three archives and the appointment booking ARE
published and are cited. The conduct rules, the ID requirement, who may use
the reading room, the lockers and the semester hours split are NOT on any
page we hold -- they are given as the department's own information and
labelled as such in the answer text.

    Verified against the live index 2026-08-13: spec.lib.miamioh.edu/home/,
    /home/visiting/ and /home/about-archives/ are the only Special
    Collections pages we hold. None of them mentions drop-ins, lockers,
    permitted items, pens, bags, or the ID requirement.

WHY LOCKERS ARE THE REASON THIS MODULE EXISTS
The operator asked the running bot about lockers and got King's FACULTY AND
GRADUATE READING ROOM lockers -- a yearly assigned locker restricted to
faculty and grad students. Her lockers are a different thing entirely: free,
secure, for any reading-room visitor's belongings, because bags are not
allowed in. An undergraduate or a community researcher was being told they
were not eligible for a locker they are in fact entitled to use.

Two services, one word. See `sc_locker_answer` and the caller in
new_orchestrator's `_locker_answer`.
"""
from __future__ import annotations

import re
from typing import Optional

# --- published, therefore citable ----------------------------------------

SPEC_HOME_URL = "https://spec.lib.miamioh.edu/home/"
SPEC_VISITING_URL = "https://spec.lib.miamioh.edu/home/visiting/"
SPEC_ARCHIVES_URL = "https://spec.lib.miamioh.edu/home/about-archives/"

ARCHIVES_EMAIL = "Archives@MiamiOH.edu"
ARCHIVES_PHONE = "(513) 529-6720"
"""Both from /home/about-archives/, which names them as the contact for
appointments and questions."""

# --- DEPT: her document, not on any page we hold --------------------------

SEMESTER_HOURS = (
    "8:00am-4:00pm during Fall and Spring semester, and 9:00am-4:00pm over "
    "Summer and Winter breaks"
)
CLOSED_NOTE = "closed weekends and university holidays"
READING_ROOM_CLOSES = "The Reading Room closes promptly at 4:00pm"

PERMITTED = ("pencils, loose paper, laptops and tablets, phones, and cameras "
             "for research photography")
NOT_PERMITTED = "pens and markers, backpacks and bags, food, and drink"


def _cite(n: int, url: str, snippet: str) -> dict:
    return {"n": n, "url": url, "snippet": snippet}


def dept_note() -> str:
    """One sentence, on every answer carrying unpublished facts.

    A patron who cannot find this on the website has to be able to tell WHY,
    and who to check with. Without it the bot is asserting things no page
    backs, which is the failure mode the whole citation discipline exists to
    prevent.
    """
    return (
        f"This comes from the Special Collections staff rather than a web "
        f"page, so to confirm before you travel, call {ARCHIVES_PHONE} or "
        f"email {ARCHIVES_EMAIL}."
    )


# --- matchers -------------------------------------------------------------
#
# These fire before the agent. Tight on purpose: a false positive replaces a
# good retrieved answer with a canned one.

SC_RE = re.compile(
    r"\b(special\s+collections?|spec\s*coll|university\s+archives?|"
    r"havighurst|rare\s+books?)\b",
    re.IGNORECASE,
)
"""The department. Deliberately NOT bare "archives" -- that word also shows up
in digital-collections and government-documents questions, which have their
own better answers."""

_READING_ROOM_RE = re.compile(r"\breading\s+room\b", re.IGNORECASE)

_OTHER_COLLECTIONS_RE = re.compile(
    r"\b(what\s+(other|else)|other\s+collections?|which\s+collections?|"
    r"what\s+collections?|what'?s\s+in|what\s+is\s+in|hold|holds|holdings|"
    r"contain|contains|inside)\b",
    re.IGNORECASE,
)

_WHO_MAY_USE_RE = re.compile(
    r"\b(who\s+(can|may|is\s+allowed|are\s+allowed)|am\s+i\s+allowed|"
    r"can\s+(anyone|the\s+public|community|a\s+visitor|visitors?|"
    r"non[- ]?miami|someone)|"
    # Bare "can i" was a bug, measured against the deployed bot 2026-08-13:
    # "where CAN I learn more" and "what CAN I bring" both matched it, and
    # this matcher runs early, so both got the who-may-use answer instead of
    # their own. Tie it to verbs about USING THE DEPARTMENT.
    r"can\s+i\s+(use|visit|come|go|enter|access|get\s+in(to)?)|"
    r"open\s+to\s+(the\s+)?(public|everyone|anyone)|eligib\w*|"
    # "an ID", not just "a id" -- the article has to allow both or the most
    # natural phrasing of the question misses.
    r"do\s+i\s+need\s+(an?\s+)?(id|i\.d\.|identification|photo)|"
    r"non[- ]?miami|not\s+a\s+student|unaffiliated|visiting\s+scholar)\b",
    re.IGNORECASE,
)

# Split in two, because a bare "can i use" belongs to the who-may-use
# question, not to this one. An items question names an ITEM or uses a
# bring-verb; "can I use Special Collections" does neither.
_ITEM_RE = re.compile(
    r"\b(pen|pens|pencil|pencils|marker|markers|laptop|laptops|tablet|"
    r"tablets|backpack|backpacks|bag|bags|food|drink|drinks|water|coffee|"
    r"camera|cameras|photo|photos|photograph\w*|notebook|notebooks|"
    r"belongings)\b",
    re.IGNORECASE,
)
_BRING_VERB_RE = re.compile(
    r"\b(bring|carry\s+in|take\s+in(to)?|allowed\s+in(side)?|"
    r"permitted\s+in(side)?)\b",
    re.IGNORECASE,
)

_DROPIN_RE = re.compile(
    r"\b(drop[- ]?in|drop[- ]?ins|walk[- ]?in|walk[- ]?ins|"
    r"without\s+an?\s+appointment|need\s+an?\s+appointment|"
    r"appointment\s+(required|necessary|needed)|"
    r"do\s+i\s+(have\s+to|need\s+to)\s+(book|schedule|make)|just\s+show\s+up)\b",
    re.IGNORECASE,
)

_LOCKER_RE = re.compile(r"\blockers?\b", re.IGNORECASE)

_LEARN_MORE_RE = re.compile(
    r"\b(learn\s+more|find\s+out\s+more|more\s+(info|information)|"
    r"website|web\s*site|web\s*page|home\s*page|url|link)\b",
    re.IGNORECASE,
)


# --- answers --------------------------------------------------------------


def other_collections_answer(message: str) -> "Optional[tuple[str, list[dict]]]":
    """What else lives in Special Collections.

    The live bot answered this with the Oxford-only campus speech -- a true
    sentence about a question nobody asked. Measured 2026-08-13.
    """
    m = message or ""
    if not (SC_RE.search(m) and _OTHER_COLLECTIONS_RE.search(m)):
        return None
    # "digital collections" is a separate service with its own answer.
    # `docs?` alone does not match "documents" -- \b fails mid-word, so
    # "government documents" sailed straight past this guard.
    if re.search(r"\b(digital|online|gov(ernment)?\s*(docu?ments?|docs?)|"
                 r"newspaper)\b", m, re.IGNORECASE):
        return None
    return (
        "The University Archives is in Special Collections. It holds "
        "materials for **Miami University, Western College and Oxford "
        "College** -- three archives, all on the third floor of King "
        "Library [1].\n\n"
        "Alongside the archives, Special Collections holds over 125,000 "
        "volumes of rare books, manuscripts and special subject "
        f"collections [2]. For a specific collection, {ARCHIVES_EMAIL} or "
        f"{ARCHIVES_PHONE} will get you to the right person.",
        [_cite(1, SPEC_ARCHIVES_URL,
               "Walter Havighurst Special Collections & University Archives — "
               "about the archives"),
         _cite(2, SPEC_HOME_URL,
               "Walter Havighurst Special Collections & University Archives")],
    )


def who_may_use_answer(message: str) -> "Optional[tuple[str, list[dict]]]":
    """DEPT: open to everyone, with photo ID.

    The live bot answered this with the reading-room handling speech and
    never said who may use it. A community researcher had no way to learn
    they are welcome.
    """
    m = message or ""
    if not (SC_RE.search(m) and _WHO_MAY_USE_RE.search(m)):
        return None
    return (
        "**Special Collections is open to everyone** -- Miami students and "
        "faculty, community members with no university affiliation, and "
        "visiting scholars.\n\n"
        "All visitors must present a **valid school-issued or government "
        "photo ID**, such as a driver's licence, and register on arrival. "
        "Materials do not circulate, so you consult them in the Reading Room "
        "on the third floor of King Library [1].\n\n"
        + dept_note(),
        [_cite(1, SPEC_VISITING_URL,
               "Walter Havighurst Special Collections & University Archives — "
               "visiting")],
    )


def reading_room_items_answer(message: str) -> "Optional[tuple[str, list[dict]]]":
    """DEPT: what may and may not come into the Reading Room.

    Until now the bot said these conditions "aren't spelled out on the
    website, and I'd rather not guess at them". That was the honest answer
    when we did not know. We know now.
    """
    m = message or ""
    if not (SC_RE.search(m) or _READING_ROOM_RE.search(m)):
        return None
    if not (_ITEM_RE.search(m) or _BRING_VERB_RE.search(m)):
        return None
    return (
        f"In the Special Collections Reading Room you may bring in "
        f"**{PERMITTED}**.\n\n"
        f"Not permitted: **{NOT_PERMITTED}**.\n\n"
        f"**Free, secure lockers are provided** for your bag and anything "
        f"else you cannot take in, so you do not have to leave belongings "
        f"unattended or make a second trip.\n\n"
        + dept_note(),
        [],
    )


def dropins_answer(message: str) -> "Optional[tuple[str, list[dict]]]":
    """DEPT: drop-ins ARE welcome. An appointment is encouraged, not required.

    This is the correction with the most at stake. Every existing Special
    Collections answer said "access is by appointment", full stop, which
    reads as a closed door -- and the department says the door is open. A
    patron who could have walked in was being told not to come.
    """
    m = message or ""
    if not (SC_RE.search(m) and _DROPIN_RE.search(m)):
        return None
    return (
        "**Drop-ins are welcome** -- you do not need an appointment to "
        "visit.\n\n"
        "That said, the staff strongly encourage booking in advance, because "
        "then they can retrieve your materials ahead of time rather than "
        "while you wait. You can book a visit through the Special Collections "
        f"website [1], or by phone on {ARCHIVES_PHONE}.\n\n"
        "Bring a valid school-issued or government photo ID either way -- "
        "everyone registers on arrival.",
        [_cite(1, SPEC_HOME_URL,
               "Walter Havighurst Special Collections & University Archives — "
               "book an appointment")],
    )


def sc_locker_answer(message: str) -> "Optional[tuple[str, list[dict]]]":
    """DEPT: the Special Collections patron lockers.

    NOT King's Faculty and Graduate Reading Room lockers, which is what the
    bot used to answer with. These are free, need no assignment, and are open
    to anybody visiting the Reading Room -- because bags are not allowed in,
    so the locker is part of being able to visit at all.
    """
    m = message or ""
    if not (_LOCKER_RE.search(m) and SC_RE.search(m)):
        return None
    return (
        "Yes -- **Special Collections provides free, secure lockers** for "
        "your personal belongings while you work in the Reading Room. There "
        "is no application and no eligibility requirement: they are there "
        "for anyone visiting.\n\n"
        f"You will need one, because {NOT_PERMITTED} cannot come into the "
        "Reading Room.\n\n"
        "(These are separate from the yearly assigned lockers in King's "
        "Faculty and Graduate Reading Rooms, which are restricted to faculty "
        "and graduate students.)\n\n"
        + dept_note(),
        [],
    )


def learn_more_answer(message: str) -> "Optional[tuple[str, list[dict]]]":
    """Hand over the URL, plainly. She asked for the URL to be given."""
    m = message or ""
    if not (SC_RE.search(m) and _LEARN_MORE_RE.search(m)):
        return None
    return (
        f"Special Collections has its own website: {SPEC_HOME_URL} [1]. It "
        "covers the collections, the three archives, visiting and parking, "
        "the staff, and appointment booking.\n\n"
        f"For anything it does not answer, {ARCHIVES_EMAIL} or "
        f"{ARCHIVES_PHONE} reaches the department directly.",
        [_cite(1, SPEC_HOME_URL,
               "Walter Havighurst Special Collections & University Archives")],
    )


def hours_rider() -> str:
    """The sentence appended to the LIVE LibCal hours answer.

    Live hours stay live -- LibCal is the source for "are they open today",
    and burning her static figures in as the answer would go stale exactly
    the way the website's flat "M-F 9-4" already has. What her document adds
    that LibCal cannot express is the SEMESTER PATTERN, the holiday closure,
    and the promptly-at-4 rule, so those ride along as context.

    The appointment wording is also corrected here: the old rider said
    research access "is by appointment", which contradicts the department.
    """
    return (
        f"In general Special Collections is open {SEMESTER_HOURS}, "
        f"{CLOSED_NOTE}. {READING_ROOM_CLOSES}, so plan to arrive with time "
        f"to work.\n\n"
        f"Drop-ins are welcome, but booking ahead means staff can retrieve "
        f"your materials before you arrive."
    )


__all__ = [
    "ARCHIVES_EMAIL", "ARCHIVES_PHONE", "CLOSED_NOTE", "NOT_PERMITTED",
    "PERMITTED", "READING_ROOM_CLOSES", "SC_RE", "SEMESTER_HOURS",
    "SPEC_ARCHIVES_URL", "SPEC_HOME_URL", "SPEC_VISITING_URL",
    "dept_note", "dropins_answer", "hours_rider", "learn_more_answer",
    "other_collections_answer", "reading_room_items_answer",
    "sc_locker_answer", "who_may_use_answer",
]
