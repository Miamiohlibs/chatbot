"""The ticket queue's tag bar and pagination.

Both exist because the queue could only show one thing: the most recent 200
tickets, undifferentiated. You could not ask it "which ones are still open"
or "which ones have no source URL to work from", and past 200 you could not
see them at all.
"""

from datetime import datetime, timezone
from types import SimpleNamespace as NS

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from src.api.admin.ticket_router import (
    TICKET_TAGS,
    build_ticket_router,
    ticket_tag_counts,
    ticket_where,
)


def _t(i, status="open", source="", email_sent=True):
    return NS(id=f"t-{i}", createdAt=datetime.now(timezone.utc),
              librarianName=f"Person {i}", librarianEmail=f"p{i}@miamioh.edu",
              question=f"question {i}", botAnswer="wrong",
              expectedAnswer="right", sourceUrl=source, status=status,
              reviewedAt=None, emailSent=email_sent)


class _Tickets:
    def __init__(self, rows):
        self.rows = rows

    def _match(self, where):
        rows = self.rows
        if not where:
            return rows
        if "AND" in where:
            for c in where["AND"]:
                rows = _Tickets(rows)._match(c)
            return rows
        out = rows
        st = where.get("status")
        if isinstance(st, dict) and st.get("not"):
            out = [r for r in out if r.status != st["not"]]
        elif isinstance(st, str):
            out = [r for r in out if r.status == st]
        if "sourceUrl" in where:
            out = [r for r in out if (r.sourceUrl or "") == where["sourceUrl"]]
        if "emailSent" in where:
            out = [r for r in out if r.emailSent == where["emailSent"]]
        return out

    async def find_many(self, where=None, order=None, take=None, skip=None):
        rows = self._match(where)[(skip or 0):]
        return rows[:take] if take else rows

    async def count(self, where=None):
        return len(self._match(where))

    async def find_unique(self, where=None):
        return next((r for r in self.rows if r.id == where["id"]), None)

    async def update(self, **_):
        return None


def _client(rows):
    async def _ok() -> None:
        return None

    db = NS(correctionticket=_Tickets(rows),
            message=NS(find_many=_none, count=_zero),
            conversation=NS(find_many=_none, count=_zero),
            manualcorrection=NS(find_many=_none, count=_zero, create=_none),
            modeltokenusage=NS(find_many=_none),
            toolexecution=NS(find_many=_none),
            conversationfeedback=NS(find_unique=_none_one, find_many=_none))
    app = FastAPI()
    app.include_router(build_ticket_router(
        {"db": db, "guard": _ok, "librarian_code": "c"}))
    return TestClient(app, raise_server_exceptions=False), db


async def _none(**_):
    return []


async def _none_one(**_):
    return None


async def _zero(**_):
    return 0


# --- the where clause ------------------------------------------------------


def test_a_status_tag_selects_exactly_that_status():
    assert ticket_where(tag="open") == {"status": "open"}
    assert ticket_where(tag="done") == {"status": "done"}


def test_asking_for_done_shows_done_even_though_the_default_hides_it():
    # Otherwise clicking "Done" returns nothing and reads as a broken filter.
    w = ticket_where(tag="done", show_done=False)
    assert w == {"status": "done"}


def test_the_no_source_tag_is_still_scoped_to_unfinished_work():
    w = ticket_where(tag="no-source", show_done=False)
    assert {"sourceUrl": ""} in w["AND"]
    assert {"status": {"not": "done"}} in w["AND"]


def test_the_default_tag_hides_finished_tickets():
    assert ticket_where(tag="") == {"status": {"not": "done"}}
    assert ticket_where(tag="", show_done=True) == {}


# --- the bar itself --------------------------------------------------------


@pytest.mark.asyncio
async def test_every_tag_count_matches_what_that_tag_will_show():
    # A badge that disagrees with the page it opens is worse than no badge.
    rows = ([_t(i) for i in range(3)]
            + [_t(10, status="done"), _t(11, status="in_progress")]
            + [_t(12, source="", email_sent=False)])
    db = NS(correctionticket=_Tickets(rows))
    counts = await ticket_tag_counts(db)
    for tag, _label in TICKET_TAGS:
        shown = await db.correctionticket.count(where=ticket_where(tag=tag))
        assert counts[tag] == shown, tag


def test_the_bar_renders_every_tag_and_marks_the_active_one():
    client, _ = _client([_t(1)])
    html = client.get("/admin/tickets/view?tag=open&key=K").text
    for _tag, label in TICKET_TAGS:
        assert label in html
    assert "tag active" in html


def test_clicking_a_tag_filters_the_list():
    rows = [_t(1, status="open"), _t(2, status="in_progress"),
            _t(3, status="done")]
    client, _ = _client(rows)
    open_only = client.get("/admin/tickets/view?tag=open&key=K").text
    assert "question 1" in open_only
    assert "question 2" not in open_only and "question 3" not in open_only


def test_a_tag_with_nothing_in_it_says_so_and_offers_a_way_back():
    client, _ = _client([_t(1, status="open")])
    html = client.get("/admin/tickets/view?tag=done&key=K").text
    assert "No tickets here" in html
    assert "All" in html


def test_an_unknown_tag_falls_back_to_the_default_view():
    client, _ = _client([_t(1)])
    r = client.get("/admin/tickets/view?tag=nonsense&key=K")
    assert r.status_code == 200
    assert "question 1" in r.text


# --- pagination ------------------------------------------------------------


def test_the_queue_no_longer_stops_at_the_first_page():
    client, _ = _client([_t(i) for i in range(60)])
    html = client.get("/admin/tickets/view?key=K&per=25").text
    assert "of 60" in html, "the total must be visible, not just the page"
    assert "next" in html


def test_the_second_page_holds_different_tickets():
    client, _ = _client([_t(i) for i in range(60)])
    p1 = client.get("/admin/tickets/view?key=K&per=25&page=1").text
    p2 = client.get("/admin/tickets/view?key=K&per=25&page=2").text
    assert "question 0" in p1 and "question 0" not in p2


def test_paging_keeps_the_tag_you_are_filtered_on():
    # Losing the filter on page 2 is how a filtered view becomes a lie.
    client, _ = _client([_t(i, status="open") for i in range(60)])
    html = client.get("/admin/tickets/view?key=K&per=25&tag=open").text
    assert "tag=open" in html
    assert "page=2" in html


def test_a_hand_edited_per_cannot_ask_for_the_whole_table():
    # 4GB box; one page load must not become a full scan.
    client, _ = _client([_t(i) for i in range(30)])
    r = client.get("/admin/tickets/view?key=K&per=100000")
    assert r.status_code == 200


def test_no_pager_is_drawn_when_everything_fits_on_one_page():
    client, _ = _client([_t(i) for i in range(5)])
    html = client.get("/admin/tickets/view?key=K&per=25").text
    assert "class='pager'" not in html
