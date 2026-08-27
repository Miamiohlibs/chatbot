"""What /admin/review could do that /admin/conversations could not.

Flagged listed MESSAGES by preset and dropped them once marked handled.
The conversations view browsed one day at a time and showed neither the
patron's own verdict nor what the bot thought it was being asked.

The merge is only finished if every one of those capabilities is on the
remaining page. This file is that check -- each test names the thing it
would be losing.

The one capability deliberately NOT carried over is the mark-handled
queue. Nobody ever used it: reviewedAt is null on all 3,096 assistant
messages ever logged, which is why 318 rows sat in a queue that never
shrank.
"""

import datetime as dt
from types import SimpleNamespace as NS

import pytest

from src.api.admin.review_queries import list_conversations_on

_TZ = dt.timezone.utc


def _m(cid, content, type_="user", **kw):
    return NS(id=f"{cid}-{content[:6]}-{type_}", conversationId=cid,
              content=content, type=type_,
              timestamp=dt.datetime(2026, 8, 20, 15, tzinfo=_TZ),
              wasRefusal=kw.get("refusal", False),
              isPositiveRated=kw.get("rated", None),
              confidence=kw.get("confidence", "high"),
              intent=kw.get("intent"), citedUrls=[], citedChunkIds=[],
              modelUsed="", latencyMs=0, reviewedAt=None, reviewedBy=None,
              scopeCampus=None, scopeLibrary=None)


class _DB:
    def __init__(self, msgs, feedback=()):
        self._msgs = msgs
        self._fb = list(feedback)
        self.message = NS(find_many=self._find)
        self.conversation = NS(find_many=self._none)
        self.conversationfeedback = NS(find_many=self._fbs)

    async def _none(self, **_): return []
    async def _fbs(self, where=None): return self._fb

    async def _find(self, where=None, order=None, take=None):
        w = where or {}
        out = list(self._msgs)
        ts = w.get("timestamp") or {}
        if ts.get("gte"):
            out = [m for m in out if m.timestamp >= ts["gte"]]
        if ts.get("lt"):
            out = [m for m in out if m.timestamp < ts["lt"]]
        out.sort(key=lambda m: m.timestamp)
        return out


MSGS = (
    [_m("c-ref", "q1"), _m("c-ref", "a1", "assistant", refusal=True,
                           intent="room_booking")]
    + [_m("c-down", "q2"), _m("c-down", "a2", "assistant", rated=False,
                              intent="hours")]
    + [_m("c-up", "q3"), _m("c-up", "a3", "assistant", rated=True)]
    + [_m("c-low", "q4"), _m("c-low", "a4", "assistant", confidence="low")]
    + [_m("c-ok", "q5"), _m("c-ok", "a5", "assistant")]
)


async def _rows(**kw):
    res = await list_conversations_on(_DB(MSGS), "2026-08-20", **kw)
    return {r["conversation_id"] for r in res["rows"]}


@pytest.mark.asyncio
async def test_the_refusal_preset_survived():
    assert await _rows(flag="refusal") == {"c-ref"}


@pytest.mark.asyncio
async def test_the_thumbs_down_preset_survived():
    assert await _rows(flag="thumbs_down") == {"c-down"}


@pytest.mark.asyncio
async def test_the_thumbs_up_preset_survived():
    """The only positive signal in the console. Losing it would leave no
    way to look at what went RIGHT."""
    assert await _rows(flag="thumbs_up") == {"c-up"}


@pytest.mark.asyncio
async def test_the_low_confidence_preset_survived():
    assert await _rows(flag="low_confidence") == {"c-low"}


@pytest.mark.asyncio
async def test_no_flag_shows_everything():
    assert len(await _rows()) == 5


@pytest.mark.asyncio
async def test_an_unknown_flag_does_not_silently_empty_the_page():
    """A typo'd or stale filter value must not read as "no traffic"."""
    assert len(await _rows(flag="nonsense")) == 5


@pytest.mark.asyncio
async def test_the_counts_describe_what_each_filter_will_show():
    res = await list_conversations_on(_DB(MSGS), "2026-08-20")
    assert res["flag_counts"] == {
        "refusal": 1, "thumbs_down": 1, "thumbs_up": 1, "low_confidence": 1}


@pytest.mark.asyncio
async def test_the_counts_are_taken_before_the_filter_runs():
    """A badge that shrinks to 1 the moment you click it is a badge that
    disagrees with the page it opened."""
    res = await list_conversations_on(_DB(MSGS), "2026-08-20", flag="refusal")
    assert res["flag_counts"]["thumbs_down"] == 1


@pytest.mark.asyncio
async def test_what_the_bot_classified_the_question_as_is_on_the_row():
    """Every assistant message carries an intent and none of it was on
    this list, so triaging meant opening a conversation to find out what
    the bot thought it was being asked. Flagged showed it."""
    res = await list_conversations_on(_DB(MSGS), "2026-08-20", flag="refusal")
    assert res["rows"][0]["intents"] == ["room_booking"]


@pytest.mark.asyncio
async def test_the_patron_rating_reaches_the_row():
    """The star rating and comment are the only signal here that comes
    from the person who was actually helped or not."""
    from src.api.admin.review_queries import attach_feedback

    db = _DB(MSGS, feedback=[NS(conversationId="c-down", rating=2,
                                userComment="did not answer me")])
    res = await list_conversations_on(db, "2026-08-20", flag="thumbs_down")
    rows = await attach_feedback(db, res["rows"])
    assert rows[0]["feedback_rating"] == 2
    assert rows[0]["feedback_comment"] == "did not answer me"


# --- every column says what it is ----------------------------------------


def test_the_flags_column_has_a_header():
    """It shipped as a bare <th></th>. That column is the densest one on
    the page -- refusals, thumbs, low confidence, the patron's rating, the
    classified intent -- and the only one whose meaning a reader had to
    infer. An empty header is also nothing at all to a screen reader.
    """
    import re
    from pathlib import Path

    src = Path("src/api/admin/conversations_router.py").read_text(
        encoding="utf-8")
    header = re.search(r"<th>Time</th>.*?</tr>", src, re.S)
    assert header, "the conversations table header moved; update this test"
    assert "<th></th>" not in header.group(0)
    assert "<th>Flags</th>" in header.group(0)
