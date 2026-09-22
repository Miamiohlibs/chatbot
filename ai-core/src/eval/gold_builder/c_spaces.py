"""Rooms, spaces, buildings and getting around them.

Two standing rulings govern this group. The operator's 2026-08-17 rule:
any building fact the WEBSITE does not publish goes to the service desk
rather than being answered from memory -- floors, restrooms, vending
machines. And the default-library rule: an unscoped question is about
King, and a service the evidence describes generally must not be pinned
to whichever building happens to be named nearby.
"""
from base import *   # noqa: F401,F403

C = "spaces"

# --- booking a room -------------------------------------------------------
g("rt_room_can_reserve", "can i reserve a study room", "room_booking",
  "Yes -- how to reserve, pointing at the room reservation system. A "
  "booking the bot can actually start is also acceptable.",
  library="king", urls=[ROOMS, LIBCAL], category=C)

g("rt_room_how_book", "how do i book a study room", "room_booking",
  "The room reservation route for King/Oxford.",
  library="king", urls=[ROOMS, LIBCAL], category=C)

g("rt_room_what_rooms", "what rooms do you even have", "room_booking",
  "What study spaces are bookable and where the list lives. Point at the "
  "reservation system rather than enumerating from memory.",
  library="king", urls=[ROOMS, LIBCAL], category=C)

g("rt_room_tomorrow_3pm", "I want to book a study room tomorrow 3pm to 4pm",
  "room_booking",
  "Start the booking flow for that slot -- ask for the missing details "
  "(name, email, which library) rather than deflecting to the website.",
  library="king", urls=[ROOMS, LIBCAL], category=C)

g("rt_room_tomorrow_short", "book a study room tomorrow 3pm to 4pm",
  "room_booking",
  "Same slot, terser: begin the booking rather than pointing at a page.",
  library="king", urls=[ROOMS, LIBCAL], category=C)

g("rt_room_tomorrow_generic", "book a room tomorrow 3pm to 4pm", "room_booking",
  "Begin the booking flow; 'a room' at Oxford means a King study room "
  "unless told otherwise.", library="king", urls=[ROOMS, LIBCAL], category=C)

g("rt_room_king_2pm", "i need a room tomorrow 2pm to 3pm at king",
  "room_booking",
  "Begin the booking flow for King for that slot.",
  library="king", urls=[ROOMS, LIBCAL], category=C)

g("rt_room_king103", "Is King 103 available tomorrow afternoon?", "room_booking",
  "Check availability for that specific room and window, or say how to. "
  "Naming a different room would be wrong.",
  library="king", urls=[ROOMS, LIBCAL], category=C)

g("rt_room_now", "book something for right now", "room_booking",
  "Begin a booking for the current slot, or say what is free now.",
  library="king", urls=[ROOMS, LIBCAL], category=C)

g("rt_room_how_far_ahead", "how far ahead can i book", "room_booking",
  "The booking window from the room reservation policy. If the number is "
  "not held, point at the reservation page rather than guessing.",
  library="king", urls=[ROOMS, LIBCAL], category=C)

g("rt_room_for_someone_else", "can i book for someone else", "room_booking",
  "Whether a booking can be made on another person's behalf, per the room "
  "policy.", library="king", urls=[ROOMS, LIBCAL], category=C)

g("rt_room_how_cancel", "how do i cancel", "room_booking",
  "How to cancel a reservation -- the confirmation email's cancel link or "
  "the reservation system.", library="king", urls=[ROOMS, LIBCAL], category=C)

g("rt_room_cancel_booking", "cancel my booking", "room_booking",
  "Explain how to cancel; the bot cannot cancel somebody's reservation for "
  "them without the booking details.",
  library="king", urls=[ROOMS, LIBCAL], category=C)

