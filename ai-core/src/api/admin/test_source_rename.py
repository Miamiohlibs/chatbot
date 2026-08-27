"""The manual verdict buttons are B / S / P — bot, staff, patron.

They were S / T / P, where "S" meant script-local and "T" meant staff. The
letters did not match their own words, so the reader had to hover to find
out which was which.

The rename carries a stored value with it: `local` became `bot`. Twelve
conversations were written with the old one, and `?source=local` is in
bookmarks and in every link the page printed before 2026-08-27 — so it is
accepted on READ for ever and never written again. Most of this file is
about that half, because a rename that quietly stops matching old rows is
how twelve known scripts turn into twelve "real patrons".
"""

import datetime as dt
from types import SimpleNamespace as NS

import pytest

from src.api.admin.review_queries import (
    MANUAL_LABELS,
    SOURCE_TAGS,
    TESTING_TAGS,
    canonical_source,
    classify_source,
    list_conversations_on,
)

_TZ = dt.timezone.utc


class TestTheNames:
    def test_the_three_choices_are_bot_staff_patron(self):
        assert set(MANUAL_LABELS) == {"bot", "staff", "patron"}

    def test_the_filter_bar_offers_bot_not_local(self):
        values = {v for v, _ in SOURCE_TAGS}
        assert "bot" in values
        assert "local" not in values

    def test_the_buttons_read_b_s_p(self):
        """B, S, P in that order, each next to the word it stands for."""
        from pathlib import Path

        src = Path("src/api/admin/conversations_router.py").read_text(
            encoding="utf-8")
        assert 'set_link(cid, "bot", "B"' in src
        assert 'set_link(cid, "staff", "S"' in src
        assert 'set_link(cid, "patron", "P"' in src
        assert '"T", "Mark as staff' not in src


class TestTheOldValueStillReads:
    def test_local_maps_onto_bot(self):
        assert canonical_source("local") == "bot"
        assert canonical_source("LOCAL") == "bot"
        assert canonical_source(" local ") == "bot"

    def test_anything_else_passes_through_untouched(self):
        for v in ("bot", "staff", "patron", "maybe-staff", ""):
            assert canonical_source(v) == v

    def test_a_conversation_stored_as_local_is_still_a_manual_verdict(self):
        """Twelve rows carry it. If the override stopped being recognised
        they would fall back to the automatic rules, and a person's
        verdict would be silently overruled by a guess."""
        v = classify_source({"source_override": "local",
                             "source_override_by": "operator"})
        assert v["manual"] is True
        assert v["tag"] in ("bot", "local")

    def test_local_is_still_counted_as_testing(self):
        """close-testing sweeps TESTING_TAGS. Dropping `local` would
        reclassify twelve known scripts as patron traffic — the direction
        that inflates every real-patron number we report."""
        assert "local" in TESTING_TAGS
        assert "bot" in TESTING_TAGS


class _DB:
    def __init__(self, overrides):
        self._ov = overrides
        self.message = NS(find_many=self._msgs)
        self.conversation = NS(find_many=self._convs)
        self.conversationfeedback = NS(find_many=self._none)

    async def _none(self, **_): return []

    async def _convs(self, **_):
        return [NS(id=cid, sourceOverride=val, sourceOverrideBy="operator",
                   sourceOverrideAt=dt.datetime(2026, 8, 21, tzinfo=_TZ))
                for cid, val in self._ov.items()]

    async def _msgs(self, where=None, order=None, take=None):
        out = []
        for cid in self._ov:
            for i, (txt, typ) in enumerate((("q", "user"), ("a", "assistant"))):
                out.append(NS(
                    id=f"{cid}-{i}", conversationId=cid, content=txt, type=typ,
                    timestamp=dt.datetime(2026, 8, 21, 15, tzinfo=_TZ),
                    wasRefusal=False, isPositiveRated=None, confidence="high",
                    intent=None, citedUrls=[], citedChunkIds=[], modelUsed="",
                    latencyMs=0, reviewedAt=None, reviewedBy=None,
                    scopeCampus=None, scopeLibrary=None))
        return out


@pytest.mark.asyncio
async def test_both_names_filter_to_the_same_conversations():
    """A bookmark from before the rename has to keep working, and it has
    to work at the QUERY layer -- a script or the eval calling
    list_conversations_on directly gets the alias too, not just a browser
    going through the router."""
    db = _DB({"old": "local", "new": "bot"})
    by_old = await list_conversations_on(db, "2026-08-21", source="local")
    by_new = await list_conversations_on(db, "2026-08-21", source="bot")
    assert {r["conversation_id"] for r in by_old["rows"]} == {"old", "new"}
    assert {r["conversation_id"] for r in by_new["rows"]} == {"old", "new"}
