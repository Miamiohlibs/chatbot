"""Equipment, printing, software, building policies, events and jobs.

Two hard rules here. Printing prices and WiFi credentials are NEVER
quoted -- IT rotates them and a stale figure is a hallucination with a
citation, so the printing page carries them. And the equipment list is a
GENERAL list: only the lines that name a building belong to that
building.
"""
from base import *   # noqa: F401,F403

C = "tech"

# --- equipment ------------------------------------------------------------
g("rt_tech_laptop", "I need a laptop", "tech_checkout",
  "The Libraries lend laptops -- Chromebooks, 30-day loan -- from a library "
  "checkout desk with a university ID. It must NOT say Wertz Art & "
  "Architecture lends them: the equipment page attaches Art & Architecture "
  "to the iPads only, and everything else on that page is general.",
  library="king", urls=[TECH, TECHHUB], category=C,
  notes="Rated thumbs-down live 2026-09-11; the same session answered three "
        "questions running about Wertz until the student objected.")

g("rt_tech_ipad", "I need an ipad", "tech_checkout",
  "iPad Pros and Apple Pencils ARE at the Art & Architecture Library -- this "
  "is the one line on the equipment page that names a building, so naming "
  "Wertz here is correct.", library="king", urls=[TECH], category=C)

g("rt_tech_computer_checkout", "Can I check out a computer", "tech_checkout",
  "Yes -- laptops from a checkout desk with a university ID, per the "
  "equipment page.", library="king", urls=[TECH], category=C)

g("rt_tech_laptop_broken",
  "My laptop is broken. how long can I check one out", "tech_checkout",
  "The laptop loan period (30 days for Chromebooks). The broken laptop is "
  "context, not a complaint to be routed to a feedback form.",
  library="king", urls=[TECH], category=C,
  notes="Answered by the complaint short-circuit, which read 'broken' and "
        "missed the actual question.")

g("rt_tech_laptop_how_long",
  "how long can I keep my laptop that I borrowed from the library?",
  "tech_checkout",
  "The laptop loan period. If no campus was named, say which campus's rule "
  "it is -- equipment differs by location.",
  library="king", urls=[TECH], category=C)

g("rt_tech_camera", "how long can I keep a DSLR camera", "tech_checkout",
  "Cameras are 24-hour checkouts per the equipment page.",
  library="king", urls=[TECH], category=C)

g("rt_tech_headphones", "can i rent headphomes", "tech_checkout",
  "Headphones are on the equipment list; borrow with a university ID. A "
  "typo must not change the answer.", library="king", urls=[TECH], category=C)

g("rt_tech_charger_1", "can I borrow a phone charger", "tech_checkout",
  "YES -- the equipment page lists chargers for Mac, PC and assorted "
  "phones. A category summary that leaves the charger out fails the "
  "question.", library="king", urls=[TECH], category=C)

g("rt_tech_charger_2", "do you lend chargers", "tech_checkout",
  "Yes, chargers are lent; say so rather than refusing.",
  library="king", urls=[TECH], category=C)

g("rt_tech_charger_3", "do you lend phone chargers", "tech_checkout",
  "Yes -- chargers for Mac, PC and assorted phones.",
  library="king", urls=[TECH], category=C)

g("rt_tech_charger_4", "does the library have phone chargers", "tech_checkout",
  "Yes -- chargers are on the equipment list.",
  library="king", urls=[TECH], category=C)

g("rt_tech_charger_5", "Do you have a phone charger I can borrow?",
  "tech_checkout",
  "Yes -- chargers are lent from the checkout desk.",
  library="king", urls=[TECH], category=C)

g("rt_tech_usbc", "I need USB-c", "tech_checkout",
  "Cables and adaptors are on the equipment list; check at the desk for the "
  "specific connector.", library="king", urls=[TECH], category=C)

g("rt_tech_ham_equipment", "what services does Rentschler Library offer",
  "space_info",
  "Rentschler's OWN services, from the Hamilton site.",
  campus="hamilton", library="rentschler", urls=[HAM_SVC, HAM, HAM_EQUIP],
  category=C)

# --- printing, scanning, wifi --------------------------------------------
g("rt_print_cost", "how much is printing?", "printing_wifi",
  "Point at the Printing & WiFi page and let it carry the price. Quoting a "
  "per-page cost is forbidden -- it changes and cannot be verified.",
  library="king", urls=[PRINTING], category=C)

