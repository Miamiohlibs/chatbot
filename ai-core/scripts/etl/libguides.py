"""Subject and course guides, indexed as POINTERS rather than content.

WHY THIS EXISTS
    A student asked "is there a subject guide for film studies?" at 02:32 on
    2026-08-25 and was told the question was outside what a library chatbot
    covers. Miami has a Film Studies guide. We hold its title, its URL and
    the subjects it serves in Postgres -- 480 guides, 741 subjects, 587
    subject-to-guide links -- and none of it was reachable from a question.

    The crawl cannot supply this. The A-Z guide index at
    libguides.lib.miamioh.edu/ renders its list in JavaScript: 66KB of live
    HTML that yields two links, neither of them a guide. Twenty-three guide
    pages reached the index by being linked from somewhere else, out of 480.

WHY POINTERS AND NOT CONTENT
    The operator's framing, 2026-08-12: this bot is the library website's
    navigator, not an answer generator. A guide's CONTENT is a librarian's
    working document -- reading lists, database picks, semester notes -- and
    burning it into the corpus means serving last term's advice as fact.

    What is stable is that the guide EXISTS, what it is called, which
    subjects it serves and where it lives. That is what a student needs to
    be handed, and it is what this module publishes. Nothing here is
    scraped, so nothing dated can leak in; the same DATE_SHAPED guard the
    navigation source uses is applied anyway, because a guide TITLE can
    carry a year ("HST 111 Fall 2026") and that would date the pointer.

WHERE THE DATA COMES FROM
    The LibGuide / Subject / SubjectLibGuide tables, populated by the
    LibGuides API sync. This module only reads them, so a guide renamed or
    retired upstream is picked up by the next ETL run without an edit here.
"""

from __future__ import annotations

import html
import logging
import os
import re
from typing import Optional

from . import classify, config, discover, extract
from .navigation import DATE_SHAPED

logger = logging.getLogger(__name__)


