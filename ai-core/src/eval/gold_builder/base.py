"""Shared machinery for the real-traffic gold set.

Every row is a question a PERSON actually asked the bot between
2026-08-03 and 2026-09-16. Script traffic is excluded: a conversation was
treated as ours if it contained any question hard-coded in a repo script,
if it was one of six or more conversations opened within twenty seconds,
or if its turns were machine-paced. That left 363 distinct human
questions out of 3,202 messages.

expected_answer is a RUBRIC, not a transcript -- it says what a correct
reply has to contain, because the judge reads it as a standard rather
than matching text. allowed_urls is the strict half: anything cited that
is not on the list is scored wrong, so every URL here is one that exists
in the orchestrator's own constants or in content the bot has cited.
"""
import json

# --- the verified URL pool ------------------------------------------------
HOURS      = "https://www.lib.miamioh.edu/about/locations/hours/"
ASKUS      = "https://www.lib.miamioh.edu/research/research-support/ask/"
KING       = "https://www.lib.miamioh.edu/about/locations/king-library/"
WERTZ      = "https://www.lib.miamioh.edu/about/locations/art-arch/"
MUSIC      = "https://www.lib.miamioh.edu/about/locations/music-library"
LIAISONS   = "https://www.lib.miamioh.edu/about/organization/liaisons/"
STAFF      = "https://www.lib.miamioh.edu/about/organization/staff/"
DEANS      = "https://www.lib.miamioh.edu/about/organization/deans-office/"
GUIDES     = "https://www.lib.miamioh.edu/research/find/guides/"
DBS        = "https://libguides.lib.miamioh.edu/az/databases"
PRIMO      = ("https://ohiolink-mu.primo.exlibrisgroup.com/discovery/search"
              "?vid=01OHIOLINK_MU:MU")
MYACCOUNT  = ("https://ohiolink-mu.primo.exlibrisgroup.com/discovery/account"
              "?vid=01OHIOLINK_MU:MU&section=overview&lang=en")
ILL        = "https://www.lib.miamioh.edu/use/borrow/ill/"
CIRC       = "https://libguides.lib.miamioh.edu/mul-circulation-policies"
CIRC_OL    = ("https://libguides.lib.miamioh.edu/mul-circulation-policies/"
              "loan-periods-ohiolink-ill")
ROOMS      = "https://www.lib.miamioh.edu/use/spaces/room-reservations/"
LIBCAL     = "https://muohio.libcal.com/allspaces"
TECH       = "https://www.lib.miamioh.edu/use/technology/tech-checkout/"
PRINTING   = "https://www.lib.miamioh.edu/use/technology/printing/"
SOFTWARE   = "https://www.lib.miamioh.edu/use/technology/software/"
ADOBE      = "https://www.lib.miamioh.edu/adobe/"
MAKER      = "https://www.lib.miamioh.edu/use/spaces/makerspace/"
MAKER_GUIDE= "https://libguides.lib.miamioh.edu/create/makerspace"
MAKER_EQUIP= "https://muohio.libcal.com/reserve/equipment/makerspace"
SPEC       = "https://spec.lib.miamioh.edu/home/"
SPEC_VISIT = "https://spec.lib.miamioh.edu/home/visiting/"
SPEC_STAFF = "https://spec.lib.miamioh.edu/home/staff/"
RESERVES   = "https://libguides.lib.miamioh.edu/reserves-textbooks"
NEWSPAPERS = "https://libguides.lib.miamioh.edu/newspapers"
NEWS_OHIO  = "https://libguides.lib.miamioh.edu/newspapers/ohio"
NEWS_NYT   = "https://libguides.lib.miamioh.edu/newspapers/nyt"
NEWS_ARCH  = "https://libguides.lib.miamioh.edu/newspapers/Archives"
CITATION   = "https://libguides.lib.miamioh.edu/citation"
SCHOLCOMM  = "https://www.lib.miamioh.edu/research/creation/scholarly-commons/"
DIGITAL    = "https://www.lib.miamioh.edu/digital-collections/"
EVENTS     = "https://www.lib.miamioh.edu/about/news-events/news/"
GAMES      = "https://libguides.lib.miamioh.edu/games-night"
JOBS       = "https://www.lib.miamioh.edu/about/organization/employment/"
READING    = "https://www.lib.miamioh.edu/use/spaces/reading-rooms/"
FEEDBACK   = "https://www.lib.miamioh.edu/website-feedback/"
LOLA       = "https://www.lib.miamioh.edu/use/borrow/lola/"
SWORD      = "https://www.lib.miamioh.edu/about/locations/regional/sword/"
# Hamilton
HAM        = "https://www.ham.miamioh.edu/library/"
HAM_HOURS  = "https://www.ham.miamioh.edu/library/about/hours/"
HAM_STAFF  = "https://www.ham.miamioh.edu/library/about/rentschler-library-staff/"
HAM_SVC    = "https://www.ham.miamioh.edu/library/services/"
HAM_EQUIP  = "https://www.ham.miamioh.edu/library/services/equipment-you-can-borrow/"
HAM_ROOMS  = "https://www.ham.miamioh.edu/library/study-rooms/"
HAM_FAC    = "https://www.ham.miamioh.edu/library/services/for-faculty/"
# Middletown
MID        = "https://www.mid.miamioh.edu/library/"
MID_CAL    = "https://www.mid.miamioh.edu/library/calendar.htm"
MID_RES    = "https://www.mid.miamioh.edu/library/reserves.htm"
MID_TEXT   = "https://www.mid.miamioh.edu/library/textbookreserves.htm"
MID_TEC    = "https://libguides.lib.miamioh.edu/middletown_tec_lab/home"