g("rt_room_gh_120",
  "can you book me room 120 at gardner-harvey on tuesday morning at 9am "
  "until 11am burkejj@miamioh.edu", "room_booking",
  "A complete Middletown booking request -- room, campus, day, window and "
  "email are all present. Either complete it or say exactly what is "
  "missing; a generic pointer is what earned this a thumbs-down.",
  campus="middletown", library="gardner_harvey",
  urls=[ROOMS, MID_LIBCAL, MID], category=C, notes="Rated thumbs-down.")

g("rt_room_gh_120_today",
  "Book me study room 120 at Gardner-Harvey today from 1pm to 2pm. My email "
  "is burkejj@miamioh.edu", "room_booking",
  "Same booking, today: complete it against Middletown's own spaces.",
  campus="middletown", library="gardner_harvey",
  urls=[ROOMS, MID_LIBCAL, MID], category=C)

# CORRECTED 2026-09-17. This row assumed Armstrong is not ours. The room
# reservations page says otherwise, verbatim: "our room reservation system
# allows you to reserve rooms in King, Art & Architecture Libraries, CIM
# studio rooms and Armstrong Student Center study rooms."
g("rt_room_armstrong", "can I reserve a study room at Armstrong?",
  "room_booking",
  "YES -- Armstrong Student Center study rooms are bookable through the "
  "Libraries' own reservation system, alongside King and Art & "
  "Architecture. Point at the reservation page.",
  library="king", urls=[ROOMS, LIBCAL], category=C)

g("rt_room_rentschler_groups", "are there group study rooms at Rentschler",
  "room_booking",
  "Rentschler's own study rooms and its own booking page -- not Oxford's.",
  campus="hamilton", library="rentschler",
  urls=[HAM_ROOMS, HAM_LIBCAL, HAM], category=C)

g("rt_room_all_campuses",
  "do all of the libraries have study rooms I can reserve?",
  "cross_campus_comparison",
  "An explicit comparison: say which campuses have bookable rooms and link "
  "each campus's own booking. Here enumerating IS the answer.",
  campus="oxford", urls=[ROOMS, LIBCAL, HAM_ROOMS, MID], category=C)

# --- quiet space, study space --------------------------------------------
g("rt_space_quiet_king", "where is a quiet place to study at King library?",
  "space_info",
  "King's quiet study space -- the Reading Rooms and designated quiet "
  "floors, from a cited page. If the floor is not published, the service "
  "desk is the right answer rather than a guessed floor.",
  library="king", urls=[READING, KING, ASKUS], category=C)

g("rt_space_quiet_generic", "where is the quiet study area", "space_info",
  "Quiet study at King, from a cited page, or the desk if the site does not "
  "publish it.", library="king", urls=[READING, KING, ASKUS], category=C)

g("rt_space_music_section", "Does King Library have a music section?",
  "space_info",
  "The Music Library has CLOSED and its collection moved into King, so yes "
  "-- King holds the music collection. Say that rather than describing an "
  "open Music Library.", library="king", urls=[MUSIC, KING], category=C)

g("rt_space_music_section_2", "do we have a music section in King", "space_info",
  "Same: the music collection is in King since the Music Library closed.",
  library="king", urls=[MUSIC, KING], category=C)

g("rt_space_music_where_1", "Where is the music library?", "space_info",
  "The Amos Music Library closed in 2023 and its collection is in King. Do "
  "not give directions to a closed building.",
  library="king", urls=[MUSIC, KING], category=C,
  notes="CORRECTED 2026-09-22: this row first called it the Amelia Hoover "
        "Music Library. There is no such library -- the name was "
        "invented, in a rubric written to stop the bot inventing "
        "things. scripts/verify_gold.py catches a proper noun that "
        "appears in no source we hold, and this was its first find.")

g("rt_space_music_where_2", "where is the music library", "space_info",
  "The Music Library is closed and its collection is in King.",
  library="king", urls=[MUSIC, KING], category=C)

