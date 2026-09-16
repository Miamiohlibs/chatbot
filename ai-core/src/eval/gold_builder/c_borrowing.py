"""Borrowing, renewals, fines, reserves, OhioLINK and interlibrary loan.

The recurring hazard in this group is CARRYING A RULE ACROSS SERVICES.
OhioLINK, SearchOhio, interlibrary loan and Miami's own stacks each have
their own loan period, renewal limit and return rule, and they get
described in the same paragraph on the same page -- so a number stated
for one of them tells you nothing about the others. Several rubrics below
exist only to hold that line.
"""
from base import *   # noqa: F401,F403

C = "borrowing"

g("rt_bor_howmany", "how many books can I check out", "circulation_basic",
  "The checkout limit for Miami materials, stated rather than deflected.",
  urls=[CIRC, CIRC_FINES], category=C)

g("rt_bor_howmany_q", "How many books can I check out?", "circulation_basic",
  "The checkout limit for Miami materials.", urls=[CIRC, CIRC_FINES],
  category=C)

g("rt_bor_howmany_student", "how many books can I check out as a student?",
  "circulation_basic",
  "The student checkout limit specifically.", urls=[CIRC, CIRC_FINES],
  category=C)

g("rt_bor_grad_loan", "I'm a grad student. How long can I keep a book and "
  "can I renew?", "loan_policy",
  "Graduate students get a semester-long loan on Miami materials, and yes "
  "they can renew -- through MyAccount, with the limits on the circulation "
  "page. Both halves of the question must be answered.",
  urls=[CIRC, CIRC_FINES, MYACCOUNT], category=C)

g("rt_bor_staff_loan", "how long can I keep a book if I am a staff",
  "loan_policy",
  "The loan period for staff/other patrons on Miami materials (six weeks), "
  "distinguished from faculty's year.", urls=[CIRC, CIRC_FINES], category=C)

g("rt_bor_overdue", "How much are overdue books?", "loan_policy",
  "Overdue and replacement charges from the circulation policy page. If the "
  "exact figures are not held, point at the page rather than guess.",
  urls=[CIRC, CIRC_FINES], category=C)

g("rt_bor_lost", "what do i do if i lost a book", "circulation_basic",
  "What to do about a lost item: contact circulation, and the replacement "
  "charge is on the policy page.", urls=[CIRC, CIRC_FINES, ASKUS], category=C)

g("rt_bor_renew_1", "how do i renew a book", "renewal",
  "Renew through MyAccount; renewal limits differ between Miami materials "
  "and OhioLINK/ILL items, and the circulation desk can help at the limit.",
  urls=[CIRC, CIRC_FINES, CIRC_OL, MYACCOUNT], category=C)

g("rt_bor_renew_2", "how do I renew a book?", "renewal",
  "Renew through MyAccount, with the two-path caveat about Miami vs "
  "OhioLINK/ILL items.", urls=[CIRC, CIRC_FINES, CIRC_OL, MYACCOUNT],
  category=C)

g("rt_bor_renew_3", "how do i renew my books", "renewal",
  "Renew through MyAccount, with the two-path caveat.",
  urls=[CIRC, CIRC_FINES, CIRC_OL, MYACCOUNT], category=C)

g("rt_bor_renew_count", "how many times can I renew my book?", "renewal",
  "The renewal limit, and that it DIFFERS by where the item came from -- "
  "Miami materials on the circulation page, OhioLINK/SearchOhio/ILL on "
  "their own page. One number for everything is wrong.",
  urls=[CIRC, CIRC_FINES, CIRC_OL, MYACCOUNT], category=C)

g("rt_bor_renew_howlong", "how long do i get to renew my book for", "renewal",
  "How long a renewal runs, split the same way: Miami materials versus "
  "OhioLINK/ILL.", urls=[CIRC, CIRC_FINES, CIRC_OL, MYACCOUNT], category=C)

g("rt_bor_renew_ohiolink",
  "I need to renew a book I have checked out from OhioLink", "renewal",
  "OhioLINK renewals specifically -- through MyAccount, up to the OhioLINK "
  "limit, and NOT the Miami-materials number. This must not open with the "
  "research-consultation banner: it is pure logistics.",
  urls=[CIRC_OL, MYACCOUNT], category=C,
  notes="Kevin Messner quoted the banner on this exact question.")

g("rt_bor_return_mail", "I've gone home for the summer. Can I return books "
  "by mail", "circulation_basic",
  "Whether items can be returned by post, and how -- the home delivery / "
  "return route, or contacting circulation. Do not state a mailing address "
  "that is not in a cited source.",
  urls=[HOME_DELIV, CIRC, ASKUS], category=C)

g("rt_bor_mailing_address", "What is the mailing address for the library",
  "location_directions",
  "The Libraries' mailing address if it is in a cited source; otherwise send "
  "them to the service desk rather than guessing. King's street address is "
  "acceptable only if the source gives it as the mailing address.",
  library="king", urls=[KING, ASKUS], category=C)

g("rt_bor_hold_no_news",
  "I placed a hold on a book but haven't heard anything about it since.",
  "circulation_basic",
  "Check MyAccount for the hold's status and contact circulation -- an "
  "account-specific question the bot cannot look up itself.",
  urls=[MYACCOUNT, ASKUS], category=C)