g("rt_print_free", "Is there free printing?", "printing_wifi",
  "Point at the Printing & WiFi page rather than asserting free or paid "
  "printing with a figure.", library="king", urls=[PRINTING], category=C)

g("rt_print_color", "can i print in color", "printing_wifi",
  "Colour printing exists; the Printing & WiFi page carries where and what "
  "it costs. No price in the answer.",
  library="king", urls=[PRINTING], category=C)

g("rt_print_where", "Where I can find the printer?", "printing_wifi",
  "Where printing is available in the building, via the Printing & WiFi "
  "page, or the service desk if the location is not published.",
  library="king", urls=[PRINTING, ASKUS], category=C)

g("rt_print_poster", "Can I print a poster at the library", "printing_wifi",
  "Large-format/poster printing: the Printing & WiFi page and/or the "
  "MakerSpace. No price.", library="king", urls=[PRINTING, MAKER], category=C)

g("rt_print_poster_help", "Can I get help making a poster?", "printing_wifi",
  "Where poster help lives -- the MakerSpace or the printing page -- and a "
  "person to ask.", library="king", urls=[PRINTING, MAKER, ASKUS], category=C)

g("rt_print_wifi_password", "print wifi password", "printing_wifi",
  "NEVER state a WiFi network name or password: point at the Printing & "
  "WiFi page and University IT.", library="king", urls=[PRINTING], category=C)

g("rt_print_scan_doc", "can I scan a document", "printing_wifi",
  "Yes -- the KIC scanners are free and email the PDF; the printing page "
  "has the details.", library="king", urls=[PRINTING, TECHHUB], category=C)

g("rt_print_scanner", "do u have a scanner", "printing_wifi",
  "Yes -- free KIC book scanners in King, plus scanning on the pay-for-print "
  "machines.", library="king", urls=[PRINTING, TECHHUB], category=C)

g("rt_print_scan_book",
  "I am looking to scan a book I've purchased into a PDF version. Is that "
  "doable with the scanner at the library?", "printing_wifi",
  "Yes -- the KIC book scanners do exactly this and email the PDF. "
  "Copyright limits are worth a sentence but must not become a refusal.",
  library="king", urls=[PRINTING, TECHHUB], category=C)

# --- software -------------------------------------------------------------
g("rt_soft_adobe_how", "How do I check out Adobe Creative Cloud?",
  "adobe_access",
  "Adobe Creative Cloud is a LICENCE you check out and install on your own "
  "device, from the software page; 'Reserve' is just the button wording and "
  "has nothing to do with course reserves.",
  urls=[SOFT_ALT, SOFTWARE, ADOBE], category=C)

g("rt_soft_adobe_get", "how to get Adobe", "adobe_access",
  "The same licence-checkout route on the software page.",
  urls=[SOFT_ALT, SOFTWARE, ADOBE], category=C)

g("rt_soft_adobe_need", "I need to check out adobe cloud", "adobe_access",
  "The licence-checkout route, student or faculty/staff link.",
  urls=[SOFT_ALT, SOFTWARE, ADOBE], category=C)

g("rt_soft_adobe_howlong", "How long can I check out adobe creative cloudbfor",
  "adobe_access",
  "How long the Adobe licence lasts, from the software page. A typo must "
  "not change the answer.", urls=[SOFT_ALT, SOFTWARE, ADOBE], category=C)

g("rt_soft_acrobat",
  "Am I remembering correctly that it's possible to \"check out\" Adobe "
  "Acrobat from the library", "adobe_access",
  "Yes -- Acrobat Pro comes with the Creative Cloud licence checkout.",
  urls=[SOFT_ALT, SOFTWARE, ADOBE], category=C)

g("rt_soft_photoshop_where", "Where can I use Adobe Photoshop?", "adobe_access",
  "Check out the Creative Cloud licence and install it on your own device; "
  "library computers also have it.",
  urls=[SOFT_ALT, SOFTWARE, ADOBE], category=C)

g("rt_soft_photoshop_computers", "Do computers have photoshop?", "adobe_access",
  "Adobe Creative Cloud on library computers, and the licence checkout for "
  "your own device.", urls=[SOFT_ALT, SOFTWARE, ADOBE, COMPUTERS], category=C)