def _norm(name: str) -> str:
    """Compare guide names ignoring punctuation and the word "and".

    SubjectLibGuide stores the guide by NAME, and the two tables disagree on
    the Oxford comma -- "Chemistry and Biochemistry" against "Chemistry &
    Biochemistry". Six guides were lost to that alone.

    Deliberately stops at normalisation. Fuzzy matching would have paired
    the Film Studies subject with "Journalism 310: Media History", which is
    worse for the student than the honest silence of no pointer at all.
    Names that still do not match are logged for a librarian to reconcile.
    """
    s = (name or "").lower()
    s = re.sub(r"\band\b|&", " ", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(s.split())


# Course guides are named for a section that will not exist next year
# ("CJS 271", "EGS 215: Workplace Writing (Cotugno)"). A student asking for
# one asks by course code, which the subject route does not serve, and
# pointing them at last year's section is worse than saying nothing. Only
# guides reachable from a SUBJECT are published.
REQUIRE_SUBJECT = os.getenv("ETL_LIBGUIDES_REQUIRE_SUBJECT", "1") != "0"

TOPIC = "research"

# Enough to carry the words a student would actually type, few enough that
# the pointer stays a single chunk (config.CHUNK_TARGET_TOKENS is 400, and
# the longest guide serves 40-odd subjects).
MAX_SUBJECTS_LISTED = 18


def _rows() -> "list[tuple[str, str, str, list[str]]]":
    """(guide_name, url, description, subjects) for every active guide.

    Reads Postgres directly. Returns [] on any failure -- a guide list we
    cannot read must not take the site crawl down with it.
    """
    import asyncio

    async def _go():
        from prisma import Prisma

        db = Prisma()
        await db.connect()
        try:
            guides = await db.libguide.find_many(where={"isActive": True})
            subjects = await db.subject.find_many()
            links = await db.subjectlibguide.find_many()
            by_id = {s.id: s.name for s in subjects}
            # SubjectLibGuide.libGuide holds the guide NAME, not an id.
            per_guide: dict = {}
            for l in links:
                name = by_id.get(l.subjectId)
                if name:
                    per_guide.setdefault(_norm(l.libGuide), set()).add(name)

            known = {_norm(g.name) for g in guides}
            orphans = sorted(k for k in per_guide if k and k not in known)
            if orphans:
                # NOT a silent drop: these subjects have a guide named in the
                # roster that no row in LibGuide matches, so the student gets
                # no pointer. It is a data reconciliation for a librarian,
                # and it stays visible until someone does it.
                logger.warning(
                    "libguides: %d guide name(s) referenced by a subject have "
                    "no matching guide row, so those subjects get no pointer: "
                    "%s", len(orphans), ", ".join(orphans[:10]))

            out = []
            for g in guides:
                if not (g.url or "").strip():
                    continue
                out.append((g.name or "", g.url,
                            (g.description or "").strip(),
                            sorted(per_guide.get(_norm(g.name), ()))))
            return out
        finally:
            await db.disconnect()

    try:
        return asyncio.run(_go())
    except Exception as exc:  # noqa: BLE001
        logger.warning("libguides: could not read the guide tables: %s", exc)
        return []


def friendly_url(url: str, get=None) -> str:
    """The readable address for a guide, or `url` unchanged.

    LibGuide rows store `c.php?g=22058`, which is what the API hands back.
    That is the address a patron would be shown, and it tells them nothing
    about where they are going. Every guide also has a friendly URL, and the
    page announces it as og:url -- `/education`, `/games-night/home`.

    It matters beyond looks: the crawl already indexes some guides under
    their friendly URL, so publishing the c.php form would put the same
    guide in the index twice under two identities.

    One request per published guide -- about fifty on a nightly run. On any
    failure the c.php form is kept, which still works.
    """
    if not url or "c.php" not in url:
        return url
    try:
        import requests

        get = get or requests.get
        r = get(url, timeout=config.REQUEST_TIMEOUT_SECONDS,
                headers={"User-Agent": config.USER_AGENT})
        m = re.search(
            r"""<meta[^>]+property=["']og:url["'][^>]*content=["']([^"']+)""",
            r.text or "", re.I)
        if not m:
            return url
        # og:url is HTML, so its ampersands arrive escaped. Left as-is the
        # citation would read `c.php?g=22072&amp;p=129894` and the `p`
        # parameter would be lost, landing the patron on the wrong tab.
        found = html.unescape(m.group(1).strip())
        # Only accept a LibGuides address: an og:url pointing anywhere else
        # is a template artefact, not this guide.
        if found.startswith("https://libguides.lib.miamioh.edu/"):
            return found
    except Exception as exc:  # noqa: BLE001
        logger.info("libguides: keeping %s (og:url lookup failed: %s)",
                    url, exc)
    return url


def build_body(name: str, url: str, description: str,
               subjects: "list[str]") -> Optional[str]:
    """The indexed text, or None if it is not safe or not useful to index."""
    if not name or not url:
        return None
    if REQUIRE_SUBJECT and not subjects:
        return None

    # THE URL LEADS, AND THE SUBJECT LIST IS BOUNDED.
    #
    # The Education guide serves 40-odd subjects. Written out in full the
    # pointer ran to 210 words, the chunker cut it in three, and two of the
    # three chunks were subject names with no destination in them -- a
    # student matching on "Art Education" would have retrieved a list and no
    # link, which is the failure this whole module exists to end.
    #
    # So the address goes in the opening sentence, where the leading chunk
    # always carries it, and the list is capped to keep the document to one
    # chunk. The count is kept honest rather than the overflow hidden.
    shown = subjects[:MAX_SUBJECTS_LISTED]
    more = len(subjects) - len(shown)
    lines = [
        f"{name} -- a Miami University Libraries research guide, at {url}",
        "",
    ]
    if shown:
        tail = f", and {more} more subject(s)" if more else ""
        lines.append("Subjects it covers: " + ", ".join(shown) + tail + ".")
    if description:
        lines.append(description.rstrip(".") + ".")
    lines += [
        "",
        f"Current reading lists, recommended databases and anything with a "
        f"date on it are on the guide itself: {url}",
    ]
    body = "\n".join(lines)

    # A guide TITLE can carry a term ("HST 111 Fall 2026"). Publishing that
    # as a pointer dates the pointer, so refuse it here rather than serve a
    # student a guide that named a semester which has passed.
    if DATE_SHAPED.search(body):
        logger.info("libguides: skipping date-shaped guide %r", name)
        return None
    return body


def to_classified() -> "list[tuple[extract.ExtractedDoc, classify.DocMetadata]]":
    out = []
    for name, url, description, subjects in _rows():
        # Resolve the readable address only for guides we will actually
        # publish, so a course guide nobody can reach costs no request.
        if build_body(name, url, description, subjects) is None:
            continue
        url = friendly_url(url)
        body = build_body(name, url, description, subjects)
        if body is None:
            continue
        out.append((
            extract.ExtractedDoc(
                url=url,
                title=f"{name} research guide",
                body_text=body,
                breadcrumbs=["Research Guides"],
                word_count=len(body.split()),
                schema_org_json=None,
                last_modified=None,
                rejection_reason=None,
                # Authored as one short pointer, like a FAQ: the boilerplate
                # floor that protects the crawl would drop every one of them.
                min_chunk_tokens=0,
            ),
            classify.DocMetadata(
                topic=TOPIC,
                campus="oxford",
                library=None,
                audience=["student"],
                featured_service=None,
            ),
        ))
    return out


def load() -> "list[tuple[extract.ExtractedDoc, classify.DocMetadata]]":
    """The Pipeline.extra_docs_fn entry point. Reads Postgres, no network."""
    docs = to_classified()
    logger.info("libguides: %d guide pointer(s) published", len(docs))
    return docs


def discovered(docs) -> "list[discover.DiscoveredUrl]":
    return [discover.DiscoveredUrl(url=d.url, campus="oxford",
                                   source="libguide")
            for d, _ in docs]


__all__ = ["build_body", "discovered", "load", "to_classified"]