g("rt_bor_ebook_isbn",
  "In what way can I borrow the eBook ISBN (9781452973418) - Reclaiming the "
  "Road, 2025? Thank you", "find_resource",
  "Search Primo for the title; if Miami does not hold it, request it through "
  "interlibrary loan. Do not claim we hold or do not hold this specific "
  "ISBN.", urls=[PRIMO, ILL], category=C)

g("rt_bor_which_campus_has_it",
  "how can i tell which campus has a particular book that the libraries own?",
  "find_resource",
  "Primo shows the holding location per copy; explain reading the location "
  "in the record, and that items can be requested between campuses.",
  urls=[PRIMO, CIRC], category=C)

g("rt_bor_middletown_to_king",
  "If I am located in Middletown, and I need a book that is in King Library, "
  "what are my options for getting that book?", "circulation_basic",
  "Request the item through Primo for pickup at Gardner-Harvey, or travel to "
  "Oxford. The mechanism for moving a Miami item between campuses is what is "
  "being asked for.", campus="middletown", library="gardner_harvey",
  urls=[PRIMO, CIRC, MID], category=C)

# --- OhioLINK vs ILL: the distinction that keeps collapsing --------------
g("rt_ill_what_is_ill", "what is ill", "interlibrary_loan",
  "Interlibrary Loan gets material Miami and OhioLINK partners do not own, "
  "requested through the ILL form. Distinct from OhioLINK.",
  urls=[ILL, CIRC_OL], category=C)

g("rt_ill_what_is_ohiolink", "what is ohiolink", "interlibrary_loan",
  "OhioLINK is the shared Ohio catalogue, requested through Miami's own "
  "catalogue, with its own loan and renewal rules. Distinct from ILL.",
  urls=[PRIMO, CIRC_OL], category=C)

g("rt_ill_difference",
  "what's the difference between OhioLINK and interlibrary loan",
  "interlibrary_loan",
  "OhioLINK is the Ohio consortium borrowed through our catalogue; ILL "
  "reaches beyond it through a separate form. Different forms, different "
  "turnaround, different loan rules -- the answer must keep them apart.",
  urls=[PRIMO, ILL, CIRC_OL], category=C)

g("rt_ill_have_question", "I have a question about ill", "interlibrary_loan",
  "Explain ILL briefly and offer the form and Ask Us; or ask what they need. "
  "Must not answer about OhioLINK.", urls=[ILL, ASKUS], category=C)

g("rt_ill_have_question_full", "I have a question about interlibrary loan",
  "interlibrary_loan",
  "Same as the abbreviation: ILL, its form, and Ask Us.",
  urls=[ILL, ASKUS], category=C)

g("rt_ill_bare", "Ill", "interlibrary_loan",
  "Three letters that are almost certainly ILL: give the interlibrary loan "
  "pointer, or ask which they meant. Either is acceptable; a scope refusal "
  "is not.", outcome="clarify", urls=[ILL, ASKUS], category=C)

g("rt_ill_turnaround", "how long does an ILL request take", "interlibrary_loan",
  "ILL's own turnaround (some items three weeks or more), NOT the home "
  "delivery page's day counts and NOT OhioLINK's.",
  urls=[ILL, CIRC_OL], category=C,
  notes="This was answered with HOME DELIVERY day counts -- real numbers for "
        "a different service.")

g("rt_ill_ohiolink_turnaround", "how long does OhioLINK take",
  "interlibrary_loan",
  "OhioLINK's delivery time specifically, kept apart from ILL's.",
  urls=[CIRC_OL, PRIMO], category=C)

g("rt_ill_when_arrive", "When will my OhioLINK request arrive?",
  "interlibrary_loan",
  "Typical OhioLINK delivery time plus MyAccount to check this particular "
  "request -- the bot cannot see the patron's account.",
  urls=[CIRC_OL, MYACCOUNT], category=C)

g("rt_ill_when_arrive_2", "when will my ohiolink request arrive",
  "interlibrary_loan",
  "Typical OhioLINK delivery time plus MyAccount for the specific request.",
  urls=[CIRC_OL, MYACCOUNT], category=C)

g("rt_ill_arrived_yet", "Has my interlibrary loan request arrived yet",
  "interlibrary_loan",
  "The bot cannot see an individual account: point at MyAccount / the ILL "
  "system and offer the desk. Do not invent a status.",
  urls=[MYACCOUNT, ILL], category=C)

g("rt_ill_ohiolink_loan_length",
  "how long can i check out a book from ohiolink?", "loan_policy",
  "OhioLINK's loan period from the OhioLINK & ILL page -- not Miami's "
  "six-week undergraduate loan.", urls=[CIRC_OL, MYACCOUNT], category=C)

g("rt_ill_request_ohiolink", "how do I request a book from OhioLINK",
  "interlibrary_loan",
  "Request through Miami's own catalogue (Primo), which now carries OhioLINK "
  "-- NOT the interlibrary loan form, which is a different service.",
  urls=[PRIMO, CIRC_OL], category=C,
  notes="Circulation reported these two being conflated.")

