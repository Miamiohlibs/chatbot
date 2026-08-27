"""Pages a reviewer has said do not belong in the corpus.

WHY THIS EXISTS
    Reviewing a diff used to end in a note. `record_rejection` says so in
    as many words -- "A REJECTION IS A RECORD, NOT AN EDIT" -- and the
    reasoning was that a web form rewriting the crawl rules would make a
    change that outlives the conversation with nobody's name on it, so the
    operator should make it deliberately instead.

    That reasoning assumed an operator. When the person who reads these
    notes hands over, an objection becomes a message to nobody: the
    reviewer says a page should not be indexed, presses send, and the page
    is still there next week and every week after.

    So the loop closes here. The objection still cannot be silent -- but
    it no longer needs somebody with shell access to act on it.

WHAT KEEPS IT HONEST
    * Every entry carries who excluded it, when, and why. The original
      objection to a form doing this was that the change would be
      anonymous; this one cannot be.
    * EXACT URLs only. The code lists in config.py take prefixes and
      regexes because a maintainer reading them can see what they sweep;
      a prefix typed into a web form cannot be seen the same way, and
      `/use/` would quietly remove a quarter of the corpus.
    * Undoing is one click, and the next crawl brings the page back. An
      exclusion that is hard to reverse is one people are afraid to make.
    * It changes nothing on its own. The page stays in the live index
      until somebody fetches a new diff, reads it, and signs.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

STORE_PATH = Path(
    os.getenv("ETL_EXCLUSIONS_PATH", "/opt/chatbot/ai-core/data/crawl_exclusions.json")
)


def _norm(url: str) -> str:
    """Compare URLs the way the crawler will see them.

    Scheme and a trailing slash are noise here: the reviewer copies a link
    out of the diff, and the diff and the sitemap do not always agree about
    either.
    """
    u = (url or "").strip().lower()
    u = u.removeprefix("https://").removeprefix("http://")
    return u.rstrip("/")


def load() -> list:
    """Every exclusion on record. Never raises.

    An unreadable store means the crawl proceeds WITHOUT the exclusions --
    a corpus with too much in it, which a reviewer can see and act on.
    Failing closed would empty the corpus instead, which nobody would
    notice until the bot started refusing everything.
    """
    try:
        if not STORE_PATH.exists():
            return []
        data = json.loads(STORE_PATH.read_text(encoding="utf-8"))
        return [e for e in data if isinstance(e, dict) and e.get("url")]
    except Exception:  # noqa: BLE001
        logger.warning("crawl exclusions unreadable at %s -- crawling "
                       "without them", STORE_PATH, exc_info=True)
        return []


def excluded_urls() -> set:
    return {_norm(e["url"]) for e in load()}


def is_excluded(url: str) -> "Optional[dict]":
    """The entry that excludes `url`, or None."""
    want = _norm(url)
    for e in load():
        if _norm(e["url"]) == want:
            return e
    return None


def _save(entries: list) -> None:
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STORE_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(entries, indent=1, ensure_ascii=False),
                   encoding="utf-8")
    tmp.replace(STORE_PATH)


def add(urls: list, *, by: str, reason: str,
        when: "Optional[dt.datetime]" = None) -> list:
    """Record an exclusion for each url. Returns the ones newly added."""
    stamp = (when or dt.datetime.now(dt.timezone.utc)).isoformat(
        timespec="seconds")
    entries = load()
    have = {_norm(e["url"]) for e in entries}
    added = []
    for raw in urls:
        u = (raw or "").strip()
        if not u or _norm(u) in have:
            continue
        entries.append({"url": u, "by": by, "at": stamp,
                        "reason": " ".join((reason or "").split())})
        have.add(_norm(u))
        added.append(u)
    if added:
        _save(entries)
        logger.warning("crawl exclusions added by %s: %s", by, added)
    return added


def remove(url: str, *, by: str) -> bool:
    """Undo one exclusion. The next crawl collects the page again."""
    entries = load()
    want = _norm(url)
    kept = [e for e in entries if _norm(e["url"]) != want]
    if len(kept) == len(entries):
        return False
    _save(kept)
    logger.warning("crawl exclusion removed by %s: %s", by, url)
    return True


__all__ = ["STORE_PATH", "add", "excluded_urls", "is_excluded", "load",
           "remove"]
