"""Subject liaisons, named staff, and library leadership.

Naming the right person is the bot's single most-asked job after hours.
Every name here was read out of the Librarian/LibrarianSubject tables on
2026-09-16, so a rubric may require the name -- deflecting to the
directory when we hold the record is a failure, not a safe answer.

The cross-campus rule is the operator's from 2026-07-28: a liaison on
another campus is KEPT and LABELLED, never silently dropped and never
presented as though they sat on the asked campus.
"""
from base import *   # noqa: F401,F403

C = "people"

def liaison(id, q, subject, who, email, extra="", **kw):
    """`email` is taken and deliberately NOT written into the rubric.

    A gold row that spells out "boehmemv@miamioh.edu" duplicates the
    Librarian table, goes stale the day somebody's address changes, and --
    across enough rows -- makes the gold file look exactly like the
    spreadsheet-of-people that scan_for_pii.py exists to stop. CI blocked
    the push on 2026-09-23 for that reason and was right about the shape.

    The address is still checked, just not here: verify_gold.py matches
    every name in this file against the roster, and the bot reads the
    address from that same roster. The standard is the NAME.
    """
    g(id, q, "subject_librarian",
      f"Name {who} as the {subject} liaison, with the email and phone as "
      f"the staff directory gives them. Deflecting to the liaisons "
      f"directory without the name is wrong -- we hold the record. "
      f"{extra}".strip(),
      urls=[LIAISONS, GUIDES], category=C, **kw)

liaison("rt_lia_bio_my", "who is my biology subject librarian",
        "Biology", "Ginny Boehme", "boehmemv@miamioh.edu")
liaison("rt_lia_bio_short", "Who is the subject librarian for Bio?",
        "Biology", "Ginny Boehme", "boehmemv@miamioh.edu",
        "'Bio' is Biology; an abbreviation must resolve.")
liaison("rt_lia_chem", "who is my subject librarian for chemistry",
        "Chemistry and Biochemistry", "Kristen Adams", "adamsk3@miamioh.edu")
liaison("rt_lia_math", "Who is the subject librarian for Math",
        "Mathematics", "Roger Justus", "justusra@miamioh.edu",
        "Write the name without the middle initial.")
liaison("rt_lia_nursing", "Who is the subject librarian for Nursing?",
        "Nursing", "Ginny Boehme", "boehmemv@miamioh.edu")
# OPERATOR RULING 2026-09-17: "Rob Withers" is acceptable. We do not use
# middle names when we mention people, and whether "O'Brien Withers" is a
# double surname or a middle name is not worth failing an answer over. The
# email is the part that has to be right.
liaison("rt_lia_religion", "Who is the subject librarian for religion?",
        "Religion", "Rob Withers", "witherre@miamioh.edu",
        "\"Rob O'Brien Withers\" in full is equally correct -- either form "
        "passes, as long as the email is right.")
liaison("rt_lia_education", "Who is the education librarian?",
        "Education", "Abigail Morgan", "morgan55@miamioh.edu")
liaison("rt_lia_history", "Who is the best person to contact about history",
        "History", "Jenny Presnell", "presnejl@miamioh.edu")
liaison("rt_lia_music_name", "What is the name of the music librarian",
        "Music", "Barry Zaslow", "zaslowbj@miamioh.edu")
liaison("rt_lia_music_typo", "who is the music librarain",
        "Music", "Barry Zaslow", "zaslowbj@miamioh.edu",
        "A typo in 'librarian' must not change the answer.")
liaison("rt_lia_music_at_king", "How about music librarian at King?",
        "Music", "Barry Zaslow", "zaslowbj@miamioh.edu",
        "Phrased as a follow-up and naming a building; still a liaison "
        "lookup, NOT a question about job openings.")
liaison("rt_lia_psy215", "PSY 215",
        "Psychology", "Megan Jaskowiak", "jaskowma@miamioh.edu",
        "A bare course code is a liaison lookup: PSY maps to Psychology.")
liaison("rt_lia_bio271", "I am writing a BIO 271 paper I need hlep",
        "Biology", "Ginny Boehme", "boehmemv@miamioh.edu",
        "The course code carries the subject even through the typo.")
liaison("rt_lia_ai", "Who is the AI librarian?",
        "the Artificial Intelligence Center", "Anna Shaw",
        "shawar2@miamioh.edu")
liaison("rt_lia_ai_literacy", "I need to learn about AI literacy.",
        "the Artificial Intelligence Center", "Anna Shaw",
        "shawar2@miamioh.edu",
        "A research guide on AI literacy is an equally good destination if "
        "one is cited.")

