"""Building facts the library knows but its website does not publish.

PROVENANCE, AND WHY IT IS WRITTEN DOWN HERE
Everything in this module came from the operator (Meng Qu, Libraries) on
2026-08-04, not from a crawl. It is in code rather than in the search index
because the search index is a faithful copy of lib.miamioh.edu, and putting
unpublished claims in there would quietly break the promise that every
indexed sentence traces back to a page a patron can read.

THE 2026-08-04 RULE WAS REVERSED ON 2026-08-17 -- READ THIS FIRST.
Four answers here were originally written from the operator's own knowledge,
on the reasoning that "refusing a question the staff can answer in one
sentence is the worst kind of unhelpful": quiet-study floors, reading-room
floors, restrooms on every floor, and no lactation room.

The operator reversed that for the PHYSICAL PLANT. Any library hardware or
infrastructure the website does not cover now goes to the service desk, via
`building_facility_answer`. Those four claims carried no citation, so nobody
reading an answer could tell one had gone stale -- which is exactly the
failure the paragraph below had predicted from day one. A wrong floor sends
someone up three flights for nothing.

What remains here is only what a PAGE or a published FAQ backs: printing
prices and guides, Wi-Fi, the computer labs. The rule is about UNSOURCED
claims, not about declining to be useful.

RE-VERIFY WHEN THE BUILDING CHANGES
Anything here that later appears on the website should be DELETED from this
module so there is one source of truth.

WHAT IS DELIBERATELY NOT CITED
A fact that is not on a page does not get a citation marker pointing at that
page. Where a real page supports part of the answer (the Reading Rooms page
genuinely is titled "Faculty and Graduate Reading Room") it is cited; the
floor numbers, which the page does not state, are given as the library's own
information and marked as such.
"""
from __future__ import annotations

import re
from typing import Optional

# --- verified live 2026-08-04 (HTTP 200, redirect target recorded) --------

READING_ROOMS_URL = "https://www.lib.miamioh.edu/use/spaces/reading-rooms/"
"""200, title "Faculty and Graduate Reading Room | Miami University Libraries"."""

KING_LIBRARY_URL = "https://www.lib.miamioh.edu/about/locations/king-library/"

PRINTING_PAGE_URL = "https://www.lib.miamioh.edu/use/technology/printing/"
"""200, "Printing and WiFi". A LINK LIST -- its value is the two destinations
below plus an embedded video, which is why extracting only its text yielded
231 useless characters."""

MUPRINT_GUIDE_URL = (
    "https://miamioh.teamdynamix.com/TDClient/1813/Portal/KB/Article/84563/User-Guide"
)
"""200, "User Guide / MUprint" -- university IT's printing guide, the page the
Libraries' own printing page links to. Reached via the redirect from
.../KB/ArticleDet?ID=84563; the canonical form is recorded here."""

WIFI_SERVICE_URL = (
    "https://miamioh.teamdynamix.com/TDClient/1813/Portal/Requests/Service/4444/Wi-Fi"
)
"""200, "Service - Wi-Fi" -- university IT's Wi-Fi service page."""

PRINTING_VIDEO_URL = "https://www.youtube.com/watch?v=JiNgoIoYfGg"
"""200. The how-to video embedded on the Libraries' printing page."""

ASK_US_URL = "https://www.lib.miamioh.edu/research/research-support/ask/"

KING_PHONE = "(513) 529-4141"

# --- matchers -------------------------------------------------------------
#
# Tight on purpose. These fire before the agent, so a false positive replaces
# a good retrieved answer with a canned one.

# _QUIET_RE, _RESTROOM_RE, _NURSING_RE and _NURSING_IS_THE_SUBJECT_RE lived
# here until 2026-08-18. They belonged to the four answers the operator's
# 2026-08-17 ruling removed, and were left behind dead -- one of them shadowed
# by an identically named matcher further down, which is worse than useless
# because a reader cannot tell which one is live. Their surviving equivalents
# are _QUIET_SPACE_RE, _BUILDING_FIXTURE_RE and _FIXTURE_IS_ACADEMIC_RE, next
# to `building_facility_answer`.
_PRINT_SCAN_WIFI_RE = re.compile(
    r"\b(print|prints|printing|printer|printers|photocopy|copier|"
    r"scan|scans|scanning|scanner|scanners|"
    r"wifi|wi-?fi|wireless|internet)\b",
    re.IGNORECASE,
)

# The printing/wifi answer must not hijack questions that only LOOK related:
# 3D printing has its own page and its own short-circuit, and "print" appears
# in reprints/fines questions.
# This matcher is the broadest in the short-circuit table, and the 2026-08-04
# eval showed it overfiring: it replaced four GOOD specific answers with the
# same generic MUprint pointer --
#   "does Wertz have printing"      -> lost the Wertz-specific answer
#   "can I print in color"          -> never confirmed colour
#   "scanning at all three campuses"-> lost the per-campus verification
#   a policy-link case              -> lost the corrected link
# It gained two and lost four. So it now declines anything it cannot actually
# answer: a named campus or library, a comparison, or a specific capability.
_NOT_PRINTING_RE = re.compile(
    r"\b(3d|three-?d|makerspace|maker\s*space|reprint|reprints|"
    r"fine|fines|charge|charges|cost|price|how\s+much"
    # a specific capability the generic pointer does not state
    r"|colour|color|black\s*(and|&)\s*white|b\s*&\s*w|double\s*sided|duplex"
    r"|11x17|poster|large\s*format"
    # a named library / campus, or a comparison -- the generic answer cannot
    # confirm anything building-specific
    r"|wertz|art\s*(and|&)\s*architecture|rentschler|hamilton|gardner|"
    r"middletown|king|regional|all\s+(three\s+)?campuses?|each\s+campus|"
    r"every\s+campus|both\s+campuses|which\s+(library|campus)|compare"
    # "Do ALL THE LIBRARIES have scanners?" needs a per-campus answer, and the
    # generic pointer cannot give one (gold xc2_scanning_all_campuses).
    r"|all\s+(the\s+)?librar(y|ies)|every\s+librar(y|ies)|each\s+librar(y|ies)"
    # "Where is the printing POLICY?" is asking for one specific page, and the
    # gold checks that only the approved page is cited -- a four-link answer
    # fails it by construction (gold cit_blacklisted_url_dropped).
    r"|policy|policies"
    # "SCAN" IS NOT ALWAYS OUR SCANNER. Two real asks on 2026-08-17 got the
    # MUprint guide because the word appeared in them at all:
    #   "...can I use interlibrary loan if I only need a photo or a SCAN of
    #    an image from a 2001 issue?"        -> an ILL question
    #   "an OCR SOFTWARE capable of SCANNING and translating Japanese ... do
    #    we have access to ABBYY?"           -> a software-access question
    # In both, scanning is the deliverable or the software's function, not
    # something the patron wants to do at our machines.
    r"|interlibrary\s+loan|\bill\s+request|\bocr\b|software|translat\w*"
    r"|subscri\w*)\b",
    re.IGNORECASE,
)