g("rt_space_cafe", "is there a cafe in king library", "space_info",
  "King Cafe if a cited page names it; otherwise say the site does not "
  "confirm what is open in the building and send them to the service desk. "
  "A refusal with no route is poor, and inventing an espresso bar is worse.",
  library="king", urls=[KING, ASKUS], category=C)

g("rt_space_vending", "what's stocked in the king vending machine", "space_info",
  "Not published anywhere we can read: the service desk knows. This is the "
  "2026-08-17 ruling working correctly.",
  library="king", urls=[ASKUS], category=C)

g("rt_space_bathrooms_king", "where are the bathrooms in king",
  "location_directions",
  "Restroom floors are not on the Libraries' site, so the service desk is "
  "the answer -- a remembered floor number is exactly what the 2026-08-17 "
  "ruling forbids.", library="king", urls=[ASKUS], category=C,
  notes="Rated thumbs-down by a tester who wanted the floor. The ruling "
        "stands: an unsourced building fact goes to the desk.")

g("rt_space_bathrooms_bare", "Where are the bathrooms at", "location_directions",
  "Same: the service desk, not a guessed floor.",
  library="king", urls=[ASKUS], category=C)

g("rt_space_toilet_report", "There is a toilet running on the second floor",
  "website_feedback",
  "A REPORT, not a question: take it to the service desk / facilities. "
  "Answering with where the restrooms are misses it entirely.",
  library="king", urls=[ASKUS, FEEDBACK], category=C)

g("rt_space_accessible", "Is the library accessible?",
  "accessibility_services",
  "King Library's accessibility -- the accessibility page's provisions, "
  "and the desk for anything specific. It must NOT answer about Wertz Art "
  "& Architecture, which is not what was asked.",
  library="king", urls=[ACCESS, KING, ASKUS], category=C,
  notes="Live 2026-09-11: answered about Wertz three turns running until "
        "the student asked why.")

g("rt_space_king_accessible",
  "Why do you keep answering about the Art library? Is King library "
  "accessible", "accessibility_services",
  "Answer about KING's accessibility. A street address followed by 'I "
  "haven't addressed whether King has accommodations' is not an answer.",
  library="king", urls=[ACCESS, KING, ASKUS], category=C)

g("rt_space_gh_assistive",
  "Does the Gardner-Harvey Library have any assistive technology?",
  "accessibility_services",
  "Gardner-Harvey's own assistive technology, from the Middletown site.",
  campus="middletown", library="gardner_harvey",
  urls=[MID_ACCESS, MID], category=C)

g("rt_space_mid_computer_lab",
  "Is there a computer lab in the library at Middletown?", "space_info",
  "Middletown's own computing provision, from the Middletown library site.",
  campus="middletown", library="gardner_harvey",
  urls=[MID, MID_TEC], category=C)

# --- counting and naming the libraries ------------------------------------
g("rt_space_how_many", "How many libraries are there", "space_info",
  "Name the locations rather than asserting a count the sources disagree "
  "on: King and the Art & Architecture (Wertz) Library at Oxford, with "
  "Walter Havighurst Special Collections inside King, plus Rentschler at "
  "Hamilton and Gardner-Harvey at Middletown. A count and a list that "
  "contradict each other is the failure to avoid.",
  urls=[HOURS, KING, WERTZ, HAM, MID], category=C,
  notes="Live 2026-09-11: answered 'four Oxford-campus locations', then "
        "listed three and said the sources showed three.")

g("rt_space_four_names",
  "what are the four libraries on oxford's campus called?", "space_info",
  "List the Oxford locations we can source -- King, Art & Architecture "
  "(Wertz), and Walter Havighurst Special Collections within King. If that "
  "is three rather than four, say so plainly without narrating the "
  "evidence bundle ('the sources provided identify three...').",
  urls=[HOURS, KING, WERTZ, SPEC], category=C)

g("rt_space_named_after", "Who is the library named after", "space_info",
  "Edgar Weld King, a longtime library director and benefactor.",
  library="king", urls=[KING], category=C)