g("rt_ill_get_copy_ohiolink", "how do I get a copy of a book from Ohiolink?",
  "interlibrary_loan",
  "Request it through the catalogue; ILL is the fallback when OhioLINK does "
  "not hold it.", urls=[PRIMO, CIRC_OL, ILL], category=C)

g("rt_ill_return_where", "where do i return an interlibrary loan book",
  "interlibrary_loan",
  "ILL items go back to the library that lent them to you -- the desk or "
  "bookdrop at the Miami library you borrowed from. Must not say 'any Miami "
  "University library' if the policy page does not.",
  urls=[ILL, CIRC_OL], category=C,
  notes="A wrong answer here costs the patron money.")

g("rt_ill_return_circ_desk",
  "do I return an interlibrary loan book to the circulation desk?",
  "interlibrary_loan",
  "Confirm the return route for ILL items from the policy page rather than "
  "generalising.", urls=[ILL, CIRC_OL], category=C)

g("rt_ill_denied",
  "I requested some materials from ILL, and the requests were denied. Do you "
  "know why that would happen?", "interlibrary_loan",
  "Common reasons a request is declined, and route them to ILL staff / Ask "
  "Us for their specific requests. Do not assert why these were denied.",
  urls=[ILL, ASKUS], category=C)

g("rt_ill_searchohio_up",
  "Hello, I'm wondering if Search Ohio and Ohio LInk are up and running/? "
  "I'm not seeing a way to search them right now on the Miami Library site...",
  "interlibrary_loan",
  "OhioLINK and SearchOhio are now searched from inside Miami's own "
  "catalogue rather than as separate catalogues -- that is why the old "
  "search box is gone. Point at Primo.", urls=[PRIMO, CIRC_OL], category=C)

g("rt_ill_no_physical_offer",
  "Hi -- I'm trying to  request a bunch of CDs from Ohiolink, and I keep "
  "getting a message that is \"no physical offer\" for the items. Is there a "
  "way that i can at least see what libraries the items are held at? Here's "
  "an example link: https://ohiolink-mu.primo.exlibrisgroup.com/permalink/"
  "01OHIOLINK_MU/1fsas8e/cdi_globaltitleindex_catalog_493521336",
  "interlibrary_loan",
  "A specific catalogue-record diagnosis the bot cannot make: hand this to "
  "Ask Us or ILL staff cleanly. A generic paragraph about OhioLINK being "
  "integrated into the catalogue, followed by 'I haven't covered whether "
  "holdings can be displayed', answers neither of the two things asked.",
  urls=[ASKUS, ILL], category=C,
  notes="Live 2026-09-12, from someone who had clearly already tried.")

g("rt_ill_oglobo",
  "\"\tI need to access O Globo's digital archive "
  "(https://oglobo.globo.com/acervo/resultado/) to find an image. Does Miami "
  "have any way to access it? If not, can I use interlibrary loan if I only "
  "need a photo or a scan of an image from a 2001 issue?\"",
  "interlibrary_loan",
  "Both halves: check the newspapers guide / Databases A-Z for O Globo, and "
  "yes, ILL can supply a scan of a single item. Offer Ask Us for the "
  "specific archive.", urls=[NEWSPAPERS, DBS, ILL, ASKUS], category=C)

# --- course reserves ------------------------------------------------------
g("rt_res_textbooks_reserve", "does the library have textbooks on reserve",
  "course_reserves",
  "Yes -- course reserves, with the Reserves & Textbooks guide and how to "
  "look a course up.", urls=[RESERVES, RESERVES_S], category=C)

g("rt_res_put_on_reserve", "How do I put a book on reserve", "course_reserves",
  "Instructors submit reserves themselves through the Libraries' process; "
  "point at the instructor instructions and the circulation desk. The bot "
  "cannot place the item.", urls=[RESERVES, RESERVES_S, ASKUS], category=C)

g("rt_res_chm141", "Do you have the book for CHM141?", "course_reserves",
  "A course-code question: check course reserves for CHM 141 and search "
  "Primo for the title. Do not assert whether that specific textbook is "
  "held.", urls=[RESERVES, RESERVES_S, PRIMO], category=C)

g("rt_res_hamilton_reserves",
  "does the Hamilton library have textbooks on reserve", "course_reserves",
  "Rentschler's OWN reserves -- each regional campus buys textbooks for its "
  "own courses, so an Oxford answer repeated word for word is wrong.",
  campus="hamilton", library="rentschler",
  urls=[HAM, HAM_SVC, RESERVES, RESERVES_S], category=C,
  notes="Measured 2026-08-18: Hamilton and Oxford returned identical text.")

g("rt_res_hamilton_textbooks",
  "hello! how can I find information on textbooks in the Hamilton campus "
  "library?", "course_reserves",
  "Rentschler Library's own textbook/reserves information, on the Hamilton "
  "site. A generic Oxford reserves pointer is what earned this a "
  "thumbs-down.", campus="hamilton", library="rentschler",
  urls=[HAM, HAM_SVC, RESERVES_S], category=C, notes="Rated thumbs-down.")