# Which PART of print/scan/wifi the patron actually asked about.
_WIFI_ONLY_RE = re.compile(r"\b(wifi|wi-?fi|wireless|internet|network)\b",
                           re.IGNORECASE)
_PRINT_OR_SCAN_RE = re.compile(
    r"\b(print|prints|printing|printer|printers|photocopy|copier|"
    r"scan|scans|scanning|scanner|scanners)\b", re.IGNORECASE)
# "How do I ...", "what are the steps" -- someone who wants to be walked
# through it. A yes/no ("can I print here?") does not need a video.
_HOWTO_RE = re.compile(
    r"\bhow\s+(do|can|would)\s+i\b|\bhow\s+to\b|\bsteps?\b|"
    r"\bwalk\s+me\b|\binstructions?\b|\bguide\b|\bset\s*up\b",
    re.IGNORECASE)


COMPUTER_LABS_URL = "https://www.lib.miamioh.edu/use/spaces/computer-labs/"
"""In the live index 2026-08-13: "Open-use Computers ... on every floor of King
Library as well as at the Art & Architecture Library. To use these computers,
login with your Miami ID and password." """

# --- "who can help with my computer?" -------------------------------------
#
# Kevin Messner (Head of Advise & Instruct) rated this 1/5 on 2026-08-13 --
# his worst score. The bot answered:
#
#     "Your subject librarian is Roger Justus at Oxford (justusra@..., ...)"
#
# His comment: "Their subject librarian is probably not Roger, and that's not
# the question being asked at all. this is just one of probably dozens of
# examples of the limitation of matching a word to a subject librarian."
#
# HOW IT HAPPENED, traced 2026-08-13: our own curated alias table does NOT
# contain a bare "computer" -- find_subject_by_alias("who can help with my
# computer?") returns None. The agent chose to call lookup_librarian with
# "computer" anyway, and that goes to the LIVE LibGuides API, which
# fuzzy-matched it to "Computer Science and Software Engineering". Roger
# Justus covers that subject, so the roster was right and the QUESTION was
# never understood.
#
# The fix here is the positive one: this question has a real answer, and it is
# not a librarian. It is asked before the agent so no lookup happens at all.
#
# WHAT THIS DOES NOT FIX, stated plainly because Kevin's point is wider than
# "computer": he also named education, business, paper, english, environment,
# management -- everyday words that ARE real subjects. Those cannot be
# stop-listed without breaking legitimate lookups, and the discriminator is
# context, not vocabulary. The possessive-plus-device shape ("my computer",
# "my laptop", "my password") IS reliable, and that is exactly the slice this
# matcher takes. "I need help with my business" remains genuinely ambiguous
# and is left to the agent.
# TWO conditions, both required. The first version needed only the noun, and
# that was too loose: "My account is messnekr" -- a patron DISCLOSING their
# username, which is Kevin Messner's own test input -- matched "my account"
# and got the IT-desk answer, displacing the correct one ("I don't have access
# to your library account, check it at ... or call ..."). Found by re-running
# his list against the deployed fix, 2026-08-13.
#
# A device noun alone is a statement. A device noun PLUS trouble is a request.
_IT_NOUN_RE = re.compile(
    # The possessive is load-bearing: "my computer" is a device, "computer
    # science" is a subject. The optional qualifier catches "my MIAMI account"
    # and "my UNIVERSITY email", which is how students say it.
    r"\b(my|the)\s+(?:miami\s+|university\s+|school\s+|muohio\s+)?"
    r"(computer|laptop|pc|mac|macbook|chromebook|tablet|ipad|"
    r"phone|device|account|password|login|log[- ]?in|username|net\s*id|"
    r"miami\s*id|email|screen|keyboard|charger)\b",
    re.IGNORECASE,
)
_IT_TROUBLE_RE = re.compile(
    r"\b(help|helps|fix|fixed|broken|break|not\s+working|isn'?t\s+working|"
    r"doesn'?t\s+work|won'?t\s+(work|start|turn|boot|open|connect|load)|"
    r"can'?t|cannot|unable|trouble|problem|problems|issue|issues|"
    r"reset|forgot|forgotten|locked\s+out|stuck|frozen|freezes|crashed|"
    r"crashes|error|dead|slow|virus|malware|"
    # "won't charge" IS a fault. "Where can I charge my laptop" is a question
    # about OUTLETS -- building infrastructure, so it goes to the desk. Bare
    # "charge" here sent it to IT support, which answered "that isn't a
    # library question" about a library building question.
    r"won'?t\s+charge|not\s+charging|"
    r"who\s+(can|do\s+i|should\s+i)|where\s+do\s+i\s+go)\b",
    re.IGNORECASE,
)
# A login/connection problem stated without a possessive at all: "I can't log
# in", "trouble connecting". Self-sufficient, so it bypasses the noun test.
_IT_LOGIN_TROUBLE_RE = re.compile(
    r"\b(can'?t|cannot|unable\s+to|trouble|problem|issue|help|forgot|"
    r"locked\s+out)\b[^.?!]{0,30}"
    r"\b(log\s*in|login|log\s*on|sign\s*in|connect|password|reset)\b",
    re.IGNORECASE,
)