g("rt_soft_word", "Do library computers have Microsoft Word", "software_access",
  "Yes -- Microsoft Office including Word is on library computers.",
  urls=[SOFTWARE, SOFT_ALT, COMPUTERS], category=C)

g("rt_soft_loan", "Do you loan software", "software_access",
  "Yes -- the software page covers what is licensed and how to check it "
  "out.", urls=[SOFTWARE, SOFT_ALT], category=C)

g("rt_soft_qgis", "Can I get QGIS loaded on a library computer?",
  "software_access",
  "What is installed is on the software page; a request for new software "
  "goes to the desk or IT. Do not promise an installation.",
  urls=[SOFTWARE, SOFT_ALT, ASKUS], category=C)

g("rt_soft_abbyy",
  "Hi librarians! I am trying to find an OCR software capable of scanning "
  "and translating Japanese. I heard that some institutions have access to "
  "ABBYY (https://pdf.abbyy.com/) so I was wondering if we have access to "
  "that through Miami. If not, do you have any other suggestions that are "
  "either free or available through the library?", "software_access",
  "Say plainly whether ABBYY is on the software list, and offer the KIC "
  "scanners' OCR plus Ask Us for a Japanese-capable alternative. Both halves "
  "were asked; do not answer only the scanning half.",
  urls=[SOFTWARE, SOFT_ALT, PRINTING, ASKUS], category=C)

# --- digitisation ---------------------------------------------------------
g("rt_av_cassette", "Do you have a way to digitize cassette tapes?",
  "av_production",
  "Whether audio digitisation is available -- the MakerSpace/media services "
  "or the desk. A flat refusal wastes a question with a real destination.",
  library="king", urls=[MAKER, ASKUS], category=C)

g("rt_av_vhs",
  "I have several vhs tapes from junior high and high school that I would "
  "like to convert to a digital format. Is that something I can do at King "
  "or pay to have someone do there? I just do not have a vhs player "
  "anymore. Thanks!", "av_production",
  "Whether VHS digitisation is possible at King, and who to ask. If we "
  "cannot confirm the equipment, say so and route to the desk rather than "
  "refusing outright.", library="king", urls=[MAKER, ASKUS], category=C)

# --- building policies ----------------------------------------------------
g("rt_pol_nap", "Can I take a nap at the library", "service_howto",
  "Sleeping is covered by the Libraries' building policies; point at the "
  "policies document.", library="king", urls=[POLICIES, ASKUS], category=C)

g("rt_pol_smoking", "is smoking allowed in the libraries", "service_howto",
  "Smoking/vaping is covered by the building policies; point at them.",
  library="king", urls=[POLICIES, ASKUS], category=C)

g("rt_pol_cat", "can I bring my cat to the library", "service_howto",
  "Pets and service animals are covered by the building policies; a service "
  "animal is treated differently from a pet.",
  library="king", urls=[POLICIES, ASKUS], category=C)

g("rt_pol_donate", "how do i donate books to the library", "service_howto",
  "The gifts policy and who to contact about a donation.",
  urls=[GIFTS, ASKUS], category=C)

g("rt_pol_stamps", "does the library sell postage stamps?", "service_howto",
  "Not a library service we can confirm: say so and point at the service "
  "desk rather than refusing as out of scope.",
  library="king", urls=[ASKUS], category=C)

g("rt_pol_passport", "can I get a passport photo taken at King?",
  "service_howto",
  "Not a service the Libraries publish: say so and suggest the service desk "
  "or the University. A scope refusal with no route is poor.",
  library="king", urls=[ASKUS], category=C)

# --- events and jobs ------------------------------------------------------
g("rt_ev_games_night", "when is library games night?", "events_news",
  "Explain what Library Game Nights are and point at the games-night page "
  "for current dates -- never quote a date, which goes stale.",
  urls=[GAMES, EVENTS], category=C)

g("rt_ev_game_night_2", "When is library game night?", "events_news",
  "Same: what it is, plus the page for dates.",
  urls=[GAMES, EVENTS], category=C)

g("rt_ev_game_night_dates",
  "hi. can you tell me the dates for library game nights this fall?",
  "events_news",
  "Point at the games-night page rather than listing dates; the schedule "
  "changes and a crawled date is a stale date.",
  urls=[GAMES, EVENTS], category=C)

