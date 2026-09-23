"""Hours. The single largest category in real traffic (46 of 363).

Two rules run through all of it. Hours come LIVE from LibCal, so a gold
rubric asks for today's/the named day's status rather than a timetable.
And anything longer than the live window -- a term, a break, "normally" --
must point at the hours page instead of stating a schedule, because the
LibCal window only reaches a couple of weeks out.
"""
from base import *   # noqa: F401,F403

C = "hours"

g("rt_hours_today", "what are the hours today?", "hours",
  "Today's opening and closing time for King Library (the Oxford default), "
  "from live LibCal data, citing the hours page. Must not list the whole week.",
  library="king", urls=[HOURS], category=C)

g("rt_hours_bare", "what are the library hours", "hours",
  "Today's hours for King Library. A bare 'library hours' with no day means "
  "today, not a week-long table.", library="king", urls=[HOURS], category=C)

g("rt_hours_king_named", "what are king library hours", "hours",
  "Today's hours for King Library, cited to the hours page.",
  library="king", urls=[HOURS], category=C)

g("rt_hours_close_today", "what time does the library close today", "hours",
  "Today's closing time for King Library.", library="king",
  urls=[HOURS], category=C)

g("rt_hours_close_king_today", "what time does King Library close today", "hours",
  "Today's closing time for King Library.", library="king",
  urls=[HOURS], category=C)

g("rt_hours_when_close", "when do you close", "hours",
  "Today's closing time for King Library.", library="king",
  urls=[HOURS], category=C)

g("rt_hours_when_close_txt", "When do u close", "hours",
  "Today's closing time for King Library. Texting shorthand is the same "
  "question.", library="king", urls=[HOURS], category=C)

g("rt_hours_open_now", "is King open now?", "hours",
  "Whether King Library is open at this moment and, if so, when it closes "
  "today.", library="king", urls=[HOURS], category=C)

g("rt_hours_open_rn", "is the library open rn", "hours",
  "Whether King Library is open right now and when it closes today.",
  library="king", urls=[HOURS], category=C)

g("rt_hours_open_right_now", "is king library open right now", "hours",
  "Whether King Library is open right now and when it closes today.",
  library="king", urls=[HOURS], category=C)

g("rt_hours_still_open", "are you still open?", "hours",
  "Whether King Library is open at this moment and its closing time today.",
  library="king", urls=[HOURS], category=C)

g("rt_hours_how_late_king", "How late is King open?", "hours",
  "Tonight's closing time for King Library.", library="king",
  urls=[HOURS], category=C)

g("rt_hours_how_late_friday", "how late is king open friday", "hours",
  "Friday's closing time for King Library specifically -- the named day, "
  "not today and not the whole week.", library="king",
  urls=[HOURS], category=C)

g("rt_hours_when_open", "when does the library open?", "hours",
  "Today's opening time for King Library.", library="king",
  urls=[HOURS], category=C)

g("rt_hours_open_tuesday", "When does the library open on Tuesday?", "hours",
  "Tuesday's opening time for King Library, for the coming Tuesday.",
  library="king", urls=[HOURS], category=C)

g("rt_hours_main_close", "when does the main library close", "hours",
  "Today's closing time for King Library -- 'the main library' at Oxford is "
  "King.", library="king", urls=[HOURS], category=C)

g("rt_hours_saturday", "what are the library hours for Saturday?", "hours",
  "Saturday's hours for King Library.", library="king",
  urls=[HOURS], category=C)

g("rt_hours_open_sat_1", "Is King open on Saturday?", "hours",
  "Whether King Library is open this Saturday, with the times if it is.",
  library="king", urls=[HOURS], category=C)

g("rt_hours_open_sat_2", "are you open on Saturday", "hours",
  "Whether King Library is open this Saturday, with the times if it is.",
  library="king", urls=[HOURS], category=C)

g("rt_hours_open_sat_3", "is the library open on saturday", "hours",
  "Whether King Library is open this Saturday, with the times if it is.",
  library="king", urls=[HOURS], category=C)

g("rt_hours_named_date", "are you open on September 7?", "hours",
  "Open/closed status for that specific date if it falls inside the live "
  "window; otherwise the hours page. Must not answer about a different day.",
  library="king", urls=[HOURS], category=C)