# Never steal a genuine subject/research question, a course, or the things
# that already have their own better answers.
_NOT_IT_HELP_RE = re.compile(
    r"\b(computer\s+science|software\s+engineering|cse|comp\s*sci|"
    r"electrical\s+and\s+computer|computer\s+engineering|"
    # a subject/liaison ask, however phrased
    r"librarian|liaison|subject\s+specialist|"
    # things with their own short-circuits
    r"database|databases|journal|journals|article|articles|citation|"
    r"print|printing|printer|scan|scanning|wifi|wi-?fi|"
    r"checkout|check\s+out|borrow|loan|reserve|reserves|"
    r"3d|makerspace|maker\s*space|"
    # a course code
    r"[a-z]{3}\s*\d{3})\b",
    re.IGNORECASE,
)


def _cite(n: int, url: str, snippet: str) -> dict:
    return {"n": n, "url": url, "snippet": snippet}


def computer_help_answer(message: str) -> "Optional[tuple[str, list[dict]]]":
    """A broken device or a login problem is IT's, not a subject librarian's.

    Deliberately does NOT invent an IT phone number or portal URL -- nothing
    in the corpus carries one, and the whole point of this fix is to stop
    handing out confidently wrong contact details. It names the two routes we
    can actually stand behind: the library desk for a library machine, and
    Miami's IT support for a personal device or a Miami account.
    """
    m = message or ""
    if _NOT_IT_HELP_RE.search(m):
        return None
    # A BORROWING QUESTION WITH A BROKEN DEVICE IN FRONT OF IT IS STILL A
    # BORROWING QUESTION.
    #
    # Real question, 2026-08-06: "My laptop is broken. how long can I check
    # one out" was answered entirely about where to take a broken computer,
    # and never gave the laptop loan period -- which is the half the patron
    # asked. The broken device is the REASON, not the request.
    if re.search(r"\bhow\s+long\b|\bloan\s*period\b|\bcheck(ing)?\s*(one|"
                 r"a\s+\w+)?\s*out\b|\bcheckout\b|\bborrow\b|\brent\b",
                 m, re.IGNORECASE):
        return None
    asks_for_help = (
        (_IT_NOUN_RE.search(m) and _IT_TROUBLE_RE.search(m))
        or _IT_LOGIN_TROUBLE_RE.search(m)
    )
    if not asks_for_help:
        return None
    return (
        "That one isn't a library question, and there's no subject librarian "
        "assigned to it -- so let me point you at the right desk instead.\n\n"
        f"- **A computer in the library** that won't log in or isn't working: "
        f"ask at the information desk, or call {KING_PHONE}. The open-use "
        f"machines are on every floor of King and at Art & Architecture, and "
        f"they take your Miami ID and password [1].\n"
        "- **Your own laptop, phone, or your Miami account or password**: "
        "that's Miami University IT support, not the Libraries. They handle "
        "logins, password resets, and personal devices.\n\n"
        "If it turns out to be a library thing after all -- getting into a "
        "database, or a resource that won't load off campus -- tell me and I "
        "can help with that.",
        [_cite(1, COMPUTER_LABS_URL,
               "Miami University Libraries — Open-use computers")],
    )


# A REPORT IS NOT A QUESTION.
#
# Live traffic, 2026-08-17: "There is a toilet running on the second floor"
# was answered with where the restrooms are. The patron was not lost -- they
# were doing us a favour, and got a map.
#
# Nobody is going to file a work order through a chatbot, and pretending we
# can would be worse than useless. What we can do is thank them and give them
# the desk, in one short answer, which is what a member of staff would do.
_FACILITY_PROBLEM_RE = re.compile(
    r"\b(running|leak\w*|drip\w*|overflow\w*|clogged|blocked|broken|broke|"
    r"not\s+working|isn'?t\s+working|doesn'?t\s+work|won'?t\s+(flush|work|"
    r"turn\s+on|close|open)|out\s+of\s+order|flickering|burnt\s+out|"
    r"burned\s+out|(is|are|was|were)\s+out\b|spill\w*|flooded|smells?|stinks?|"
    r"no\s+(hot\s+)?water|"
    r"jammed|stuck)\b",
    re.IGNORECASE,
)
_FACILITY_THING_RE = re.compile(
    r"\b(toilet|urinal|sink|tap|faucet|restroom|bathroom|water\s+fountain|"
    r"drinking\s+fountain|bottle\s+filler|light|lights?|lamp|door|elevator|"
    r"lift|escalator|air\s*conditioning|a/?c|heat|heater|window|blind|"
    r"outlet|socket|printer|copier|scanner|computer|monitor|keyboard|"
    r"chair|table|desk|carpet|ceiling|floor)\b",
    re.IGNORECASE,
)
# A report STATES a condition. A question asks about one, and those keep their
# own answers ("is there a water fountain on the third floor?").
_ASKING_NOT_REPORTING_RE = re.compile(
    r"^\s*(is|are|does|do|can|could|where|when|how|what|which|who|why|may)\b"
    r"|\?\s*$",
    re.IGNORECASE,
)


def facility_problem_answer(message: str) -> "Optional[tuple[str, list[dict]]]":
    """Someone is reporting something broken. Thank them, hand them the desk."""
    m = message or ""
    if _ASKING_NOT_REPORTING_RE.search(m.strip()):
        return None
    if not (_FACILITY_PROBLEM_RE.search(m) and _FACILITY_THING_RE.search(m)):
        return None
    return (
        "Thanks for flagging that -- and sorry, I can't file a repair request "
        "myself.\n\n"
        f"The quickest route is the service desk: **{KING_PHONE}**, or stop "
        "at the desk on the first floor of King. They can get it to Facilities "
        "the same day.\n\n"
        f"If it's easier to write it down, Ask Us reaches a librarian who can "
        f"pass it on [1] -- mention the building and floor.",
        [_cite(1, ASK_US_URL, "Miami University Libraries — Ask Us")],
    )