g("rt_ev_upcoming_1", "any upcoming library events?", "events_news",
  "Events are deliberately out of the bot's knowledge because stale "
  "listings mislead: point at the News & Events page.",
  urls=[EVENTS], category=C)

g("rt_ev_upcoming_2", "What events are coming up at the library", "events_news",
  "Point at News & Events rather than listing anything.",
  urls=[EVENTS], category=C)

g("rt_ev_other_fall",
  "thanks. are there other events happening at the library this fall?",
  "events_news",
  "Point at News & Events.", urls=[EVENTS, GAMES], category=C)

g("rt_ev_map_my_classes",
  "is the library doing Map My Classes this year?", "events_news",
  "A named annual event: point at News & Events rather than confirming or "
  "denying this year's edition.", urls=[EVENTS], category=C)

g("rt_job_get_a_job", "How do I get a job at the library", "library_employment",
  "The Libraries' employment page, which links student, staff and faculty "
  "postings through Workday.", urls=[JOBS], category=C)

g("rt_job_jobs_at", "jobs at the libraries", "library_employment",
  "The employment page.", urls=[JOBS], category=C)

g("rt_job_careers", "Careers", "library_employment",
  "A single word, but an unmistakable one: the Libraries' employment page. "
  "A scope refusal is wrong when 'How do I get a job at the library' is "
  "answered.", urls=[JOBS], category=C,
  notes="Live 2026-09-09: refused as outside the bot's scope.")

# --- meta -----------------------------------------------------------------
g("rt_meta_greeting", "Hi", "human_handoff",
  "A friendly greeting plus what the bot can help with. Never a scope "
  "refusal.", urls=[ASKUS], category=C)

g("rt_meta_how_are_you", "hi how are you doing", "human_handoff",
  "A greeting with a pleasantry attached is still a greeting: greet and "
  "offer help.", urls=[ASKUS], category=C)

g("rt_meta_what_can_you_do", "what can you do for me", "human_handoff",
  "A short, honest capability summary -- hours, spaces, borrowing, finding "
  "things, naming a subject librarian -- and Ask Us for a person.",
  urls=[ASKUS], category=C)

g("rt_meta_website_broken",
  "why cant i find anything on this website", "website_feedback",
  "Offer the search routes and the website feedback form; acknowledge the "
  "frustration without arguing.", urls=[PRIMO, FEEDBACK, ASKUS], category=C)

g("rt_meta_doi_blank",
  "I'm trying to find a chapter with the DOI but the search keeps returning "
  "a blank screen. https://doi.org/10.4337/9781800375390.00022",
  "find_resource",
  "A broken-access report with a real destination: try Primo for the "
  "chapter, and Ask Us can chase the link. Do not refuse.",
  urls=[PRIMO, ASKUS, ILL], category=C)

g("rt_meta_ill_correction",
  "I need to correct a book title that I requested from ILL today: The "
  "title should be: Crossing the Wine Dark Sea.", "interlibrary_loan",
  "The bot cannot edit a submitted ILL request: route to ILL staff / Ask Us "
  "promptly, and say plainly that it cannot make the change itself.",
  urls=[ILL, ASKUS], category=C)

g("rt_meta_lola", "what is LOLA and how do I use it", "service_howto",
  "LOLA describes a short-term service whose page was never updated: send "
  "this to the service desk rather than describing it from a stale page.",
  urls=[LOLA, ASKUS], category=C)

g("rt_meta_grantforward", "Can you direct me to GrantFoward?", "databases",
  "GrantForward via Databases A-Z; the misspelling must not block it.",
  urls=[DBS, ASKUS], category=C)

g("rt_meta_vision_statements",
  "some assistance with books on \"vision statements\".", "find_resource",
  "A topic search: Primo, the databases list, and the Business liaison. Not "
  "an out-of-scope refusal.", urls=[PRIMO, DBS, LIAISONS], category=C)

g("rt_meta_steward_sustain",
  "tell me about the steward and sustain department", "staff_lookup",
  "A named internal department: describe it from the organisation pages if "
  "held, otherwise say so and point at the staff directory. Do not invent a "
  "remit.", urls=[STAFF, DEANS], category=C)

g("rt_meta_calculation2", "can I look for a book of calculation 2",
  "find_resource",
  "Almost certainly a Calculus II textbook: course reserves and Primo. Do "
  "not refuse over the phrasing.",
  urls=[RESERVES, RESERVES_S, PRIMO], category=C)