g("rt_hours_labor_day_sunday",
  "Is there any facility on Miami’s campus that is open today on Sunday, "
  "September 6 Labor Day weekend to study?", "hours",
  "Must answer about SUNDAY SEPTEMBER 6 -- open or closed on the day asked "
  "about, not the next open day. If nothing is open that day, say so and "
  "point at the hours page rather than naming Monday's hours as though they "
  "answered the question.", library="king", urls=[HOURS], category=C,
  notes="Live 2026-09-06: answered 'King is open Monday 1pm-1am', which is "
        "true about a day nobody asked about. A walk to a locked building.")

g("rt_hours_labor_day_past", "Was the library open on labor day", "hours",
  "A past date outside the live window: say the hours page carries the "
  "schedule for that date. The wording must not describe a past day as "
  "'further out than I can look up'.", library="king",
  urls=[HOURS], category=C,
  notes="Live 2026-09-11: called a date four days earlier 'further out'.")

g("rt_hours_fall_break", "What are the hours for Fall Break", "hours",
  "A break schedule is longer than the live window: point at the hours "
  "page and do not state times.", library="king", urls=[HOURS], category=C)

g("rt_hours_fall_break_2", "is the library open during fall break", "hours",
  "Point at the hours page for the break schedule; do not assert times.",
  library="king", urls=[HOURS], category=C)

g("rt_hours_fall_break_typo", "is the library open during fall brea?", "hours",
  "Same as the correctly spelled question: point at the hours page. A typo "
  "must not change the answer.", library="king", urls=[HOURS], category=C)

g("rt_hours_normally_sundays", "is it normally open on Sundays?", "hours",
  "'Normally' asks for a standing pattern, which LibCal cannot give: point "
  "at the hours page rather than generalising from one week.",
  library="king", urls=[HOURS], category=C)

g("rt_hours_wertz", "what are Wertz hours", "hours",
  "Today's hours for the Wertz Art & Architecture Library specifically, not "
  "King's.", library="wertz", urls=[HOURS, WERTZ], category=C)

g("rt_hours_arch_library", "what are the hours for the Architecture library",
  "hours",
  "Today's hours for Wertz Art & Architecture Library -- 'the Architecture "
  "library' is Wertz.", library="wertz", urls=[HOURS, WERTZ], category=C)

g("rt_hours_art_close", "what time does the art library close", "hours",
  "Today's closing time for Wertz Art & Architecture Library.",
  library="wertz", urls=[HOURS, WERTZ], category=C)

g("rt_hours_art_next_monday", "when does Art library open next monday", "hours",
  "Next Monday's opening time for Wertz, if it is inside the live window; "
  "otherwise the hours page.", library="wertz", urls=[HOURS, WERTZ],
  category=C)

g("rt_hours_art_labor_monday", "when does Art library open labor day monday",
  "hours",
  "Labor Day's hours for Wertz. A university holiday often differs from the "
  "usual Monday, so either give that date's posted hours or point at the "
  "hours page -- never copy an ordinary Monday.",
  library="wertz", urls=[HOURS, WERTZ], category=C)

g("rt_hours_art_labor_weekend",
  "is the Art and Architecture library open on Labor Day weekend?", "hours",
  "A weekend is a stretch, not a day: give the posted hours for those dates "
  "if they are in the window, otherwise the hours page.",
  library="wertz", urls=[HOURS, WERTZ], category=C)

g("rt_hours_art_labor_day",
  "is the art arch library open on Labor Day?", "hours",
  "Wertz's hours on Labor Day itself, or the hours page. Must not answer "
  "about an ordinary Monday.", library="wertz", urls=[HOURS, WERTZ],
  category=C)

g("rt_hours_music_close", "when does music library close", "hours",
  "The Amos Music Library is CLOSED -- it shut in 2023. Say that rather "
  "than giving hours. Where the collection went is NOT something we can "
  "source, so 'moved to other Miami University Libraries' is right and "
  "naming a building would be an invention.", library="king",
  urls=[MUSIC, KING], category=C,
  notes="Closure, not a schedule. Giving hours for a closed library sends "
        "somebody to a locked door. "
        "CORRECTED 2026-09-23: this row demanded that the answer say the "
        "collection moved INTO KING. Nothing supports that -- not one "
        "chunk, not one doc. The pre-launch test of 2026-07 lists "
        "\"invents a location\" as the failure condition for this very "
        "question, and the vague answer the bot gives is the "
        "deliberate right one. Second time these music rows asserted "
        "something unsourced; the first was the library's name."
        "CORRECTED 2026-09-22: this row first called it the Amelia Hoover "
        "Music Library. There is no such library -- the name was "
        "invented, in a rubric written to stop the bot inventing "
        "things. scripts/verify_gold.py catches a proper noun that "
        "appears in no source we hold, and this was its first find.")