g("rt_space_when_built", "when was king built", "space_info",
  "King Library's building history from the King Library page -- the 1966 "
  "original wing, the 1970s addition, the 2007 renovation.",
  library="king", urls=[KING], category=C)

g("rt_space_when_built_2", "when did King Library built", "space_info",
  "Same history; broken grammar must not change the answer.",
  library="king", urls=[KING], category=C)

# CORRECTED 2026-09-17. This row first said BEST was "not one of the
# locations we hold hours for". It is: the corpus carries
# lib.miamioh.edu/about/locations/best-library, "B.E.S.T. Library is
# permanently closing in Laws Hall. Materials and staff are now located at
# King Library." The bot answered exactly that and the gold marked it
# wrong. Checking the corpus before trusting a rubric is the lesson.
g("rt_space_best_library", "What are the hours of BEST library?", "hours",
  "B.E.S.T. Library has permanently closed and its materials and staff "
  "moved to King Library -- say so rather than giving it hours. Do not "
  "answer with King's hours as though BEST were open.",
  urls=[HOURS, ASKUS, KING], category=C)

g("rt_space_gh_where", "where is gardner harvey library", "location_directions",
  "Gardner-Harvey Library is on the Middletown campus; give its page.",
  campus="middletown", library="gardner_harvey", urls=[MID, HOURS], category=C)

g("rt_space_gh_website", "what is the website for the middletown library?",
  "location_directions",
  "The Gardner-Harvey / Middletown library site.",
  campus="middletown", library="gardner_harvey", urls=[MID], category=C)

g("rt_space_gh_contact",
  "who should i contact for help at the gardner-harvey library?",
  "staff_lookup",
  "Gardner-Harvey's own contact route, from the Middletown site.",
  campus="middletown", library="gardner_harvey", urls=[MID, ASKUS], category=C)

g("rt_space_gh_close_today", "when does gardner harvey close today", "hours",
  "Today's closing time for Gardner-Harvey specifically.",
  campus="middletown", library="gardner_harvey", urls=[HOURS, MID], category=C)

g("rt_space_mid_sept12",
  "what are the hours for the middletown library on September 12?", "hours",
  "That date's hours for Gardner-Harvey if inside the live window, else the "
  "Middletown calendar.", campus="middletown", library="gardner_harvey",
  urls=[HOURS, MID_CAL, MID], category=C)

# CORRECTED 2026-09-22. This row said we hold no borrowing rule for SWORD.
# Its own page states one: "Items in the depository may be requested
# through catalogs of the cooperating libraries ... or through the OhioLINK
# catalog." That is the answer, and it was sitting in the corpus.
g("rt_space_sword_borrow",
  "can library affiliates borrow items held at SWORD?", "circulation_basic",
  "YES -- SWORD is the Southwest Ohio Regional Depository on the Middletown "
  "campus, and items in it are requested through the cooperating libraries' "
  "catalogues or through OhioLINK. Give that route rather than applying "
  "Oxford's shelf rules to a storage facility.",
  campus="middletown", urls=[SWORD, PRIMO, CIRC], category=C)

# --- MakerSpace as a place ------------------------------------------------
g("rt_ms_where", "wheres the makerspace", "location_directions",
  "The MakerSpace is on the third floor of King Library, room 303.",
  library="king", urls=[MAKER, MAKER_GUIDE], category=C)

g("rt_ms_phone", "what is the phone number for the maker space", "staff_lookup",
  "The MakerSpace's general phone and create@miamioh.edu.",
  library="king", urls=[MAKER, MAKER_STAFF], category=C)

g("rt_ms_contact", "how do i contact the makerspace", "staff_lookup",
  "create@miamioh.edu and the MakerSpace phone.",
  library="king", urls=[MAKER, MAKER_STAFF], category=C)