# --- cross-campus liaison asks -------------------------------------------
g("rt_lia_hamilton_history", "who is the history librarian at Hamilton?",
  "subject_librarian",
  "History's liaison is Jenny Presnell, based at "
  "OXFORD. Name her AND say which campus she is on. Dropping her because "
  "Hamilton has no history liaison leaves the patron with nothing; "
  "presenting her as Hamilton's is the other error.",
  campus="hamilton", library="rentschler", urls=[LIAISONS, GUIDES, HAM],
  category=C)

g("rt_lia_hamilton_bio", "who is the biology librarian at the hamilton campus",
  "subject_librarian",
  "Biology's liaison is Ginny Boehme at Oxford; name "
  "her and label the campus.",
  campus="hamilton", library="rentschler", urls=[LIAISONS, GUIDES, HAM],
  category=C)

g("rt_lia_hamilton_edu", "who is the education librarian at the hamilton campus",
  "subject_librarian",
  "Education's liaison is Abigail Morgan at Oxford; "
  "name her and label the campus.",
  campus="hamilton", library="rentschler", urls=[LIAISONS, GUIDES, HAM],
  category=C)

g("rt_lia_hamilton_art", "who is the art librarian at the hamilton campus?",
  "subject_librarian",
  "Art's liaison is Stefanie Hilles at Oxford; "
  "Hamilton's Community Arts liaison is Krista McDonald "
  ". Either is right if the campus is labelled.",
  campus="hamilton", library="rentschler", urls=[LIAISONS, GUIDES, HAM],
  category=C)

g("rt_lia_middletown_nursing", "who is the nursing librarian at Middletown?",
  "subject_librarian",
  "Nursing's liaison is Ginny Boehme at Oxford. Name "
  "her and say she is at Oxford rather than refusing.",
  campus="middletown", library="gardner_harvey", urls=[LIAISONS, GUIDES, MID],
  category=C)

# --- "who is MY librarian" -- the clarify case ---------------------------
g("rt_lia_mine_bare", "who is my librarian?", "subject_librarian",
  "Liaisons are assigned by SUBJECT, not to individual students: ask which "
  "subject, major or course, and offer the liaisons directory. Naming "
  "somebody here would be a guess.",
  outcome="clarify", urls=[LIAISONS], category=C)

g("rt_lia_mine_personal", "how do I know who my personal librarian is?",
  "subject_librarian",
  "Same as the bare form: explain liaisons are by subject and ask for the "
  "subject or course.", outcome="clarify", urls=[LIAISONS], category=C)

g("rt_lia_mine_howfind", "How do I find my subject librarian", "subject_librarian",
  "Explain that liaisons are assigned by subject and ask for theirs, with "
  "the directory as the browse option.",
  outcome="clarify", urls=[LIAISONS], category=C)

g("rt_lia_appointment", "how do i make an appointment with a librarian",
  "research_consultation",
  "How to book a research consultation: the subject liaison's own booking or "
  "Ask Us. A named liaison is fine if a subject was inferable, but the "
  "mechanism is what was asked for.",
  urls=[LIAISONS, ASKUS, GUIDES], category=C)

# --- job titles, not subjects --------------------------------------------
g("rt_staff_webservices", "who is the web services librarian", "staff_lookup",
  "Jerry Yarnetsky and Ken Irwin both hold the title Web Services Librarian; "
  "name them with emails from the staff directory. Saying 'Miami has no "
  "subject librarian for Web Services' is wrong -- it is a job title, and "
  "they are in the roster.", urls=[STAFF], category=C,
  notes="A colleague's thumbs-down in August. The title lookup was wired on "
        "2026-08-31.")

g("rt_staff_webservices_plural", "who are the web services librarians?",
  "staff_lookup",
  "Name Jerry Yarnetsky and Ken Irwin, Web Services Librarians, with emails.",
  urls=[STAFF], category=C)

g("rt_staff_jerry", "Does Jerry Yarnetsky work here?", "staff_lookup",
  "Yes -- Jerry Yarnetsky, Web Services Librarian, with his email. A "
  "by-name question about a colleague must not be refused as out of scope.",
  urls=[STAFF], category=C)

g("rt_staff_tricia", "how do I contact Tricia Zeiser", "staff_lookup",
  "Tricia Zeiser's email (and phone if held) from the staff directory.",
  urls=[STAFF], category=C)

g("rt_staff_john_williams", "what is John Williams' email", "staff_lookup",
  "John Williams' email address from the staff directory, stated rather "
  "than deflected to the directory page.", urls=[STAFF], category=C)

g("rt_staff_candace", "who is Candace Pine", "staff_lookup",
  "Candace Pine's role and contact from the staff directory.",
  urls=[STAFF], category=C)

