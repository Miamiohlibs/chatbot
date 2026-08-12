"""Pages the bot should POINT AT rather than answer from.

WHY THIS EXISTS
    The operator's framing, 2026-08-12: this bot is the library website's
    navigator, not an answer generator. Two kinds of thing are safe to burn
    into the corpus as answers -- data fetched live from an API, and policy
    that stays put for years (loan periods, renewal limits, fines). Anything
    that carries a date does not qualify. An event page indexed in August is
    a wrong answer in October, and a student who drives to King Library for
    an event that already happened trusts the bot less than one who was
    simply sent to the page.

    So for those pages we index the NAVIGATION and not the content: what the
    page is, who it is for, what its sub-pages cover, and the URLs. The
    student gets routed to the live page and reads the current dates there.

THE GUARANTEE IS STRUCTURAL, NOT A FILTER
    The obvious implementation is "scrape the page, then strip the dates".
    That is the wrong shape: a filter has to catch every way a date can be
    written -- "Sept 12", "next Friday", "Fall semester", "this week" -- and
    the one it misses is served to a student as fact.

    Nothing here is scraped. Each entry is DESCRIBED, by hand, in terms that
    are true regardless of the calendar, and the document is built only from
    those fields. A date cannot leak out of text that was never read in.

    As a second line, `build_body` refuses outright to emit a document whose
    text contains anything date-shaped -- so a future entry written
    carelessly fails loudly at ETL time instead of quietly reaching a
    student. See DATE_SHAPED and its test.

ADDING A SOURCE
    Ask first: how often does this change? If the answer is "every
    semester" or "whenever an event is scheduled", it belongs here. If it is
    a policy that has held for years, it belongs in the ordinary crawl,
    where the bot can answer from it directly.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from . import classify, discover, extract

logger = logging.getLogger("etl.navigation")


# Anything matching these must never appear in a navigation document. The
# point is not to sanitise -- it is to fail the build, loudly, so a careless
# description is fixed rather than shipped.
DATE_SHAPED = re.compile(
    r"\b(20\d{2})\b"                                   # a year
    r"|\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)"
    r"(uary|ruary|ch|il|e|y|ust|ember|ober)?\b\.?\s*\d"  # "Sept 12"
    r"|\b\d{1,2}\s*(st|nd|rd|th)?\s+"
    r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)"  # "12 September"
    r"|\b(mon|tues|wednes|thurs|fri|satur|sun)day\b"
    r"|\b(spring|summer|fall|autumn|winter)\s+(semester|term|20\d{2})"
    r"|\bthis\s+(week|month|semester|term|year)\b"
    r"|\b(upcoming|next\s+week|next\s+month|tonight|today|tomorrow)\b"
    r"|\b\d{1,2}\s*[-–]\s*\d{1,2}\s*(am|pm)\b"
    r"|\b\d{1,2}\s*(am|pm)\b",
    re.IGNORECASE,
)


class DateSensitiveContent(ValueError):
    """Raised when a navigation entry describes something dated."""


@dataclass(frozen=True)
class SubPage:
    label: str
    url: str
    covers: str
    """One line on what a student finds there. No dates, no counts that
    change, no 'currently'."""


@dataclass(frozen=True)
class NavigationSource:
    url: str
    """The canonical page to cite. NOT a vanity redirect: /games is a
    224-byte meta-refresh shim, and citing it indexes nothing useful."""

    title: str
    covers: str
    """What the page is, in terms that survive the calendar."""

    topic: str
    audience: "list[str]" = field(default_factory=lambda: ["student"])
    short_url: "str | None" = None
    """A memorable vanity URL librarians hand out, if there is one. Mentioned
    in the text, never used as the citation."""

    durable_notes: "tuple[str, ...]" = ()
    """Facts that genuinely do not change -- who may attend, where it is
    held, what may be borrowed. Kept because they answer the question a
    student actually asks before clicking."""

    subpages: "tuple[SubPage, ...]" = ()


# --- the registry ---------------------------------------------------------

SOURCES: "tuple[NavigationSource, ...]" = (
    NavigationSource(
        # Requested by Circulation 2026-08-12. The page they named,
        # www.lib.miamioh.edu/games, is a meta-refresh shim; this is what it
        # points at and what has the content.
        url="https://libguides.lib.miamioh.edu/games-night/home",
        short_url="https://www.lib.miamioh.edu/games",
        title="Library Game Nights",
        covers=(
            "The Libraries' game nights and their board game collection: what "
            "the events are, who may come, the pop-up game night kit that can "
            "be checked out, online board games, historic games, and games in "
            "books and film"
        ),
        topic="events",
        durable_notes=(
            "Game nights are held at King Library on the Oxford campus.",
            "Miami students, faculty, staff and their families are welcome; "
            "entry is for Miami students and staff and their guests.",
            "A pop-up game night kit -- a tub of easy-to-play games -- can be "
            "checked out from the Libraries.",
            "Event dates and times change every semester, so the guide is "
            "where to look them up.",
        ),
        subpages=(
            SubPage("Pop-Up Game Night Kit",
                    "https://libguides.lib.miamioh.edu/games-night/games-inventory",
                    "what is in the kit that can be borrowed"),
            SubPage("Online Board Games",
                    "https://libguides.lib.miamioh.edu/games-night/online-board-games",
                    "board games that can be played online"),
            SubPage("Historic Games",
                    "https://libguides.lib.miamioh.edu/games-night/historic-games",
                    "historic and traditional games"),
        ),
    ),
)


# --- building -------------------------------------------------------------


def build_body(source: NavigationSource) -> str:
    """The indexed text. Raises if anything date-shaped got in."""
    lines = [f"{source.title}", "", source.covers + ".", ""]
    if source.durable_notes:
        lines += list(source.durable_notes) + [""]
    lines.append(f"Full details, and anything with a date on it, are on the "
                 f"guide itself: {source.url}")
    if source.short_url:
        lines.append(f"It is also linked as {source.short_url}.")
    if source.subpages:
        lines += ["", "Sections of the guide:"]
        lines += [f"- {p.label} ({p.covers}): {p.url}" for p in source.subpages]

    body = "\n".join(lines)
    hit = DATE_SHAPED.search(body)
    if hit:
        raise DateSensitiveContent(
            f"{source.url} would index date-sensitive text: {hit.group(0)!r}. "
            f"Navigation entries describe what a page IS, not what is on it "
            f"this semester -- rewrite the description."
        )
    return body


def to_document(source: NavigationSource) -> extract.ExtractedDoc:
    body = build_body(source)
    return extract.ExtractedDoc(
        url=source.url,
        title=source.title,
        body_text=body,
        breadcrumbs=["Research Guides", source.title],
        word_count=len(body.split()),
        schema_org_json=None,
        last_modified=None,
        rejection_reason=None,
        # Authored, not scraped, so the boilerplate floor that protects the
        # crawl does not apply -- these are deliberately short.
        min_chunk_tokens=0,
    )


def to_classified() -> "list[tuple[extract.ExtractedDoc, classify.DocMetadata]]":
    out = []
    for s in SOURCES:
        out.append((to_document(s), classify.DocMetadata(
            topic=s.topic,
            campus="oxford",
            library=None,
            audience=list(s.audience),
            featured_service=None,
        )))
    return out


def load() -> "list[tuple[extract.ExtractedDoc, classify.DocMetadata]]":
    """The orchestrator's entry point. No network: nothing here is fetched."""
    docs = to_classified()
    logger.info("navigation: %d pointer document(s), no page content fetched",
                len(docs))
    return docs


def discovered(docs) -> "list[discover.DiscoveredUrl]":
    return [discover.DiscoveredUrl(url=d.url, source="navigation")
            for d, _ in docs]


__all__ = [
    "DATE_SHAPED",
    "DateSensitiveContent",
    "NavigationSource",
    "SOURCES",
    "SubPage",
    "build_body",
    "load",
    "to_classified",
    "to_document",
]