# A PERSON BEING DISRUPTIVE IS NOT A BROKEN FIXTURE.
#
# "Someone is too loud in the library" -- a real report, 2026-08-17. It has no
# problem word and no fixture noun, so facility_problem_answer never sees it,
# and the agent has answered it three different ways across three runs: the
# conduct policy, "you can reserve a study room", and -- on 2026-08-20 --
# "report the disturbance to the Games Committee", lifted from a game-night
# event page. None of those is what a patron in that moment needs.
#
# It is a REPORT, not a policy question. "Can I talk in the library?" keeps
# going to the policy doc; _ASKING_NOT_REPORTING_RE separates the two.
_DISTURBANCE_RE = re.compile(
    r"\b(too\s+loud|so\s+loud|being\s+loud|really\s+loud|very\s+loud|"
    r"noisy|making\s+(a\s+lot\s+of\s+)?noise|shouting|yelling|screaming|"
    r"blasting|talking\s+loudly|on\s+speakerphone|playing\s+music\s+out\s+loud|"
    r"disruptive|disturbing\s+(me|others|people)|bothering\s+(me|others)|"
    r"harass\w*|won'?t\s+be\s+quiet)\b",
    re.IGNORECASE,
)


def disturbance_report_answer(message: str) -> "Optional[tuple[str, list[dict]]]":
    """Someone is reporting a person, not a fixture. Point at staff."""
    m = message or ""
    if not _DISTURBANCE_RE.search(m):
        return None
    if _ASKING_NOT_REPORTING_RE.search(m.strip()):
        return None      # "is the library noisy?" is a question, not a report
    return (
        "Sorry -- that is worth telling staff about, and they would rather "
        "hear it than not.\n\n"
        f"The quickest route is the service desk: **{KING_PHONE}**, or speak "
        "to whoever is at the desk on your floor. Staff can go and deal with "
        "it; I can't.\n\n"
        "If you would rather move than wait, study rooms are bookable and the "
        "quiet floors are quieter -- but do tell the desk either way, because "
        "they cannot act on what they have not heard [1].",
        [_cite(1, ASK_US_URL, "Miami University Libraries — Ask Us")],
    )


PRINT_COST_FAQ_URL = "https://libanswers.lib.miamioh.edu/faq/163327"
"""FAQ 163327: "Printing costs in the Libraries are $0.10/page for B&W and
$0.25/page for Color." Corroborated by FAQ 174591, which adds that students pay
through MUlaa with their student ID. Both live in the index, checked
2026-08-16."""

# "IS THERE FREE PRINTING?" -- a real student, 2026-08-15, the first week of
# the beta. The bot answered with the MUprint and Wi-Fi guides: how to print,
# when they asked what it costs.
#
# _NOT_PRINTING_RE already excluded cost questions -- it lists cost, price,
# how much, charge, fines -- so the generic pointer was never meant to take
# this one. It just did not list the words people actually use. Measured:
#
#     "how much does printing cost"   -> correctly excluded
#     "Is there free printing?"       -> NOT excluded, got the guide
#     "do I have to pay to print"     -> NOT excluded, got the guide
#
# Excluding them is not enough on its own: we know the answer exactly, so the
# honest thing is to give it. "Free?" deserves yes or no, not a link.
#
# NOTE this is NOT affected by the 2026-08-17 "building facts go to the desk"
# ruling: these figures come from a published FAQ, not from memory. The rule
# is about unsourced claims, not about declining to be useful.
_PRINT_COST_RE = re.compile(
    r"\b(free|cost|costs|price|pricing|how\s+much|charge|charges|"
    r"pay|paid|paying|fee|fees|expensive|cheap|per\s+page)\b",
    re.IGNORECASE,
)


def printing_cost_answer(message: str) -> "Optional[tuple[str, list[dict]]]":
    """What printing costs. Leads with the answer to "is it free": no."""
    m = message or ""
    if not _PRINT_SCAN_WIFI_RE.search(m) or not _PRINT_COST_RE.search(m):
        return None
    # 3D printing has its own pricing and its own page.
    if re.search(r"\b(3d|three-?d|makerspace|maker\s*space)\b", m, re.IGNORECASE):
        return None
    # The FAQ prices PRINTING. A question only about scanning or Wi-Fi must
    # not be answered with per-page printing charges -- we do not hold a
    # scanning price, and inventing one from the printing figure would be a
    # new wrong answer in place of the old vague one.
    if not re.search(r"\b(print|prints|printing|printer|printers|photocopy|"
                     r"copier|copy|copies|per\s+page)\b", m, re.IGNORECASE):
        return None
    return (
        "**Printing is not free** -- it is charged by the page:\n\n"
        "- **Black and white: $0.10 a page**\n"
        "- **Colour: $0.25 a page**\n\n"
        "You pay through your **MUlaa** account with your student ID, so "
        "there is nothing to set up at the machine [1].\n\n"
        f"If a print job fails or a machine takes your money, call "
        f"{KING_PHONE} and someone at the desk can sort it out.",
        [_cite(1, PRINT_COST_FAQ_URL,
               "Miami University Libraries — how much does it cost to print?")],
    )