g("rt_ms_rentschler", "does Rentschler have a MakerSpace",
  "cross_campus_comparison",
  "The MakerSpace is King's. Say what Hamilton actually has rather than "
  "answering with King's as though it were Rentschler's.",
  campus="hamilton", library="rentschler",
  urls=[MAKER, HAM_EQUIP, MID_TEC], category=C)

# --- Special Collections --------------------------------------------------
g("rt_sc_where", "Where is Special Collections located?", "special_collections",
  "Walter Havighurst Special Collections & University Archives, third floor "
  "of King Library.", library="special", urls=[SPEC, SPEC_VISIT, KING],
  category=C)

g("rt_sc_info", "information about special collections", "special_collections",
  "What Special Collections holds and how to visit.",
  library="special", urls=[SPEC, SPEC_VISIT], category=C)

g("rt_sc_question", "I have a question about special collections",
  "special_collections",
  "Offer what Special Collections is and how to reach them, or ask what "
  "they need. Must not refuse.", library="special",
  urls=[SPEC, SPEC_VISIT, SPEC_STAFF], category=C)

g("rt_sc_learn_more", "Where may I learn more about Special Collections?",
  "special_collections",
  "The Special Collections site.", library="special",
  urls=[SPEC, SPEC_VISIT], category=C)

g("rt_sc_how_use", "how do I use special collections", "special_collections",
  "How access works -- drop-ins welcome during opening hours, and booking "
  "ahead means staff can retrieve materials. Do not say access is by "
  "appointment only.", library="special", urls=[SPEC, SPEC_VISIT], category=C)

g("rt_sc_reservation", "how to make reservation to special collections",
  "special_collections",
  "How to request materials or arrange a visit, from the visiting page.",
  library="special", urls=[SPEC, SPEC_VISIT], category=C)

g("rt_sc_dropins",
  "Do I need to make an appointment before visiting, or are drop-ins "
  "allowed?", "special_collections",
  "Drop-ins ARE allowed; booking ahead only means materials are ready when "
  "you arrive. Saying access is by appointment reads as a closed door.",
  library="special", urls=[SPEC, SPEC_VISIT], category=C,
  notes="Rated thumbs-down when answered as appointment-only.")

g("rt_sc_reading_room", "What can I bring into the Reading Room?",
  "special_collections",
  "The Reading Room rules from the visiting page -- what may be brought in, "
  "and the free lockers for everything else.",
  library="special", urls=[SPEC_VISIT, SPEC], category=C)

g("rt_sc_lockers",
  "in special collections, Free, secure lockers are provided to store your "
  "personal belongings.", "special_collections",
  "Confirm Special Collections' free patron lockers, which anyone may use. "
  "Must not answer with King's Faculty and Graduate Reading Room lockers, "
  "which are a different service with an eligibility rule.",
  library="special", urls=[SPEC_VISIT, READING], category=C)

g("rt_sc_other_collections",
  "What other collection are located in Special Collections?",
  "special_collections",
  "The named collections Special Collections holds, from its own site. Do "
  "not invent collection names.", library="special", urls=[SPEC], category=C)

g("rt_sc_volumes", "how many volumes does the speical collections hold",
  "special_collections",
  "A size figure only if a cited source gives one; otherwise say so and "
  "point at Special Collections. Do not produce a number from memory.",
  library="special", urls=[SPEC, ASKUS], category=C)

g("rt_sc_sanborn", "Sanborn fire maps Oxford Ohio", "special_collections",
  "Historical local maps are a Special Collections / University Archives "
  "question: route there.", library="special", urls=[SPEC, SPEC_STAFF],
  category=C)

g("rt_sc_event_contracts",
  "Where could I find records of past event contracts that Miami University "
  "has executed for the past 5 years?", "special_collections",
  "University administrative records: University Archives is the right "
  "destination, and public-records requests go through the University. A "
  "bare refusal wastes a question we can route.",
  library="special", urls=[SPEC, ASKUS], category=C)