HEADER = """\
// Gold set built from REAL TRAFFIC, 2026-08-03 to 2026-09-16.
//
// Every question below was typed by a person -- a patron, or a member of
// library staff testing the bot. Our own probe scripts are excluded: a
// conversation was treated as ours if it contained any question hard-coded
// in a repo script, if it was one of six or more conversations opened
// within twenty seconds, or if its turns were machine-paced. That removed
// 2,618 of 3,202 user messages and left 363 distinct human questions.
//
// 344 of those are here. The 19 that are not are listed at the bottom of
// this header: connectivity checks with no right answer, and turns that
// only mean something after the turn before them (a name and email handed
// to the booking flow, "what are they called?"). Those belong in
// src/eval/multiturn/, not in a single-turn gold set.
//
// Four rows are questions our probe runs also replayed, so the classifier
// put their conversations in the script bucket. They are plainly real
// questions -- a Slate subscription, an Inside Higher Ed paywall -- and
// they are kept.
//
// Two questions are reproduced with a personal detail REMOVED: a
// student's email address, and an alum's name, class year and telephone
// number that a staff member had pasted in. Both rows say so. This repo
// is public and neither belongs in it; staff emails, which are published
// on the liaisons directory, are kept.
//
// expected_answer is a RUBRIC, not a transcript: the judge reads it as the
// standard a reply has to meet. It says what the answer SHOULD be, which
// for roughly forty of these rows is NOT what the bot said at the time --
// where a reply was wrong, the note records what it did.
//
// allowed_urls is the strict half. Anything cited that is not on the list
// scores wrong, so every URL here comes from the orchestrator's own
// constants or from a page the bot has already cited in production.
//
// Deliberately excluded (19): hello this is a test / hi this is a staff
// test / hi this is from staff test / some test / this is a test / web
// test / nvm / nvm cancel it / ok go ahead and book it / three turns
// handing a name and email to the booking flow / My account is
// <redacted> / Thursday 8/13 at 1pm / I
// don't see anything there about Hamilton. / It's the King Library Crowd
// Index, on the front page of the library website / Free, secure lockers
// are provided to store your personal belongings. / What's in that space
// now? / what are they called?
"""

ROWS = []

# Destinations that are never a WRONG citation, whatever was asked. The
# first run scored 56 rows down on "some_invalid" citations, and the four
# commonest offenders were Ask Us, the liaisons directory, Databases A-Z
# and Primo -- the bot's general navigation, cited alongside a correct
# answer. allowed_urls is meant to catch a reply pointing somewhere it
# should not, not to punish "...and a librarian on Ask Us can help".
ALWAYS_OK = (ASKUS, LIAISONS, DBS, PRIMO, HOURS, GUIDES)


def g(id, question, intent, answer, *, campus="oxford", library=None,
      outcome="answer", urls=(), category="", notes=None, origin=None):
    """One gold row. `answer` is the rubric; "REFUSAL" for refusal rows."""
    row = {
        "id": id, "question": question, "intent": intent,
        "scope_campus": campus, "scope_library": library,
        "expected_answer": answer, "expected_outcome": outcome,
        "allowed_urls": sorted(set(urls) | set(ALWAYS_OK),
                               key=lambda u: (u not in urls, u)),
        "category": category,
    }
    if notes:
        row["notes"] = notes
    if origin:
        row["needs_session_origin"] = origin
    ROWS.append(row)
    return row

def emit(path):
    ids = [r["id"] for r in ROWS]
    dupe = {i for i in ids if ids.count(i) > 1}
    if dupe:
        raise SystemExit(f"duplicate ids: {sorted(dupe)}")
    qs = [r["question"].strip().lower() for r in ROWS]
    dq = {q for q in qs if qs.count(q) > 1}
    if dq:
        raise SystemExit(f"duplicate questions: {sorted(dq)[:5]}")
    with open(path, "w", encoding="utf-8") as f:
        f.write(HEADER)
        for r in ROWS:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"{len(ROWS)} rows -> {path}")