def printing_scanning_wifi_answer(message: str) -> "Optional[tuple[str, list[dict]]]":
    """Printing, scanning and Wi-Fi all live in university IT's guides.

    The Libraries' own printing page is a LINK LIST: two links and a video,
    and nothing else. Our extractor kept the link text ("Printing
    Instructions WiFi Connections") and dropped the destinations, so the bot
    retrieved 231 characters of menu and answered "King Library offers
    printing/scanning services" without ever giving the student the guide.
    Those destinations are what the question is actually asking for.

    ANSWER THE PART THAT WAS ASKED. Until 2026-08-18 this returned all four
    links every time, so "How do I print from my laptop?" and "Can I print
    here?" both came back reciting the Wi-Fi service page and a how-to video.
    The eval scored both `partial` for exactly that -- extra URLs beyond the
    one the question needed -- and it is the house failure mode besides:
    answering next to the question rather than at it. Wi-Fi appears only when
    Wi-Fi is asked about; the video only when someone wants the steps.
    """
    m = message or ""
    if not _PRINT_SCAN_WIFI_RE.search(m) or _NOT_PRINTING_RE.search(m):
        return None

    wants_wifi = bool(_WIFI_ONLY_RE.search(m))
    wants_paper = bool(_PRINT_OR_SCAN_RE.search(m))
    wants_steps = bool(_HOWTO_RE.search(m))
    if not (wants_wifi or wants_paper):
        wants_paper = True       # the gate matched something; default to paper

    lines: "list[str]" = []
    cites: "list[dict]" = []

    def _add(url: str, snippet: str) -> int:
        cites.append(_cite(len(cites) + 1, url, snippet))
        return len(cites)

    if wants_paper:
        n = _add(MUPRINT_GUIDE_URL, "Miami University IT — MUprint User Guide")
        lines.append(
            f"Printing and scanning in the libraries run on the University's "
            f"MUprint system, and the step-by-step guide is IT's [{n}]. "
            f"Miami's multifunction printers in the libraries both print and "
            f"scan."
        )
    if wants_wifi:
        n = _add(WIFI_SERVICE_URL, "Miami University IT — Wi-Fi")
        lines.append(
            f"For Wi-Fi, the University's Wi-Fi service page covers "
            f"connecting your device [{n}]."
        )
    if wants_paper and wants_steps:
        n = _add(PRINTING_VIDEO_URL,
                 "Miami University Libraries — printing how-to video")
        lines.append(f"There is also a short how-to video [{n}].")
    n = _add(PRINTING_PAGE_URL,
             "Miami University Libraries — Printing and WiFi")
    lines.append(
        f"The Libraries' own Printing and WiFi page links to all of it [{n}]."
    )
    lines.append(
        f"If something is broken or you are stuck at a machine, call "
        f"{KING_PHONE} and someone at the desk can help."
    )
    return "\n\n".join(lines), cites



# --- Adobe Creative Cloud: "Reserve" is a button, not a hold ----------------
#
# A librarian rated this 4/5 on 2026-08-18 with the reason written out:
# "Takes you to the correct library webpage. Students might not understand the
# word 'Reserve' in regards to software."
#
# They are right, and the word is not ours to change -- the software page's two
# links literally read "Reserve Adobe Creative Cloud (Student)" and
# "(Faculty/Staff)". To a student, "reserve" means a room for Tuesday or a
# textbook behind the desk. Here it means claiming one of the Libraries'
# licences for your own machine, permanently enough to install with. So the
# answer names the button, because that is what they have to click, AND says
# what it does.
#
# Deterministic because Adobe is the highest-volume software ask (it has its
# own intent, `adobe_access`) and the flow is stable page content: two links,
# then adobe.com with Miami credentials.
SOFTWARE_CHECKOUT_URL = "https://www.lib.miamioh.edu/software/"
"""In the index 2026-08-18: "Downloadable software you can check out on your
device ... Reserve Adobe Creative Cloud (Student) / Reserve Adobe Creative
Cloud (Faculty/Staff) ... After you have checked out a license you will be able
to login at adobe.com using your Miami credentials." """

LIBRARY_COMPUTER_SOFTWARE_URL = "https://www.lib.miamioh.edu/use/technology/software/"
"""In the index 2026-08-18: "Adobe Creative Cloud: installed, but requires
license checkout"."""

_ADOBE_RE = re.compile(
    r"\badobe\b|creative\s+cloud|\bcc\s+apps?\b|\bphotoshop\b|\bindesign\b|"
    r"\billustrator\b|\bpremiere\b|\bacrobat\b|\bafter\s+effects\b|\blightroom\b",
    re.IGNORECASE,
)
# Not the licence flow: a PDF that will not open, a font, a file conversion.
_ADOBE_NOT_RE = re.compile(
    r"\bpdf\b|\bebsco\b|\bwon'?t\s+open\b|\bcan'?t\s+open\b|\bcorrupt\w*|"
    r"\bconvert\b|\bfont\b|\bdigital\s+editions\b",
    re.IGNORECASE,
)
_ADOBE_ELIGIBILITY_RE = re.compile(
    r"\beligib\w*|\bqualify\b|\ballowed\b|\bentitled\b|\bpart[-\s]?time\b|"
    r"\badjunct\b|\bcontingent\b|\bemerit\w*|\balumn\w*|\bretired\b|"
    r"\bvisiting\b|\baffiliate\b",
    re.IGNORECASE,
)


def adobe_access_answer(message: str) -> "Optional[tuple[str, list[dict]]]":
    """How to get Adobe, in words a student has not had to decode."""
    m = message or ""
    if not _ADOBE_RE.search(m) or _ADOBE_NOT_RE.search(m):
        return None

    body = (
        "Adobe Creative Cloud -- Photoshop, InDesign, Premiere Pro, Acrobat "
        "Pro and the rest -- is something you check out from the Libraries and "
        "install on your **own** computer or tablet [1].\n\n"
        "On the software page there are two links. Take the one that matches "
        "you:\n\n"
        "- **Reserve Adobe Creative Cloud (Student)**\n"
        "- **Reserve Adobe Creative Cloud (Faculty/Staff)**\n\n"
        "**\"Reserve\" is just the wording on the button.** It does not hold "
        "anything for a date and it is nothing to do with course reserves -- "
        "it checks out one of the Libraries' licences to you.\n\n"
        "Once you have the licence, sign in at **adobe.com** with your Miami "
        "credentials and download whichever apps you want [1]."
    )
    cites = [_cite(1, SOFTWARE_CHECKOUT_URL,
                   "Miami University Libraries — software you can check out")]

    if _ADOBE_ELIGIBILITY_RE.search(m):
        body += (
            "\n\nOn who is eligible, the page offers a student link and a "
            "faculty/staff link and does not break it down further -- it says "
            "nothing about part-time, adjunct, emeritus or alumni status, so I "
            f"would rather not tell you either way. The desk on {KING_PHONE} "
            "can check your case before you count on it.\n\n"
            "On a library computer Adobe Creative Cloud is already installed, "
            "but it still needs a licence checked out to run [2]."
        )
        cites.append(_cite(2, LIBRARY_COMPUTER_SOFTWARE_URL,
                           "Miami University Libraries — software on library "
                           "computers"))
    return body, cites

