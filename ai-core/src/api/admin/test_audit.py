"""The record that replaced the passphrase.

Dropping a shared secret is only defensible while what replaces it is
durable and legible. These are written against the ways that fails: a line
that never reached the disk, a name nobody verified presented as though
somebody had, and a corrupt line hiding the month around it.
"""

import datetime as dt
import json

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from src.api.admin import audit
from src.api.admin.audit_router import build_audit_router
from src.api.admin.sso import Caller, ROLE_OPERATOR

WHEN = dt.datetime(2026, 8, 30, 14, 30, tzinfo=dt.timezone.utc)
SIGNED_IN = Caller(role=ROLE_OPERATOR, uid="qum", via="sso")
SHARED_KEY = Caller(role=ROLE_OPERATOR, via="token")


@pytest.fixture
def log(tmp_path, monkeypatch):
    monkeypatch.setattr(audit, "AUDIT_DIR", tmp_path / "audit")
    return tmp_path / "audit"


# --- writing ---------------------------------------------------------------


def test_a_line_lands_on_disk(log):
    assert audit.record(audit.SERVICE_PAUSE, who=SIGNED_IN, when=WHEN,
                        detail="answering nonsense about hours")
    rows = [json.loads(l) for l in
            (log / "actions-2026-08.jsonl").read_text().splitlines()]
    assert len(rows) == 1
    assert rows[0]["action"] == "service.pause"
    assert rows[0]["actor"] == "qum"
    assert rows[0]["authenticated"] is True


def test_the_shared_key_is_recorded_as_unverified(log):
    audit.record(audit.CORPUS_APPROVE, who=SHARED_KEY, when=WHEN)
    row = json.loads((log / "actions-2026-08.jsonl").read_text().strip())
    assert row["actor"] == ""
    assert row["authenticated"] is False


def test_one_file_per_month(log):
    audit.record(audit.SERVICE_PAUSE, who=SIGNED_IN, when=WHEN)
    audit.record(audit.SERVICE_RESUME, who=SIGNED_IN,
                 when=WHEN.replace(month=7))
    assert (log / "actions-2026-08.jsonl").exists()
    assert (log / "actions-2026-07.jsonl").exists()


def test_appending_never_overwrites(log):
    for i in range(3):
        audit.record(audit.CORPUS_FETCH, who=SIGNED_IN, when=WHEN,
                     detail=f"run {i}")
    assert len((log / "actions-2026-08.jsonl").read_text().splitlines()) == 3


def test_a_write_that_fails_says_so_but_does_not_raise(log, monkeypatch,
                                                       caplog):
    """Refusing to let anybody stop the bot because the disk is full is a
    worse failure than an unrecorded pause -- but it must not vanish, or
    dropping the passphrase bought nothing."""
    def boom(*a, **k):
        raise OSError("no space left on device")

    monkeypatch.setattr(audit.Path, "mkdir", boom)
    with caplog.at_level("ERROR"):
        assert audit.record(audit.SERVICE_PAUSE, who=SIGNED_IN,
                            when=WHEN) is False
    assert "AUDIT WRITE FAILED" in caplog.text
    assert "service.pause" in caplog.text, "the line itself must survive"


def test_a_long_detail_is_trimmed_not_rejected(log):
    audit.record(audit.CORPUS_REJECT, who=SIGNED_IN, when=WHEN,
                 detail="x" * 5000)
    row = json.loads((log / "actions-2026-08.jsonl").read_text().strip())
    assert len(row["detail"]) == 1000


# --- reading ---------------------------------------------------------------


def test_newest_first(log):
    for hour in (9, 17, 13):
        audit.record(audit.CORPUS_FETCH, who=SIGNED_IN,
                     when=WHEN.replace(hour=hour), detail=str(hour))
    got = [r["detail"] for r in audit.read_recent(when=WHEN)]
    assert got == ["17", "13", "9"]


def test_reading_an_empty_log_is_not_an_error(log):
    assert audit.read_recent(when=WHEN) == []


def test_a_corrupt_line_does_not_hide_the_month(log):
    audit.record(audit.SERVICE_PAUSE, who=SIGNED_IN, when=WHEN)
    with (log / "actions-2026-08.jsonl").open("a") as fh:
        fh.write("{ this is not json\n")
    rows = audit.read_recent(when=WHEN)
    assert len(rows) == 2
    assert any(r["action"] == "service.pause" for r in rows)
    assert any(r["action"] == "unreadable line" for r in rows)


def test_earlier_months_are_read_too(log):
    audit.record(audit.SERVICE_PAUSE, who=SIGNED_IN,
                 when=WHEN.replace(month=6))
    assert len(audit.read_recent(when=WHEN, months=3)) == 1


def test_an_action_from_a_newer_build_is_still_legible():
    """describe() falls back to the raw name rather than dropping the row,
    so a console running older code still shows what happened."""
    assert audit.describe({"action": "corpus.something.new"}) \
        == "corpus.something.new"


# --- the page --------------------------------------------------------------


@pytest.fixture
def client(log):
    app = FastAPI()

    async def _who():
        return SIGNED_IN

    app.include_router(build_audit_router({"guard": _who}))
    return TestClient(app)


def test_the_page_shows_what_was_done(client, log):
    audit.record(audit.CORPUS_APPROVE, who=SIGNED_IN, target="2026-08-30.md")
    body = client.get("/admin/audit").text
    assert "approved a corpus rebuild" in body
    assert "2026-08-30.md" in body
    assert "qum" in body


def test_an_unverified_name_is_marked_on_its_own_line(client, log):
    """Not in a footnote. A name that looks like the others but means
    something weaker is the one way this page could mislead its reader."""
    audit.record(audit.SERVICE_PAUSE, who=SHARED_KEY)
    # ...as a caller who typed a name into the form would appear.
    audit.record(audit.SERVICE_RESUME,
                 who=Caller(role=ROLE_OPERATOR, uid="someone", via="token"))
    body = client.get("/admin/audit").text
    assert "unverified" in body


def test_an_empty_log_explains_itself(client, log):
    assert "Nothing recorded yet" in client.get("/admin/audit").text


def test_the_filter_only_accepts_what_the_page_offers(client, log):
    audit.record(audit.SERVICE_PAUSE, who=SIGNED_IN)
    audit.record(audit.CORPUS_FETCH, who=SIGNED_IN)
    only = client.get("/admin/audit?kind=service").text
    assert "took the bot out of service" in only
    assert "re-crawled the site" not in only
    # A value we do not offer falls back to everything rather than
    # reaching a filter of the caller's choosing.
    both = client.get("/admin/audit?kind=../../etc").text
    assert "took the bot out of service" in both
    assert "re-crawled the site" in both


def test_the_page_is_not_indexable(client, log):
    assert "noindex" in client.get("/admin/audit").headers["x-robots-tag"]
