"""Guides indexed as pointers.

A student asked "is there a subject guide for film studies?" at 02:32 on
2026-08-25 and was told the question was outside what a library chatbot
covers. Miami has research guides; we hold 480 of them, their URLs and the
subjects they serve in Postgres, and none of it was reachable from a
question. The crawl cannot supply it -- the A-Z index renders in JavaScript
and yields two links, neither of them a guide.
"""

from scripts.etl import libguides


def test_a_guide_with_a_subject_becomes_a_pointer() -> None:
    body = libguides.build_body(
        "Classics", "https://libguides.lib.miamioh.edu/c.php?g=22079",
        "", ["Classical Studies", "Greek", "Latin"])
    assert body is not None
    assert "Classics" in body
    assert "Classical Studies, Greek, Latin" in body, (
        "the subjects are how a student's word reaches the guide")
    assert "c.php?g=22079" in body


def test_the_pointer_does_not_pretend_to_be_the_guide() -> None:
    """Operator framing 2026-08-12: the bot navigates, it does not answer.

    A guide's content is a librarian's working document -- reading lists,
    database picks, notes for this term. Indexed as fact it serves last
    term's advice; indexed as a pointer it sends the student to read the
    current one.
    """
    body = libguides.build_body(
        "Music", "https://libguides.lib.miamioh.edu/c.php?g=22067", "",
        ["Music Theory"])
    assert "https://libguides.lib.miamioh.edu/c.php?g=22067" in body
    assert "anything with a date on it are on the guide itself" in body


def test_a_guide_naming_a_term_is_refused() -> None:
    """A dated TITLE dates the pointer, which is the thing pointers avoid."""
    assert libguides.build_body(
        "HST 111 Fall 2026", "https://libguides.lib.miamioh.edu/c.php?g=1",
        "", ["History"]) is None
    assert libguides.build_body(
        "Workshop Series 2026", "https://libguides.lib.miamioh.edu/c.php?g=2",
        "", ["History"]) is None


def test_a_guide_no_subject_reaches_is_left_out() -> None:
    """Course guides are named for a section that will not exist next year.

    "CJS 271" and "EGS 215: Workplace Writing (Cotugno)" are asked for by
    course code, which the subject route does not serve, and handing over
    last year's section is worse than saying nothing.
    """
    assert libguides.build_body(
        "CJS 271", "https://libguides.lib.miamioh.edu/c.php?g=1485575",
        "", []) is None


def test_a_guide_with_no_url_is_not_published() -> None:
    assert libguides.build_body("Music", "", "", ["Music"]) is None


def test_names_are_compared_without_punctuation_or_and() -> None:
    """The two tables disagree on the Oxford comma and on "and" vs "&".

    "Chemistry and Biochemistry" against "Chemistry & Biochemistry" cost six
    guides on its own.
    """
    assert libguides._norm("Chemistry and Biochemistry") == \
        libguides._norm("Chemistry & Biochemistry")
    assert libguides._norm("Media, Journalism, and Film") == \
        libguides._norm("Media Journalism and Film")
    # Normalisation only. Fuzzy matching would have paired the Film Studies
    # subject with "Journalism 310: Media History", and a wrong guide is
    # worse for the student than no guide.
    assert libguides._norm("Film") != libguides._norm("Journalism 310")


def test_the_description_is_included_when_there_is_one() -> None:
    body = libguides.build_body(
        "APA Citation Style Guide",
        "https://libguides.lib.miamioh.edu/c.php?g=22176",
        "Assistance for citing sources in APA style", ["Psychology"])
    assert "citing sources in APA style" in body


def test_the_address_is_in_the_opening_sentence() -> None:
    """Every chunk must carry a destination.

    The Education guide serves 40-odd subjects. Written out in full the
    pointer ran to 210 words, the chunker cut it in three, and two of the
    three were subject names with no link in them -- a student matching on
    "Art Education" would have retrieved a list and nowhere to go.
    """
    body = libguides.build_body(
        "Education", "https://libguides.lib.miamioh.edu/c.php?g=22058", "",
        [f"Subject {i}" for i in range(40)])
    first = body.splitlines()[0]
    assert "https://" in first, first


def test_a_long_subject_list_is_capped_and_says_so() -> None:
    body = libguides.build_body(
        "Education", "https://libguides.lib.miamioh.edu/c.php?g=22058", "",
        [f"Subject {i}" for i in range(40)])
    assert "more subject(s)" in body, "the overflow must be stated, not hidden"
    assert len(body.split()) < 200, (
        "the pointer has to stay one chunk or its later chunks lose the URL")


def test_a_short_subject_list_is_not_padded() -> None:
    body = libguides.build_body(
        "Music", "https://libguides.lib.miamioh.edu/c.php?g=22067", "",
        ["Music", "Musicology"])
    assert "more subject(s)" not in body


# --- readable addresses ---------------------------------------------------


class _Resp:
    def __init__(self, text): self.text = text


def _og(url):
    return _Resp(f'<meta property="og:url" content="{url}" />')


def test_a_c_php_url_is_replaced_by_the_friendly_one() -> None:
    """LibGuide rows store what the API hands back: c.php?g=22058. That is
    the address a patron would be shown, and it tells them nothing."""
    out = libguides.friendly_url(
        "https://libguides.lib.miamioh.edu/c.php?g=1053974",
        get=lambda *a, **k: _og("https://libguides.lib.miamioh.edu/games-night"))
    assert out == "https://libguides.lib.miamioh.edu/games-night"


def test_the_escaped_ampersand_is_decoded() -> None:
    """og:url is HTML, so its ampersands arrive escaped. Left as-is the
    citation reads c.php?g=22072&amp;p=129894 and the p parameter is lost,
    landing the patron on the wrong tab of the guide."""
    out = libguides.friendly_url(
        "https://libguides.lib.miamioh.edu/c.php?g=22072",
        get=lambda *a, **k: _og(
            "https://libguides.lib.miamioh.edu/c.php?g=22072&amp;p=129894"))
    assert "&amp;" not in out
    assert out.endswith("g=22072&p=129894")


def test_an_og_url_pointing_elsewhere_is_ignored() -> None:
    """A template artefact must not redirect a guide citation off-site."""
    original = "https://libguides.lib.miamioh.edu/c.php?g=22058"
    assert libguides.friendly_url(
        original, get=lambda *a, **k: _og("https://example.com/")) == original


def test_a_lookup_failure_keeps_the_working_address() -> None:
    def _boom(*a, **k):
        raise RuntimeError("libguides timed out")
    original = "https://libguides.lib.miamioh.edu/c.php?g=22058"
    assert libguides.friendly_url(original, get=_boom) == original


def test_a_url_that_is_already_friendly_costs_no_request() -> None:
    def _never(*a, **k):
        raise AssertionError("should not have been fetched")
    url = "https://libguides.lib.miamioh.edu/education"
    assert libguides.friendly_url(url, get=_never) == url