# BUILDING FACTS WE CANNOT SOURCE GO TO THE SERVICE DESK.
#
# OPERATOR RULING 2026-08-17, reversing the 2026-08-04 decision this module was
# built on. The original rule was "refusing a question the staff can answer in
# one sentence is the worst kind of unhelpful", so four answers were written
# from the operator's own knowledge. None of them was on a page:
#
#   restrooms      "there are restrooms on every floor"      no citation at all
#   quiet study    "quiet areas on the 2nd and 3rd floors"   floors on no page
#   reading rooms  "both on the 2nd floor"                   floors on no page
#   nursing room   "there is no lactation room"              nowhere on the site
#
# The new rule, for the physical plant -- toilets, lifts, fixtures, floors:
# if it is not on the website, do not answer from memory. Send them to the desk.
#
# WHY THE REVERSAL IS RIGHT EVEN THOUGH THOSE ANSWERS WERE USEFUL
# This module warned about exactly this failure in its own header from day one:
# "a floor gets renovated and nobody updates a Python file". A confidently
# wrong floor sends someone up three flights for nothing, and NOBODY CAN TELL
# IT IS WRONG BY READING IT -- there is no citation to check against. The desk
# always knows the building; this file only knows what it was told once.
#
# WHAT IT STILL DOES, because this is a navigator and not a refusal machine:
# where a real page exists for the thing asked about, hand over the page AND
# the desk. The Reading Rooms page genuinely describes the rooms and who may
# use them; it simply does not give a floor. Withholding a page we hold would
# be its own kind of wrong.
# THE WHOLE PHYSICAL PLANT, not only the four things that used to be answered.
#
# Operator restated the rule 2026-08-18: any library hardware or
# infrastructure the website does not cover goes to the desk -- not just
# toilets and lifts.
#
# Broad on purpose, and that is ONLY safe because of where this is registered:
# after every page-backed answer in the group. Printing, scanning, Wi-Fi,
# computers, Special Collections and room booking all keep their questions
# because they run first, so what reaches here is by construction the
# infrastructure we have no published source for. It originally sat third in
# that group, ahead of computers and printing, and would have stolen them once
# broadened -- see the ordering test in test_facility_facts.
_BUILDING_FIXTURE_RE = re.compile(
    # sanitary
    r"\b(restroom|restrooms|bathroom|bathrooms|toilet|toilets|washroom|"
    r"men'?s\s+room|women'?s\s+room|urinal|baby\s+chang\w*|"
    # vertical circulation and access
    r"elevator|elevators|lift|lifts|escalator|stairs|stairway|stairwell|"
    r"ramp|entrance|turnstile|loading\s+dock|"
    # water and food fixtures
    r"water\s+fountain|drinking\s+fountain|bottle\s+filler|water\s+cooler|"
    r"vending|microwave|fridge|refrigerator|coffee\s+machine|"
    # power, climate, light
    r"outlet|outlets|socket|sockets|power\s+strip|charging\s+station|"
    r"charge\w*\s+(my|a|the)?\s*(laptop|phone|computer|tablet|device)|"
    r"air\s*condition\w*|radiator|thermostat|ventilation|"
    r"too\s+(hot|cold)|light\s+switch|lamps?|"
    # furniture and fittings
    r"carrel|carrels|standing\s+desk|whiteboard|chalkboard|"
    r"coat\s+rack|umbrella\s+stand|bike\s+rack|recycling|"
    r"first\s+aid|aed|defibrillator|"
    # lactation -- a room question, not a subject question
    r"nursing|lactation|breastfeed\w*|breast\s*feed\w*|"
    r"pump(ing)?\s+room|mother'?s\s+room)\b",
    re.IGNORECASE,
)
# The academic senses of "nursing" keep their own answers. This carries over
# the 2026-08-12 fix: "who is the nursing librarian" was being answered with
# "King Library has no lactation room".
_FIXTURE_IS_ACADEMIC_RE = re.compile(
    r"\b(librarian|liaison|subject\s+specialist|research|"
    r"database|databases|journals?|articles?|citation|literature|"
    r"program|programme|major|degree|course|class|students?|faculty|school)\b",
    re.IGNORECASE,
)
# A ROOM WITH A WHITEBOARD IS A BOOKING, NOT A FIXTURE HUNT.
#
# `whiteboard` belongs in the fixture list -- "is there a whiteboard I can use"
# is a desk question. But on 2026-08-18 the eval showed this answer taking
# "Need a room for 4 with a whiteboard at King", whose allowed URL is LibCal:
# the patron is reserving a space and naming an amenity to filter on, and they
# got the service-desk referral instead of the reservation page.
#
# The fixture senses ask WHERE SOMETHING IS. These ask FOR A ROOM.
_FIXTURE_IS_A_ROOM_REQUEST_RE = re.compile(
    r"\b(rooms?|spaces?)\b[^.?!]{0,30}\b(for|with|that\s+has|containing)\b"
    r"|\b(book|booking|reserve|reserving|reservation|schedule|scheduling)\b"
    r"[^.?!]{0,30}\b(rooms?|spaces?)\b"
    r"|\b(need|want|looking\s+for|find\s+me)\b[^.?!]{0,24}\b(rooms?|spaces?)\b",
    re.IGNORECASE,
)
_QUIET_SPACE_RE = re.compile(
    r"\b(silent|quiet)\b[^.?!]{0,30}\b(area|areas|floor|floors|space|spaces|"
    r"section|room|rooms|study|zone)\b"
    r"|\b(study|studying|read|reading|floor|floors|somewhere|anywhere|place)\b"
    r"[^.?!]{0,24}\b(silent|silently|quiet|quietly)\b"
    r"|\bwhere\b[^.?!]{0,20}\b(silent|quiet)\b",
    re.IGNORECASE,
)
_READING_ROOM_RE = re.compile(
    r"\b(grad(uate)?|faculty|staff)\b[^.?!]{0,24}\breading\s+room",
    re.IGNORECASE,
)