g("rt_staff_conley", "who is jerome conley", "staff_lookup",
  "Jerome Conley, Dean and University Librarian, with his email.",
  urls=[STAFF, DEANS], category=C)

g("rt_staff_dean", "Who is the dean of libraries?", "staff_lookup",
  "Jerome Conley, Dean and University Librarian, and the Dean's Office page.",
  urls=[DEANS, STAFF], category=C)

g("rt_staff_leads", "who leads the library", "staff_lookup",
  "Jerome Conley as Dean, or the Dean's Office page for the leadership team.",
  urls=[DEANS, STAFF], category=C)

g("rt_staff_incharge", "who is in charge of the library", "staff_lookup",
  "Jerome Conley, Dean and University Librarian, and/or the Dean's Office "
  "page.", urls=[DEANS, STAFF], category=C)

g("rt_staff_incharge_typo1", "who is in charge of the lirbary", "staff_lookup",
  "Same as the correctly spelled question -- Jerome Conley / the Dean's "
  "Office. A transposed r/b must not route this to a subject lookup, and "
  "the reply must never quote an internal search string back at the "
  "patron.", urls=[DEANS, STAFF], category=C,
  notes="Live 2026-08-27: 'Miami doesn't have a subject librarian listed "
        "for \"library administration leadership dean director\"'.")

g("rt_staff_incharge_typo2", "who is in change of the lirbary", "staff_lookup",
  "Two typos in one sentence, same answer: Jerome Conley / the Dean's "
  "Office.", urls=[DEANS, STAFF], category=C)

g("rt_staff_dean_salary", "How much does the dean get paid?", "staff_lookup",
  "Decline the salary -- public employee compensation goes through the "
  "University, not the Libraries -- then say who holds the role, which is "
  "public: Jerome Conley, Dean and University Librarian.",
  urls=[DEANS, STAFF], category=C)

# --- computer help: a service desk question, not a liaison one -----------
g("rt_staff_computer_help", "who can help with my computer?", "staff_lookup",
  "IT support, the library service desk, or Ask Us. It must NOT name a "
  "subject liaison as the person for a broken computer.",
  urls=[ASKUS, PRINTING], category=C,
  notes="The 'computer -> Roger Justus' failure: a liaison named for a "
        "hardware problem.")

g("rt_staff_laptop_help", "who can help with my laptop computer?", "staff_lookup",
  "IT support or the library service desk / Ask Us -- not a subject "
  "liaison.", urls=[ASKUS, TECH], category=C)

g("rt_staff_bloomberg", "Who can help me with bloomberg terminals",
  "staff_lookup",
  "The Business liaison or the Farmer School's Bloomberg support, or Ask Us "
  "if we cannot confirm who runs the terminals. Do not invent an owner.",
  urls=[LIAISONS, ASKUS], category=C)

g("rt_staff_bloomberg_2", "who can help with Bloomberg terminals?",
  "staff_lookup",
  "Same as the other phrasing: the Business liaison or Ask Us.",
  urls=[LIAISONS, ASKUS], category=C)

# --- research help --------------------------------------------------------
g("rt_res_writing_center",
  "If you are writing an essay or report, there is a place in King Library "
  "you can go to for help. What is the name of this place?",
  "research_consultation",
  "The Howe Writing Center, which King Library's own page lists among its "
  "venues. Answering with a subject liaison is wrong -- the question asks "
  "for the NAME OF A PLACE.", library="king", urls=[KING, ASKUS], category=C,
  notes="Rated thumbs-down. Two students asked variants of this the same "
        "day -- it reads like a class assignment.")

g("rt_res_writing_help",
  "Where do you go if you want help for writing an assignment like whats "
  "the name of it", "research_consultation",
  "The Howe Writing Center in King Library. Same question, looser wording.",
  library="king", urls=[KING, ASKUS], category=C)

g("rt_res_paper_help", "I am writing a paper I need help!",
  "research_consultation",
  "Offer the concrete routes -- a subject liaison consultation, Ask Us, the "
  "research guides -- and ask what the paper is about so a liaison can be "
  "named.", urls=[LIAISONS, ASKUS, GUIDES], category=C)

g("rt_res_peer_reviewed", "I need peer-reviewed articles on teen mental health",
  "databases",
  "How to limit a search to peer-reviewed work in Primo or a subject "
  "database, plus the relevant liaison. Do not claim to have run a search.",
  urls=[PRIMO, DBS, LIAISONS], category=C)

g("rt_res_contango",
  "I need to find articles on contango phenomenon in the oil and gas industry",
  "databases",
  "Point at Primo and the business/economics databases, and offer the "
  "Business liaison. Naming a specific article would be invention.",
  urls=[PRIMO, DBS, LIAISONS], category=C)

