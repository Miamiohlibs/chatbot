"""Correcting the classifier by hand.

A rule that cannot be corrected by the person reading it is a rule they stop
trusting. These verdicts override everything -- including the recorded facts
-- because the reader can know things the data cannot hold: that the
colleague at the next desk was testing, that a question came in by phone and
was typed on somebody's behalf.
"""

import datetime as dt
from types import SimpleNamespace as NS

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from src.api.admin.review_queries import MANUAL_LABELS, classify_source

NY = dt.timezone(dt.timedelta(hours=-4))


# --- the verdict wins ------------------------------------------------------


@pytest.mark.parametrize("value,tag", [
    ("bot", "bot"), ("staff", "staff"), ("patron", "patron-confirmed"),
])
def test_each_verdict_is_honoured(value, tag):
    assert classify_source({"source_override": value})["tag"] == tag


def test_a_verdict_overrides_a_recorded_fact():
    # Even origin="staff", which is a fact, yields. Somebody may have opened
    # the staff link and then handed the keyboard to a student.
    v = classify_source({"source_override": "patron", "origin": "staff"})
    assert v["tag"] == "patron-confirmed"


def test_a_verdict_overrides_the_script_detector():
    v = classify_source({"source_override": "staff", "has_dev_row": True,
                         "burst": {"n": 9, "span_s": 20, "median_gap_s": 1.2,
                                   "scripted": True, "by_pace": True}})
    assert v["tag"] == "staff"


def test_the_reason_says_it_was_a_person_and_who():
    v = classify_source({"source_override": "bot",
                         "source_override_by": "qum"})
    assert v["manual"] is True
    assert "qum" in v["why"] and "by hand" in v["why"]


def test_clearing_it_returns_to_the_rules():
    base = {"source_override": None, "origin": "staff"}
    assert classify_source(base)["tag"] == "staff"
    assert classify_source(base).get("manual") is not True


def test_an_unknown_value_is_ignored_rather_than_trusted():
    v = classify_source({"source_override": "banana", "origin": "staff"})
    assert v["tag"] == "staff"


def test_the_three_choices_are_the_three_the_page_offers():
    assert set(MANUAL_LABELS) == {"bot", "staff", "patron"}


# --- the endpoint ----------------------------------------------------------


class _DB:
    def __init__(self):
        self.updates = []
        self.conversation = NS(update=self._update, find_many=self._none)
        self.message = NS(find_many=self._none)
        self.modeltokenusage = NS(find_many=self._none)
        self.conversationfeedback = NS(find_many=self._none)

    async def _update(self, where=None, data=None):
        self.updates.append((where["id"], dict(data or {})))
        return None

    async def _none(self, **_):
        return []


@pytest.fixture
def client():
    async def _ok() -> None:
        return None

    from src.api.admin.conversations_router import build_conversations_router
    db = _DB()
    app = FastAPI()
    app.include_router(build_conversations_router({"db": db, "guard": _ok}))
    return TestClient(app, raise_server_exceptions=False), db


@pytest.mark.parametrize("value", ["bot", "staff", "patron"])
def test_setting_a_verdict_records_it_with_who_and_when(client, value):
    c, db = client
    r = c.get(f"/admin/conversations/c-1/source?set={value}&day=2026-08-21",
              follow_redirects=False)
    assert r.status_code == 303
    assert len(db.updates) == 1
    _id, data = db.updates[0]
    assert data["sourceOverride"] == value
    assert data["sourceOverrideBy"]
    assert data["sourceOverrideAt"] is not None


def test_clearing_wipes_all_three_fields(client):
    c, db = client
    c.get("/admin/conversations/c-1/source?set=&day=2026-08-21",
          follow_redirects=False)
    _id, data = db.updates[0]
    assert data == {"sourceOverride": None, "sourceOverrideBy": None,
                    "sourceOverrideAt": None}


def test_a_junk_value_writes_nothing(client):
    c, db = client
    r = c.get("/admin/conversations/c-1/source?set=banana&day=2026-08-21",
              follow_redirects=False)
    assert db.updates == []
    assert r.status_code == 303, "and still returns the operator to the list"


def test_it_returns_to_the_day_and_filter_you_were_looking_at(client):
    c, _ = client
    r = c.get("/admin/conversations/c-1/source?set=staff&day=2026-08-17"
              "&source=local&key=K", follow_redirects=False)
    loc = r.headers["location"]
    assert "day=2026-08-17" in loc and "source=local" in loc and "key=K" in loc


def test_a_write_failure_does_not_500_the_operator(client):
    c, db = client

    async def _boom(**_):
        raise RuntimeError("locked")
    db.conversation.update = _boom
    r = c.get("/admin/conversations/c-1/source?set=staff&day=2026-08-21",
              follow_redirects=False)
    assert r.status_code == 303


def test_the_route_is_wired_and_never_422s(client):
    # `from __future__ import annotations` plus a factory-scoped Request has
    # produced this four times in this codebase.
    c, _ = client
    r = c.get("/admin/conversations/c-1/source?set=staff",
              follow_redirects=False)
    assert r.status_code != 422
