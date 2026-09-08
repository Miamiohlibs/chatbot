"""Stable cached prefix for the date cross-check.

Call site: src/graph/new_orchestrator.py, before any hours short-circuit
commits to a specific calendar date.

WHY THIS EXISTS
    `dateparser` is a general-purpose library whose job is to find a date
    in arbitrary text, so it is willing to a fault. It has read "hours" as
    a unit, "do" as a word, "10am" as the 10th of the month, and "Labor Day
    weekend" as Labor Day. It never says "I am not sure" -- it returns
    something, and the caller had no way to tell a confident right answer
    from a confident wrong one.

    Those wrong answers are the expensive kind. A student asked whether
    anything was open on Sunday 6 September and was told King opens Monday
    1pm-1am: true, about a day nobody asked about, with nothing marking the
    difference. That is a walk to a locked building.

    So this is a SECOND OPINION, not a replacement. The deterministic
    resolver still decides; this only says whether it agrees. Disagreement
    does not pick a winner -- it makes the hours path decline, and the
    answer falls back to the whole-week table, which needs no exact date
    and cannot send anybody to the wrong day.

    Cheap tier, and only on turns that were about to commit to a date --
    around 2% of them.

WHAT IT MUST NOT DO
    Guess. "NONE" is a first-class answer here and the right one for
    "what are your hours", "open Labor Day weekend" (a stretch, not a day)
    and anything without a date in it. A model that always names a date
    would agree with a wrong resolver as often as a right one and buy us
    nothing.
"""

from __future__ import annotations

from src.prompts import register_prefix

DATE_CHECK_V1_PREFIX = """\
You resolve which single calendar date a library question is asking about.

You are given today's date and a question. Reply with the one date the \
question is about, or NONE.

Rules:
- "today", "tonight", "right now" -> today's date.
- "tomorrow" -> the day after today. "the day after tomorrow" -> two days.
- A weekday with no other marker means the NEXT such day, counting today \
if today is that weekday.
- A named holiday means that holiday's date. But a holiday used as a \
MODIFIER is not that holiday: "Labor Day weekend" is a weekend, \
"Christmas Eve" is not Christmas. Those are NONE unless another date is \
also given.
- An explicit date ("September 12", "8/21", "August 21, 2026") wins over a \
weekday word in the same sentence.
- If the question names today's own month and day with no year, that means \
TODAY, not next year.

Answer NONE when:
- there is no date in the question at all ("what are your hours");
- the question covers a STRETCH rather than a day ("this weekend", \
"over break", "summer hours", "Labor Day weekend");
- two date signals genuinely conflict and you cannot tell which is meant.

NONE is a good answer. Do not guess a date to seem helpful -- a wrong date \
sends somebody to a locked building, and NONE simply makes us answer with \
the whole week instead.

Return JSON: {"date": "YYYY-MM-DD"} or {"date": null}.
"""

register_prefix("date_check_v1", DATE_CHECK_V1_PREFIX)
