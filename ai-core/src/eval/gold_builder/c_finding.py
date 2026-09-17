"""Finding things: the catalogue, databases, newspapers, off-campus access.

The bot is a NAVIGATOR here, not a search engine. It does not run the
search and it does not assert what the collection contains: "search Primo,
and ILL if it isn't there" is the correct shape for an item request, and
"look it up in Databases A-Z" is the correct shape for a named database.
What it must NOT do is refuse -- an ownership question is a library
question however bare the phrasing.
"""
from base import *   # noqa: F401,F403

C = "finding"

def item(id, q, extra="", intent="find_resource", **kw):
    g(id, q, intent,
      "Point at Primo to search for it, and do not assert whether we own "
      "this particular item. Naming interlibrary loan as the fallback is "
      "a bonus, not a requirement -- on a topic search you look first and "
      f"request second. {extra}".strip(),
      urls=[PRIMO, ILL], category=C, **kw)

item("rt_find_totalitarianism_1", "I'm looking for a book about totalitarianism")
item("rt_find_totalitarianism_2", "where can I find books about totalitarianism?")
item("rt_find_totalitarianism_3", "where can i find books about totalitarianism")
item("rt_find_holocaust_ebook",
     "I'm looking for a book on the holocaust. it has to be an ebook",
     "The ebook filter in Primo is the specific part of the ask.")
item("rt_find_sociology_dummies",
     "do you have the book Sociology for Dummies? I need it for a class this "
     "fall.", "An ownership question -- never refuse it as out of scope.")
item("rt_find_my_textbook", "do you have my textbook",
     "Too vague to search: ask which course or title, or give the route.")
item("rt_find_bio116_book", "Do you have the book for BIO116?",
     "A course code: course reserves is the better first stop, then Primo.")
item("rt_find_bio116_textbook", "do you have the textbook for BIO116?",
     "Course reserves first, then Primo.")
item("rt_find_bus102", "I need a textbook for BUS 102",
     "Course reserves for BUS 102, then Primo.")
item("rt_find_a_book", "finding a book",
     "A bare topic: give the Primo route rather than refusing.")
item("rt_find_cyclospora_article",
     "I'm looking for a research article about cyclospora")
item("rt_find_cyclospora_title",
     "I’m looking for the article “Cyclospora cayetanensis infection "
     "in humans: biological characteristics, clinical features, epidemiology, "
     "detection method and treatment” but can’t get to it",
     "They have the title and cannot reach it: Primo, then ILL, and the "
     "off-campus sign-in route is worth mentioning.")
item("rt_find_codere_pdf",
     "Helen Codere Fighting with Property American Anthropologist 1950 I want "
     "to find this Article PDF",
     "A full citation: search Primo for the article, ILL if not held.")
item("rt_find_this_article", "I am looking for this article",
     "No title given: ask for it, or give the route.")
item("rt_find_request_access",
     "Good morning! There is an article I would like to read/access, and I "
     "was wondering if there is any way to request access through Miami?",
     "Yes -- Primo first, interlibrary loan if we do not hold it.")
item("rt_find_wah_citation",
     "Wah, M. (2016, July 4). How to build a high performing team using a "
     "social contract. Do you have this?",
     "A pasted citation with an explicit ownership question.")
item("rt_find_kearney_citation",
     "Kearney, R. (2015, August 3). How to build a social contract for your "
     "agile team",
     "A bare pasted citation is still an ownership question, not off-topic. "
     "Refusing it is wrong.")
item("rt_find_wah_bare",
     "Wah, M. (2016, July 4). How to build a high performing team using a "
     "social contract",
     "A bare pasted citation: give the Primo/ILL route rather than refusing.")
item("rt_find_appalachia_1",
     "I want to find articles on lasting effects in the appalachian communities",
     "A topic search: Primo and the subject databases, plus the liaison.")
item("rt_find_appalachia_2", "i need resources on effects in appalachia",
     "Same topic, terser: give the route.")
item("rt_find_air_pollution", "i need a research article about air pullution",
     "A topic with a typo: Primo, Databases A-Z, and the liaison.")
item("rt_find_bioinformatics", "I'm looking for information about bioinformatics",
     "A topic: point at Primo, the databases list and the relevant liaison.")