# --- additions verified against URLs the bot has actually cited ----------
CIRC_FINES = ("https://libguides.lib.miamioh.edu/mul-circulation-policies/"
              "loan-periods-fines")
CIRC_RECALL= ("https://libguides.lib.miamioh.edu/mul-circulation-policies/"
              "recall-request")
HOME_DELIV = "https://www.lib.miamioh.edu/use/borrow/home-delivery/"
RESERVES_S = "https://libguides.lib.miamioh.edu/reserves-textbooks/"
INSTRUCTION= "https://www.lib.miamioh.edu/research/instruction/library-instruction/"
RESEARCH   = "https://www.lib.miamioh.edu/research/"
COMPUTERS  = "https://www.lib.miamioh.edu/use/spaces/computer-labs/"
TECHHUB    = "https://www.lib.miamioh.edu/use/technology/"
ACCESS     = "https://www.lib.miamioh.edu/research/instruction/accessibility"
MID_ACCESS = "https://www.mid.miamioh.edu/library/accessibility.htm"
HAM_LIBCAL = "https://muohio.libcal.com/reserve/hamilton"
MID_LIBCAL = "https://muohio.libcal.com/reserve/middletown"
MAKER_STAFF= "https://libguides.lib.miamioh.edu/create/about-makerspace/staff"
SOFT_ALT   = "https://www.lib.miamioh.edu/software/"
POLICIES   = ("https://docs.google.com/document/d/"
              "1ZQdegDmo_8V7_aM8EMzpr57lQ5-kOj_jgtCqsbJ8_d4/edit?tab=t.0")
GIFTS      = "https://libguides.lib.miamioh.edu/additional-policies/gifts-policy"


# --- scope_library is what the RESOLVER should return, not where the
# --- answer happens to be about ------------------------------------------
#
# The existing gold leaves it None on 174 of 279 rows, and the resolver
# agrees: it sets a library only when the message NAMES one. "What are the
# hours today?" is about King, but nothing in those four words says King,
# so the right resolved scope is oxford/None and the default-library rule
# does the rest downstream. Asserting "king" there would score the
# resolver wrong for behaving correctly.
#
# So this is a lexical pass over the QUESTION -- did the patron name a
# building? -- applied after authoring, rather than a judgement smuggled
# into each row. It deliberately does not consult resolve_scope(), which
# would make every row pass by construction.
import re as _re

# Regional buildings FIRST: "does Rentschler have a MakerSpace" names
# Rentschler, and matching the sub-space word would hand it to King --
# which is the very conflation that question is asking about.
_NAMES_A_LIBRARY = (
    ("rentschler",     r"\brentschler\b|\bhamilton\s+(campus\s+)?librar"),
    ("gardner_harvey", r"\bgardner[- ]?harvey\b|\bmiddletown\s+(campus\s+)?librar"),
    ("sword",          r"\bsword\b"),
    ("special",        r"\bspecial collections?\b|\barchives\b|\bhavighurst\b"),
    ("wertz",          r"\bwertz\b|\bart\s*(&|and)?\s*arch|\barchitecture\b"
                       r"|\bart library\b|\bart and architecture\b"),
    # "the main library" at Oxford is King, and the resolver reads it that
    # way; so does anybody standing on campus.
    ("king",           r"\bking\b|\bmakerspace\b|\bmaker space\b"
                       r"|\bmain librar"),
)

# A question can NAME a building while being scoped somewhere else. "I am
# in Middletown and need a book that is in King Library" says King, but
# the person asking is at Middletown and that is whose options they need.
_SCOPED_ELSEWHERE = frozenset({"rt_bor_middletown_to_king"})

# Two questions the lexical pass reads wrong and a person does not.
# "Why do you keep answering about the Art library? Is King library
# accessible" names both buildings; the ASK is King and the Art library is
# the complaint. "a computer lab in the library at Middletown" puts the
# campus after the noun. Set by hand rather than by widening the patterns,
# because both are judgements about which building the person meant.
_LIBRARY_BY_HAND = {
    "rt_space_king_accessible": "king",
    "rt_space_mid_computer_lab": "gardner_harvey",
}

def _library_named_in(question: str):
    q = question.lower()
    for lib, pat in _NAMES_A_LIBRARY:
        if _re.search(pat, q):
            return lib
    return None


def apply_scope_library():
    """Blank scope_library wherever the question does not name a building,
    and correct it where it does."""
    changed = 0
    for r in ROWS:
        if r["id"] in _LIBRARY_BY_HAND:
            want = _LIBRARY_BY_HAND[r["id"]]
        else:
            want = (None if r["id"] in _SCOPED_ELSEWHERE
                    else _library_named_in(r["question"]))
        if r["scope_library"] != want:
            r["scope_library"] = want
            changed += 1
    return changed