g("rt_hours_makerspace_close_today", "when does Makerspace close today", "hours",
  "Today's closing time for the King MakerSpace specifically, from LibCal -- "
  "the MakerSpace keeps its own hours, not King's.",
  library="king", urls=[HOURS, MAKER], category=C)

g("rt_hours_makerspace_sunday", "is the makerspace open on sunday", "hours",
  "The MakerSpace's posted Sunday hours from LibCal. Sunday is a day it is "
  "often open (12pm-4pm in a normal week), so 'closed weekends' is wrong as "
  "a standing claim.", library="king", urls=[HOURS, MAKER], category=C,
  notes="A librarian filed a rating-1 report on exactly this: 'The makerspace "
        "is open Sundays noon-4pm. The chatbot says it is closed on Sundays.'")

g("rt_hours_makerspace_appointment",
  "how do i make an appointment to use the makerspace?", "service_howto",
  "How to book MakerSpace time or equipment -- the MakerSpace page and its "
  "equipment booking, or the create@miamioh.edu contact. Not opening hours.",
  library="king", urls=[MAKER, MAKER_GUIDE, MAKER_EQUIP], category=C)

g("rt_hours_makerspace_printer_appt",
  "do I need to schedule an appointment to use a printer in the makerspace?",
  "makerspace_3d",
  "Whether MakerSpace 3D printing needs booking, pointing at the MakerSpace "
  "page or equipment booking. Must not answer about ordinary paper printing.",
  library="king", urls=[MAKER, MAKER_GUIDE, MAKER_EQUIP], category=C)

g("rt_hours_makerspace_class",
  "can I schedule a workshop for my class in the makerspace?",
  "instruction_request",
  "Name Sarah Nagle, Creation and Innovation Services Librarian, as the "
  "contact for bringing a class into the MakerSpace, with her phone or the "
  "general create@miamioh.edu. Must NOT answer with opening hours, and must "
  "not state a weekly schedule of its own.",
  library="king", urls=[MAKER_GUIDE, MAKER], category=C,
  notes="Kevin Messner rated the hours answer 2/5. The schedule sentence was "
        "removed from this answer on 2026-09-16.")

g("rt_hours_spec_bare", "special collections hours", "hours",
  "Walter Havighurst Special Collections' own hours from LibCal, plus the "
  "note that booking ahead lets staff retrieve materials. Drop-ins are "
  "welcome -- do not say access is by appointment only.",
  library="special", urls=[SPEC, SPEC_VISIT], category=C)

g("rt_hours_spec_when_visit", "when can I visit special collections?", "hours",
  "Special Collections' opening hours plus how to arrange a visit; drop-ins "
  "are welcome and booking ahead means materials are ready.",
  library="special", urls=[SPEC, SPEC_VISIT], category=C)

g("rt_hours_spec_who", "Who is allowed to use Special Collections?",
  "special_collections",
  "Special Collections is open to anyone -- not only Miami affiliates. This "
  "is an eligibility question, not an hours question.",
  library="special", urls=[SPEC, SPEC_VISIT], category=C)

g("rt_hours_operation", "When are your hours of operation?", "hours",
  "Today's hours for King Library. Asked in a Special Collections thread it "
  "may reasonably answer for Special Collections, but it must answer with "
  "hours rather than deflecting.", library="king", urls=[HOURS, SPEC],
  category=C, notes="Rated thumbs-down live.")

g("rt_hours_crowd_index", "Is the library busy", "space_info",
  "King Library's Crowd Index gives an approximate occupancy from wifi "
  "connections; point at the King Library page where it is shown. Do not "
  "claim a live headcount.", library="king", urls=[KING], category=C)

g("rt_hours_coffee_king", "Any place for coffee at king", "space_info",
  "King Cafe / the cafe in King Library, or an honest 'I can't confirm what "
  "is open in the building right now -- the service desk can tell you'. Must "
  "not invent an espresso bar or a floor for one.",
  library="king", urls=[KING, ASKUS], category=C,
  notes="The espresso-bar hallucination came from this shape: a nav menu "
        "item welded to an unrelated 'Ground Floor'.")