g("rt_res_cost_of_living",
  "I'm working on a personal finance paper and I'm trying to find the cost "
  "of living in Columbus Ohio in 2026, I've found a few sources that have "
  "relatively similar costs but they're still different nonetheless. Though "
  "all of them do say that the cost of living in Columbus is 7% less than "
  "the national average. What do you recommend I do?",
  "research_consultation",
  "A judgement question about conflicting sources: send them to the Business "
  "or Economics liaison for a consultation, and to Ask Us. The bot must not "
  "adjudicate which figure is right.",
  urls=[LIAISONS, ASKUS], category=C)

g("rt_res_stock_price",
  "I need the closing stock price of Proctor and Gamble on Sept 11 2001",
  "databases",
  "Historical share prices come from a subscribed financial database; point "
  "at Databases A-Z and the Business liaison. Do not state a price.",
  urls=[DBS, LIAISONS], category=C)

g("rt_res_digitize_music", "I need to digitize a piece of music",
  "av_production",
  "Digitisation options -- the MakerSpace / media services, or the Music "
  "liaison Barry Zaslow. A concrete route, not a refusal.",
  urls=[MAKER, LIAISONS], category=C)

g("rt_res_spss", "I need help with a formula in SPSS", "data_services",
  "SPSS support: the Data Services librarian, the software page, or Ask Us. "
  "Do not attempt the formula.", urls=[SOFTWARE, LIAISONS, ASKUS], category=C)

g("rt_res_dmp", "I need help with a DMP for a grant", "data_services",
  "Data management plan help: the Data Services librarian / Scholarly "
  "Commons, with a contact route.", urls=[SCHOLCOMM, LIAISONS], category=C)

g("rt_res_class_meeting", "can I schedule a library meeting for my class",
  "instruction_request",
  "Library instruction for a class: the subject liaison arranges it, or the "
  "instruction request route. Must not answer with room booking.",
  urls=[LIAISONS, ASKUS], category=C)

g("rt_res_ais_professor",
  "Professor wanting to talk with a librarian about using AIS",
  "instruction_request",
  "Route to the relevant subject liaison for a consultation, or Ask Us.",
  urls=[LIAISONS, ASKUS], category=C)

g("rt_res_film_guide", "is there a subject guide for film studies?",
  "research_consultation",
  "Yes -- point at the research guides for Film Studies and its liaison.",
  urls=[GUIDES, LIAISONS], category=C)

g("rt_res_film_guide_typo", "is there a subject quide for film studies?",
  "research_consultation",
  "Same as the correctly spelled question: the Film Studies guide and "
  "liaison.", urls=[GUIDES, LIAISONS], category=C)

g("rt_res_myguide", "is there a myguide", "research_consultation",
  "YES -- MyGuide is at lib.miamioh.edu/myguide, listed on the Libraries' "
  "own home page. Name it and link it; refusing is wrong.",
  urls=[MYGUIDE, GUIDES, LIAISONS], category=C)

g("rt_res_engineering_offices",
  "where is the  office of the engineering librarians", "location_directions",
  "Say we do not hold individual office locations, and hand over the "
  "liaisons directory plus the advice to email for a time. Must NOT give a "
  "building's street address as though it answered the question.",
  library="king", urls=[LIAISONS, STAFF], category=C,
  notes="Live 2026-09-07: answered with King's street address, cited, then "
        "admitted it had not covered the office location.")

g("rt_res_learn_ai", "how do i learn about ai?", "research_consultation",
  "Offer the AI-related research guide or the AI Center liaison Anna Shaw. "
  "A clarify menu of 'meeting a librarian' vs 'which database' is too "
  "abstract to choose between.",
  urls=[GUIDES, LIAISONS], category=C, notes="Rated thumbs-down live.")

g("rt_res_multi_subject_homework",
  "Even if you are an engineering major, you'll be taking other classes at "
  "Miami. There is a team of subject librarians to help in different "
  "disciplines.  Who would be best to contact for research help in the "
  "following areas?  Group of answer choices History  [ Choose ] Spainsh  "
  "[ Choose ] Biology  [ Choose ] English", "subject_librarian",
  "A pasted multiple-choice homework question naming four subjects. Either "
  "name the liaison for each (History: Jenny Presnell; Biology: Ginny "
  "Boehme; Spanish and English from the directory) or point at the "
  "directory. Any note about an unanswered part must appear ONCE.",
  urls=[LIAISONS, GUIDES], category=C,
  notes="Live 2026-09-09: the closing note read 'You also asked about You "
        "also asked about ...'. Fixed 2026-09-16.")
