"""Navigation entries must not be able to carry a date.

The whole reason these exist is that an event page indexed in August is a
wrong answer in October. The protection is that nothing is scraped -- but a
description written by hand can still say "Fall 2026" by accident, so
build_body refuses outright. These tests are the proof that it does.
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent.parent))

import pytest  # noqa: E402

from scripts.etl import navigation as nav  # noqa: E402


def _src(**kw) -> nav.NavigationSource:
    base = dict(
        url="https://libguides.lib.miamioh.edu/example/home",
        title="Example Guide",
        covers="what the guide is about",
        topic="events",
    )
    base.update(kw)
    return nav.NavigationSource(**base)


# --- the guard ------------------------------------------------------------


@pytest.mark.parametrize("dated", [
    "Events run in Fall 2026.",
    "The next one is September 12.",
    "Held 12 September.",
    "Doors open 5-10 pm.",
    "Starts at 7pm.",
    "Every Friday in the atrium.",
    "See this semester's schedule.",
    "Check the upcoming events list.",
    "Tonight's game is chess.",
    "Updated in 2026.",
])
def test_a_dated_description_is_refused(dated: str) -> None:
    with pytest.raises(nav.DateSensitiveContent):
        nav.build_body(_src(covers="board games", durable_notes=(dated,)))


@pytest.mark.parametrize("durable", [
    "Held at King Library on the Oxford campus.",
    "Miami students, faculty and staff are welcome.",
    "A kit of easy-to-play games can be checked out.",
    "Dates and times change every semester, so check the guide.",
    "Open to anyone with a Miami ID.",
])
def test_durable_wording_is_allowed(durable: str) -> None:
    body = nav.build_body(_src(durable_notes=(durable,)))
    assert durable in body


def test_the_refusal_says_what_to_do_about_it() -> None:
    with pytest.raises(nav.DateSensitiveContent) as e:
        nav.build_body(_src(durable_notes=("Next event is October 17.",)))
    msg = str(e.value)
    assert "October 17" in msg or "October" in msg
    assert "rewrite" in msg.lower(), "the error should say how to fix it"


# --- the registry as it stands --------------------------------------------


def test_every_registered_source_builds() -> None:
    """A dated entry must break the ETL here, not reach a student."""
    for s in nav.SOURCES:
        nav.build_body(s)


def test_sources_cite_the_real_page_not_a_vanity_shim() -> None:
    """www.lib.miamioh.edu/games is a 224-byte meta-refresh shim. Citing it
    would index nothing and send a student to an empty page if the redirect
    ever breaks -- the same trap as the reserves and ILL short URLs."""
    for s in nav.SOURCES:
        assert "libguides." in s.url or "/use/" in s.url, (
            f"{s.url} looks like a vanity redirect; cite the target")
        if s.short_url:
            assert s.short_url != s.url


def test_the_games_guide_points_at_its_subpages() -> None:
    games = [s for s in nav.SOURCES if "games-night" in s.url]
    assert games, "the games guide is not registered"
    body = nav.build_body(games[0])
    for page in ("games-inventory", "online-board-games", "historic-games"):
        assert page in body, f"sub-page {page} is not reachable from the index"
    # and the memorable URL a librarian would hand out is mentioned
    assert "www.lib.miamioh.edu/games" in body


def test_load_touches_no_network() -> None:
    """Nothing here is fetched -- that is the guarantee. If this ever needs a
    fetcher, the design has drifted back to scrape-then-filter."""
    import inspect
    src = inspect.getsource(nav)
    for forbidden in ("requests.", "httpx.", "urlopen", "aiohttp"):
        assert forbidden not in src, (
            f"navigation.py should never fetch: found {forbidden}")


def test_documents_are_indexable() -> None:
    docs = nav.load()
    assert docs
    for doc, meta in docs:
        assert doc.body_text.strip()
        assert doc.min_chunk_tokens == 0, "these are deliberately short"
        assert meta.campus == "oxford"
        assert doc.url in doc.body_text, "the citation URL should be in the text"


# --- wiring ---------------------------------------------------------------


def test_a_libanswers_outage_does_not_drop_the_navigation_pointers() -> None:
    """The two extra-document sources shared one try/except, so a FAQ API
    outage would have silently taken the pointers with it -- and pointers
    touch nothing and cannot fail on their own."""
    from scripts.etl import run_etl

    def _boom():
        raise RuntimeError("libanswers is down")

    real = run_etl.libanswers.load
    try:
        run_etl.libanswers.load = _boom
        docs = run_etl._extra_documents()
    finally:
        run_etl.libanswers.load = real

    urls = [d.url for d, _ in docs]
    assert any("games-night" in u for u in urls), (
        "the navigation pointers were lost when LibAnswers failed")