def building_facility_answer(message: str) -> "Optional[tuple[str, list[dict]]]":
    """Where is X in the building? The desk answers, not this file.

    Replaces quiet_study_answer, reading_room_answer, restroom_answer and
    nursing_room_answer. See the note above for why all four were removed.
    """
    m = message or ""
    reading_room = bool(_READING_ROOM_RE.search(m))
    fixture = bool(_BUILDING_FIXTURE_RE.search(m))
    if fixture and _FIXTURE_IS_ACADEMIC_RE.search(m):
        fixture = False          # the nursing LIBRARIAN, not a lactation room
    if fixture and _FIXTURE_IS_A_ROOM_REQUEST_RE.search(m):
        fixture = False          # "a room WITH a whiteboard" -> the booking path
    if not (reading_room or fixture or _QUIET_SPACE_RE.search(m)):
        return None

    if reading_room:
        return (
            "King Library has a Graduate Reading Room and a Faculty & Staff "
            "Reading Room, reserved for those groups respectively. The "
            "Reading Rooms page covers who may use them and how access "
            "works [1].\n\n"
            "It does not say which floor they are on, and I would rather not "
            f"guess -- the service desk will tell you: **{KING_PHONE}**, or "
            "ask at the desk on the first floor.",
            [_cite(1, READING_ROOMS_URL,
                   "Miami University Libraries — Faculty and Graduate "
                   "Reading Room")],
        )

    return (
        "I can't find that on the Libraries' website, and I would rather send "
        "you to someone who knows than guess at it.\n\n"
        f"The service desk has the current answer: **{KING_PHONE}**, or ask at "
        "the desk on the first floor of King. For anything about the building "
        "itself they are the right people -- layouts change and a web page "
        "does not always keep up.\n\n"
        "If you would rather write it down, Ask Us reaches a librarian [1].",
        [_cite(1, ASK_US_URL, "Miami University Libraries — Ask Us")],
    )


# --- parking: DOCUMENTED, so it is answered, not deferred -------------------
#
# The operator listed parking among the things to send to the desk
# (2026-08-18). Checked first, and it is one of the better-documented topics
# we have, so deferring it would mean withholding pages we hold -- which is
# the mistake they themselves ruled out with the reading-room example ("页面
# 提供过的信息比如locker" gets given).
#
# In the live index 2026-08-18:
#   libanswers 176243 "Where can I park on campus?" -- two garages, ~100
#       meters, no permit needed at either, permit required elsewhere, areas
#       colour-coded by privilege
#   ham.miamioh.edu/library/about/ -- "Free visitor parking ... in the large
#       parking lot just north of the library"
#   spec.../home/visiting/ -- metered street parking, Oxford Municipal garage,
#       visitor permits from the Parking Office
#
# What is NOT on any page is the live state -- whether a garage is full right
# now, whether a lot is closed for an event. Those are temporary, and
# `temporary_notice_answer` below takes them.
PARKING_FAQ_URL = "https://libanswers.lib.miamioh.edu/faq/176243"
HAMILTON_ABOUT_URL = "https://www.ham.miamioh.edu/library/about/"

_PARKING_RE = re.compile(
    r"\b(park|parking|garage|garages|meter|meters|permit|permits|"
    r"where\s+(can|do)\s+i\s+park|lot|lots)\b",
    re.IGNORECASE,
)
_PARKING_NOT_RE = re.compile(
    # "parking lot" senses that are not about parking a car, plus the live-state
    # questions that belong to the temporary-notice answer.
    r"\b(bike\s+rack|full\s+right\s+now|any\s+spaces?\s+(left|free)|"
    r"closed\s+(today|for)|blocked)\b"
    # BUYING A PERMIT IS A TRANSACTION, NOT A LIBRARY FACT.
    #
    # "How do I buy a parking pass?" is Parking & Transportation Services'
    # process -- rates, eligibility, the payment portal -- and none of it is on
    # a library page. On 2026-08-18 the eval scored this
    # answered_should_have_refused: the bot recited Oxford's permit policy and
    # added a phone number, when gold asks it to decline and not invent a
    # process. Telling someone where they may park is ours; selling them the
    # permit is not.
    r"|\b(buy|purchase|pay\s+for|order|renew|apply\s+for|register\s+for|"
    r"get\s+a)\b[^.?!]{0,24}\b(pass|passes|permit|permits|decal|hangtag|"
    r"sticker)\b"
    r"|\bparking\s+(pass|permit)\b[^.?!]{0,24}\b(cost|price|how\s+much)\b",
    re.IGNORECASE,
)