item("rt_find_ap_style_manual",
     "I have a student who needs some help wioth accessing a specific AP "
     "style manual",
     "Search Primo for the style manual; the citation guide is also a "
     "reasonable pointer.")
item("rt_find_mozart", "Mozart Piano Sonata No. 13, K331 sheet music",
     "Scores are in the catalogue: Primo, and the Music liaison Barry Zaslow "
     "for help finding editions.")

g("rt_find_journal_new_site", "this site has changed! How do I find a journal?",
  "find_resource",
  "How to find a journal on the current site -- Primo's journal search or "
  "Databases A-Z. Acknowledging the redesign is fine; the answer must be the "
  "route.", urls=[PRIMO, DBS, ASKUS], category=C)

g("rt_find_journal_confused",
  "Once again, this site has changed! How do I find a journal? I\"m so "
  "confused by the new format!", "find_resource",
  "Same as the calmer phrasing: the journal-finding route on the current "
  "site, plus Ask Us for a person. Must not answer with a clarify menu.",
  urls=[PRIMO, DBS, ASKUS], category=C)

g("rt_find_onesearch_404",
  "When I go to the OneSearch page it keeps saying 404 not found. I need to "
  "find resources and i have to use this source", "find_resource",
  "OneSearch has been replaced by the current catalogue: give the working "
  "Primo link, and Ask Us if the problem persists.",
  urls=[PRIMO, ASKUS], category=C)

g("rt_find_start_ai_articles",
  "where should i start searching for articles on artificial intelligence?",
  "databases",
  "A starting place: Primo, Databases A-Z, and the liaison for the subject.",
  urls=[PRIMO, DBS, LIAISONS], category=C)

# --- named databases ------------------------------------------------------
def db(id, q, name, **kw):
    g(id, q, "databases",
      f"Point at Databases A-Z as the place to look {name} up. That IS the "
      "answer to 'do we have X' and a refusal is wrong. Mentioning the "
      "Miami sign-in is helpful but not required, and asserting a "
      "subscription no source states is worse than omitting it.",
      urls=[DBS, ASKUS], category=C, **kw)

db("rt_db_jstor_1", "is JSTOR available", "JSTOR")
db("rt_db_jstor_2", "how can I access to JSTOR", "JSTOR")
db("rt_db_ebsco", "can i access EBSCO", "EBSCO")
db("rt_db_pubmed", "do you have PubMed", "PubMed")
db("rt_db_wos", "do we have access to Web of Science", "Web of Science")
db("rt_db_kanopy", "Is the film service Kanopy available through the library?",
   "Kanopy")
db("rt_db_mla",
   "Do we have institutional access to the MLA Directory of Periodicals? If "
   "so, how do I go about accessing it? I need to search the metrics of a "
   "few journals.", "the MLA Directory of Periodicals")
db("rt_db_where", "where can I find databases", "a database by name")
db("rt_db_random",
   "can I get into some random database nobody has heard of", "any database",
   notes="A joke phrasing with a real question inside it: the A-Z list "
         "answers it.")

g("rt_db_subscription_followup",
  "all the articles are subscription only. do you have a subscription?",
  "databases",
  "A paywall usually means arriving at the publisher from outside the "
  "Libraries' link: look the title up in Databases A-Z and follow it from "
  "there, signing in with Miami credentials. The generic 'search Primo for a "
  "book, article, journal or DVD' boilerplate does not answer this.",
  urls=[DBS, PRIMO, ASKUS], category=C,
  notes="Live 2026-09-16, straight after a Cincinnati Enquirer question. "
        "Miami does subscribe to the Enquirer (2010-present plus a "
        "historical archive), but the only chunk saying so is tagged "
        "campus=hamilton and the campus-scope rule suppresses it.")

g("rt_db_inside_higher_ed",
  "I appreciate that Miami has a subscription to the Chronicle of Higher Ed "
  "and the NYT. Since Inside Higher Ed has started charging, will we also "
  "get an online subscription to that for the university?", "databases",
  "A PURCHASE SUGGESTION, not a holdings question: whether the Libraries buy "
  "something is a collection decision, so route it to the subject librarian "
  "who selects in that area, or Ask Us. Do not promise or refuse a "
  "subscription.", urls=[LIAISONS, ASKUS], category=C)

