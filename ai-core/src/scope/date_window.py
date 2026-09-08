"""
Date extraction for the hours "1-month window" rule (operator ruling
on hr_thanksgiving):

  * a SPECIFIC date <= ~1 month out  -> answerable live via LibCal
    (the agent's get_hours handles that exact date)
  * a SPECIFIC date > 1 month out, or an open-ended range
    ("summer hours") -> point to the hours page + explain it's too
    far ahead to look up live (the PR #63 response)

This module only does the *date extraction + window test*. It's pure,
offline-testable (inject `today`), and dependency-guarded: if
dateparser / holidays / pytz aren't importable it returns None and the
caller falls back to the open-ended-phrasing regex -- never raises.

The holiday + relative-date approach mirrors the proven
`libcal_comprehensive_agent._extract_date_from_query`, kept standalone
here so the v2 rule-B gate doesn't import the heavy legacy agent.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Optional

# A specific date within this many days of "today" is treated as
# answerable live (LibCal serves a near-term window). Beyond it ->
# point-to-page. ~1 month per the operator ruling.
WINDOW_DAYS = 31

# Only trust a parsed date if the text actually contains a date-ish
# token -- stops the parser inventing a date from stray numbers
# ("room 204", "top 5 databases").
_DATE_PATTERNS = (
    r"\d{1,2}/\d{1,2}(/\d{2,4})?",
    r"\d{4}-\d{2}-\d{2}",
    r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{1,2}",
    r"\b\d{1,2}(st|nd|rd|th)?\s+(of\s+)?(jan|feb|mar|apr|may|jun|jul|aug"
    r"|sep|oct|nov|dec)[a-z]*",
    r"\b(today|tonight|tomorrow|yesterday)\b",
    r"\bnext\s+(week|month|monday|tuesday|wednesday|thursday|friday"
    r"|saturday|sunday)\b",
    r"\bthis\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
    r"\bday\s+(after|before)\s+(tomorrow|yesterday)\b",
)

# keyword -> US holidays name fragment (matched against the holidays pkg).
_HOLIDAYS = {
    "new year": "New Year",
    "mlk": "Martin Luther King",
    "martin luther king": "Martin Luther King",
    "presidents day": "Washington",
    "president's day": "Washington",
    "memorial day": "Memorial Day",
    "independence day": "Independence Day",
    "fourth of july": "Independence Day",
    "4th of july": "Independence Day",
    "july 4": "Independence Day",
    "labor day": "Labor Day",
    "columbus day": "Columbus Day",
    "veterans day": "Veterans Day",
    "thanksgiving": "Thanksgiving",
    "christmas": "Christmas",
}


def _holiday_name_matches(name: str, frag: str) -> bool:
    """Whether a `holidays` package name is the holiday `frag` names.

    PREFIX, not substring. "Independence Day" is a substring of
    "Juneteenth National Independence Day", so a substring test answered
    "when is July 4th" with the next Juneteenth -- 2027-06-18 instead of
    2027-07-04 (found 2026-08-10 while fixing the Labor Day case).

    Every fragment in _HOLIDAYS is the start of its holiday's real name
    ("New Year" -> "New Year's Day", "Washington" -> "Washington's
    Birthday"), and no holiday starts with another's fragment, so a prefix
    test separates them. The "(observed)" suffix is stripped first: the
    real date is what a patron names, and it sorts before the observed one
    anyway.
    """
    clean = (name or "").replace(" (observed)", "").strip()
    return clean.startswith(frag)


def _prefer_today_over_next_year(d: date, ref: date) -> date:
    """PREFER_DATES_FROM="future" sends today's own date a year out.

    Asked "is anything open September 6" ON 6 September, dateparser reads
    "future" strictly and answers 2027 -- a date LibCal has no rows for, so
    the answer degrades to nothing useful. Somebody naming today's date
    means today.

    Only that exact case: same month and day, exactly one year ahead.
    Every other future reading is left alone, because "December 25" asked
    in January really does mean the one coming.
    """
    if (d.month, d.day) == (ref.month, ref.day) and d.year == ref.year + 1:
        return ref
    return d


def resolve_target_date(
    text: str, today: Optional[date] = None
) -> Optional[date]:
    """Return the concrete date the question is about, or None.

    None means "no single specific date" (generic, or open-ended like
    'summer hours') -- the caller then uses phrasing heuristics. Never
    raises; missing optional deps -> None.
    """
    if not text:
        return None
    ref = today or date.today()
    t = text.lower()

    # 0) "TODAY" BEATS EVERYTHING. It carries its own date and cannot be
    # ambiguous, so nothing below gets to overrule it.
    #
    # It used to be checked last. A student asking "is there any facility
    # open TODAY on Sunday, September 6, Labor Day weekend, to study?" was
    # told King opens Monday 1pm-1am: "Labor Day" matched at step 1 and
    # took the whole sentence with it. Every library was shut that Sunday,
    # so the honest answer was "no" -- instead they got true hours for the
    # wrong day, with nothing marking the difference.
    if re.search(r"\b(today|tonight|right now)\b", t):
        return ref

    # 1) Named US holiday -> its next occurrence on/after `ref`.
    #
    # "Labor Day WEEKEND" is not Labor Day, and "Christmas EVE" is not
    # Christmas. There the holiday word is a modifier: it names the stretch
    # the asker means, not the day they are asking about.
    try:
        import holidays  # type: ignore

        us = holidays.US(years=[ref.year, ref.year + 1])
        for kw, frag in _HOLIDAYS.items():
            if kw not in t:
                continue
            if re.search(re.escape(kw) + r"\s*(weekend|eve\b)", t):
                continue
            cands = sorted(
                d for d, name in us.items()
                if _holiday_name_matches(name, frag) and d >= ref
            )
            if cands:
                return cands[0]
    except Exception:  # noqa: BLE001 -- optional dep / parse issue
        pass

    # 2) Explicit / relative date -- only if a date token is present.
    if not any(re.search(p, t) for p in _DATE_PATTERNS):
        return None
    settings = {
        "PREFER_DATES_FROM": "future",
        "RELATIVE_BASE": datetime(ref.year, ref.month, ref.day),
        "DATE_ORDER": "MDY",
    }
    try:
        # search_dates() finds a date phrase INSIDE free text
        # ("library hours on May 25" -> May 25). Plain parse() tries
        # the whole string and returns None on a sentence -- the bug a
        # live test caught. Pre-guarded by _DATE_PATTERNS above so we
        # don't run it on dateless text / false-positive on "top 5".
        from dateparser.search import search_dates  # type: ignore

        found = search_dates(text, settings=settings)
        if found:
            return _prefer_today_over_next_year(found[0][1].date(), ref)
    except Exception:  # noqa: BLE001 -- search extra missing / parse issue
        pass
    try:  # fallback: whole-string parse (works for "tomorrow" etc.)
        import dateparser  # type: ignore

        parsed = dateparser.parse(text, settings=settings)
        if parsed is not None:
            return _prefer_today_over_next_year(parsed.date(), ref)
    except Exception:  # noqa: BLE001
        return None
    return None


def within_window(d: date, today: Optional[date] = None) -> bool:
    """True if `d` is between today and today+WINDOW_DAYS inclusive
    (a near-term date LibCal can answer live)."""
    ref = today or date.today()
    return 0 <= (d - ref).days <= WINDOW_DAYS


__all__ = ["WINDOW_DAYS", "resolve_target_date", "within_window"]