def parking_answer(message: str) -> "Optional[tuple[str, list[dict]]]":
    """Where to park. Page-backed, so it gets answered."""
    m = message or ""
    if not _PARKING_RE.search(m) or _PARKING_NOT_RE.search(m):
        return None
    if re.search(r"\b(hamilton|rentschler)\b", m, re.IGNORECASE):
        return (
            "Rentschler Library is on the 2nd floor of Schwarm Hall on the "
            "Hamilton campus, and **free visitor parking** is in the large "
            "lot just north of the library [1].",
            [_cite(1, HAMILTON_ABOUT_URL, "Rentschler Library — about")],
        )
    return (
        "On the Oxford campus, **a permit is required** to park on campus and "
        "on the streets running through it, with two exceptions: Miami has "
        "**two parking garages** and about **100 metered spaces** that need no "
        "permit -- you just pay for the time you are there. Parking areas are "
        "colour-coded by who may use them [1].\n\n"
        f"For anything the page does not cover -- whether a garage is full, or "
        f"a lot is closed for an event -- the service desk will know: "
        f"**{KING_PHONE}**.",
        [_cite(1, PARKING_FAQ_URL,
               "Miami University Libraries — where can I park on campus?")],
    )


# --- temporary and short-term: the desk always, by definition ---------------
#
# OPERATOR RULING 2026-08-18: anything short-term, temporary or event-shaped
# goes to the desk. The reasoning is the same as for unsourced building facts,
# only stronger: this content is not merely absent from the site, it CHANGES,
# and a crawl is a snapshot. Nothing in the index describes current closures
# or construction (checked -- the only "closed" hits are two unrelated FAQs).
#
# Hours are the explicit exception the operator named, and they are excluded
# here: those come live from LibCal, including holiday and break hours, and
# must keep reaching that path.
_TEMPORARY_RE = re.compile(
    r"\b(construction|renovat\w*|refurbish\w*|"
    r"out\s+of\s+(service|order)|temporarily\s+(closed|shut|unavailable)|"
    r"closed\s+(today|right\s+now|at\s+the\s+moment|for\s+(repairs?|"
    r"maintenance|an?\s+event))|"
    r"why\s+is\s+[^.?!]{0,30}\s+closed|"
    r"any\s+(delays?|disruptions?|outages?)|"
    r"road\s*works?|scaffolding|blocked\s+off|cordoned)\b",
    re.IGNORECASE,
)
# Holiday / break questions that are NOT hours -- "will the bookdrop be
# emptied over winter break", "is anything different at Thanksgiving".
_HOLIDAY_NON_HOURS_RE = re.compile(
    r"\b(thanksgiving|christmas|winter\s+break|spring\s+break|"
    r"fall\s+break|summer\s+break|holiday|holidays|new\s+year)\b",
    re.IGNORECASE,
)
_IS_AN_HOURS_QUESTION_RE = re.compile(
    r"\b(hour|hours|open|opens|opening|close|closes|closing|shut|"
    r"what\s+time|when\s+(do|does|are|is)\s+[^.?!]{0,20}\b(open|close))\b",
    re.IGNORECASE,
)


def temporary_notice_answer(message: str) -> "Optional[tuple[str, list[dict]]]":
    """Short-term, temporary or current-state questions -> the desk.

    HOURS ARE EXCLUDED, by the operator's explicit carve-out: they come live
    from LibCal, holiday and break hours included, and must keep that path.
    """
    m = message or ""
    if _IS_AN_HOURS_QUESTION_RE.search(m):
        return None
    if not (_TEMPORARY_RE.search(m)
            or (_HOLIDAY_NON_HOURS_RE.search(m) and "?" in m)):
        return None
    return (
        "That is the kind of thing that changes week to week, and I only know "
        "what was on the website when it was last indexed -- so I would rather "
        "not tell you something that was true a month ago.\n\n"
        f"The service desk has today's picture: **{KING_PHONE}**, or ask at the "
        "desk on the first floor of King.\n\n"
        "Library **hours** I can look up live, including over holidays and "
        "breaks -- just ask. And current events and exhibits are on the News & "
        "Events page [1].",
        [_cite(1, "https://www.lib.miamioh.edu/about/news-events/news/",
               "Miami University Libraries — News & Events")],
    )


# --- game night: the one event the operator DID hand over -------------------
#
# Operator, 2026-08-18: events go to the desk "except the page info I gave
# you" -- the games page. So this is the deliberate exception to the events
# exclusion, and it is worth being precise about which half is answerable.
#
# From libguides.lib.miamioh.edu/games-night in the live index, all DURABLE:
#   "Co-sponsored by MU Meeples! Come with a group or join a table when you
#    get here. All Miami University students, faculty, staff, and families are
#    welcome!" ... "Questions? librarygamesnights@miamioh.edu" ... "we have
#    created a pop-up game night kit! Host your own game night with a variety
#    of easy to play games, all in one convenient tub."
#
# What the page does NOT put in the indexed text is the SCHEDULE, which is
# exactly the date-bearing content the operator's navigator rule says we
# navigate to rather than repeat. So: say what it is and who it is for, and
# send them to the page for when.
GAMES_NIGHT_URL = "https://libguides.lib.miamioh.edu/games-night"
GAMES_NIGHT_EMAIL = "librarygamesnights@miamioh.edu"

_GAMES_RE = re.compile(
    r"\b(game\s*night|games\s*night|game\s*nights|board\s*game|"
    r"tabletop|meeples|game\s+kit)\b",
    re.IGNORECASE,
)


def games_night_answer(message: str) -> "Optional[tuple[str, list[dict]]]":
    """The games programme. Durable facts here, the schedule on the page."""
    m = message or ""
    if not _GAMES_RE.search(m):
        return None
    return (
        "**Library Game Nights** are board and tabletop game evenings at the "
        "library, co-sponsored by MU Meeples. **All Miami students, faculty, "
        "staff and families are welcome** -- come with a group or join a table "
        "when you arrive, and there are snacks [1].\n\n"
        "**For the dates, check the page** [1] -- the schedule changes and I "
        "would rather send you to the current one than quote an old date.\n\n"
        "There is also a **pop-up game night kit**: a tub of easy-to-play "
        "games you can borrow to host your own [1].\n\n"
        f"Questions about the programme go to {GAMES_NIGHT_EMAIL}.",
        [_cite(1, GAMES_NIGHT_URL,
               "Miami University Libraries — Library Game Nights")],
    )