g("rt_db_inside_higher_ed_short",
  "Since Inside Higher Ed has started charging, will we also get an online "
  "subscription?", "databases",
  "Same purchase-suggestion route: the selecting librarian, or Ask Us.",
  urls=[LIAISONS, ASKUS], category=C)

g("rt_db_slate", "Does the university have a subscription to Slate Magazine?",
  "newspapers",
  "Check the newspapers/periodicals guide and Primo for the title; either "
  "answers 'do we have it'.", urls=[NEWSPAPERS, PRIMO, DBS], category=C)

# --- newspapers -----------------------------------------------------------
g("rt_news_enquirer", "how can I get today's issue of the Cincinnati Enquirer?",
  "newspapers",
  "The Ohio Newspapers guide, which lists how to read each Ohio paper. "
  "Miami does subscribe to the Cincinnati Enquirer, so naming the database "
  "route is better than the guide alone.",
  urls=[NEWSPAPERS, NEWS_OHIO, DBS], category=C)

g("rt_news_dayton", "where can I find Dayton Daily News", "newspapers",
  "The Ohio Newspapers guide and how to reach that paper.",
  urls=[NEWSPAPERS, NEWS_OHIO], category=C)

g("rt_news_cincinnati_daily", "where to read Cincinnati Daily", "newspapers",
  "The Ohio Newspapers guide.", urls=[NEWSPAPERS, NEWS_OHIO], category=C)

g("rt_news_nyt", "how to get NYT", "newspapers",
  "Miami's New York Times access and how to activate it, from the "
  "newspapers guide.", urls=[NEWSPAPERS, NEWS_NYT], category=C)

g("rt_news_wsj_1973",
  "how can I get access to an article in Jun 17, 1973, from Wall street "
  "journal", "newspapers",
  "A historical WSJ article: the newspaper archives route in the newspapers "
  "guide, and ILL if the archive does not reach 1973.",
  urls=[NEWSPAPERS, NEWS_ARCH, ILL], category=C)

g("rt_news_db", "I need a database for newspapers", "newspapers",
  "The newspapers guide and/or Databases A-Z.",
  urls=[NEWSPAPERS, DBS], category=C)

g("rt_news_question", "I have a question about newspaper", "newspapers",
  "Offer the newspapers guide and ask what they need. Must not refuse.",
  urls=[NEWSPAPERS, ASKUS], category=C)

# --- off-campus / ebook access -------------------------------------------
# REDACTED. The patron typed their own Miami address into this one. The
# question is reproduced with it removed -- this repo is public, and a
# student's address is theirs, not ours. The shape of the question, which
# is what the row measures, is unchanged.
g("rt_remote_ebsco_vpn",
  "I am a remote MU student and I am logged into my "
  "MyMiami account, and on MU VPN, however I cannot access any articles on "
  "EBSCO", "remote_access",
  "Reach licensed content through the Libraries' own links rather than the "
  "vendor site, and hand this to Ask Us -- it is an account-specific access "
  "failure the bot cannot diagnose. Do not repeat the student's email back.",
  urls=[DBS, ASKUS], category=C)

g("rt_remote_ebook_download", "why can't i download an ebook", "remote_access",
  "Common reasons an ebook will not download -- simultaneous-user limits, "
  "and the reader software a download needs -- with the route to the "
  "platform.", urls=[DBS, ASKUS], category=C)

g("rt_remote_ebook_service", "What ebook service do you use?", "remote_access",
  "The ebook platform(s) the Libraries use and how to find ebooks in the "
  "catalogue.", urls=[DBS, PRIMO], category=C)

# --- citation -------------------------------------------------------------
g("rt_cite_apa", "how do I create a citation in apa style", "citation_help",
  "The citation guide, and that citation managers are supported. Do not "
  "hand-build a citation from nothing.", urls=[CITATION, ASKUS], category=C)

g("rt_cite_chatgpt",
  "how can I cite an AI like chatGPT in my paper, in APA style?",
  "citation_help",
  "The citation guide's AI/APA section if it exists, otherwise the guide "
  "plus Ask Us. Do not invent an APA template from memory.",
  urls=[CITATION, ASKUS], category=C)

g("rt_cite_factory_hub",
  "how do i cite  Factory and the Hub: An Anatomy of Canada's Import "
  "Dependence on the US", "citation_help",
  "Point at the citation guide and the style tools; do not compose the "
  "citation.", urls=[CITATION, ASKUS], category=C)
