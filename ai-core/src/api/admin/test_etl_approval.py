"""Web approval for an ETL diff.

The gate has always been a file on disk, which means the reviewer and the
operator were the same person -- and that is not a gate. This puts the diff
in front of the colleagues who know whether a page belongs in the corpus.

These tests are about the three ways a review surface goes wrong: letting
the wrong person sign, letting somebody sign something they did not read,
and producing a signature the CLI would then refuse.
"""

from __future__ import annotations

import datetime as dt

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from scripts.etl import gate
from src.api.admin import etl_approval_router as R


@pytest.fixture
def diffs(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "DIFF_DIR", tmp_path)
    d = tmp_path / "2026-08-25_1200.md"
    d.write_text(
        "# ETL Diff Report\n\n## Summary\n\n- New chunks: **3**\n\n"
        "## Tombstones\n\n### Lost outright\n\n| chunks | URL |\n|---:|---|\n"
        "| 2 | https://x.edu/gone |\n",
        encoding="utf-8")
    gate.write_approval_template(d, dt.datetime(2026, 8, 25, 12, 0, 0))
    return d


@pytest.fixture
def client(diffs, monkeypatch):
    monkeypatch.setenv("ETL_APPROVERS", "a@miamioh.edu,b@miamioh.edu")
    monkeypatch.setenv("ETL_APPROVAL_PASSWORD", "correct horse")
    app = FastAPI()
    app.include_router(R.build_etl_approval_router({}))
    return TestClient(app)


def _form(diffs, **over):
    body = {"email": "a@miamioh.edu", "password": "correct horse",
            "ack": "yes", "diff_file": diffs.name,
            "diff_hash": gate.hash_diff_file(diffs)}
    body.update(over)
    return body


# --- who may sign --------------------------------------------------------

def test_an_email_not_on_the_list_cannot_sign(client, diffs):
    r = client.post("/admin/etl/approve",
                    data=_form(diffs, email="stranger@example.com"))
    assert r.status_code == 403
    assert not gate.verify_gate(diffs).proceed


def test_a_wrong_passphrase_cannot_sign(client, diffs):
    r = client.post("/admin/etl/approve", data=_form(diffs, password="nope"))
    assert r.status_code == 403
    assert not gate.verify_gate(diffs).proceed


def test_an_unset_allowlist_locks_everyone_out(client, diffs, monkeypatch):
    """Fail closed. A missing .env line must not mean "anyone"."""
    monkeypatch.delenv("ETL_APPROVERS", raising=False)
    r = client.post("/admin/etl/approve", data=_form(diffs))
    assert r.status_code == 403
    assert not gate.verify_gate(diffs).proceed


def test_an_unset_passphrase_locks_everyone_out(client, diffs, monkeypatch):
    monkeypatch.delenv("ETL_APPROVAL_PASSWORD", raising=False)
    r = client.post("/admin/etl/approve", data=_form(diffs))
    assert r.status_code == 403
    assert not gate.verify_gate(diffs).proceed


def test_the_passphrase_is_never_echoed(client, diffs, caplog):
    with caplog.at_level("WARNING"):
        client.post("/admin/etl/approve", data=_form(diffs, password="hunter2"))
    assert "hunter2" not in caplog.text
    assert "hunter2" not in "".join(str(r.args) for r in caplog.records)


# --- signing what you actually read --------------------------------------

def test_a_diff_that_changed_under_them_is_refused(client, diffs):
    """A prepare that runs while the page is open replaces the file under
    the same name. Signing it would attach a real person's name to a change
    they never saw."""
    stale = gate.hash_diff_file(diffs)
    diffs.write_text("# ETL Diff Report\n\n## Summary\n\n- New chunks: **900**\n",
                     encoding="utf-8")
    r = client.post("/admin/etl/approve", data=_form(diffs, diff_hash=stale))
    assert r.status_code == 409
    assert not gate.verify_gate(diffs).proceed


def test_the_acknowledgement_is_required(client, diffs):
    r = client.post("/admin/etl/approve", data=_form(diffs, ack=""))
    assert r.status_code == 400
    assert not gate.verify_gate(diffs).proceed


# --- the happy path, judged by the CLI's own gate ------------------------

def test_a_good_signature_satisfies_the_real_gate(client, diffs):
    """Not "we wrote a file" -- verify_gate is the authority, so the test
    asks it."""
    r = client.post("/admin/etl/approve", data=_form(diffs),
                    follow_redirects=False)
    assert r.status_code == 303
    decision = gate.verify_gate(diffs)
    assert decision.proceed, decision.reason
    assert decision.token.approved_by_email == "a@miamioh.edu"


def test_signing_twice_leaves_one_signature(client, diffs):
    client.post("/admin/etl/approve", data=_form(diffs), follow_redirects=False)
    client.post("/admin/etl/approve", data=_form(diffs, email="b@miamioh.edu"),
                follow_redirects=False)
    token_text = diffs.with_suffix(".approval").read_text(encoding="utf-8")
    assert token_text.count("approved_by_email:") == 1
    assert gate.verify_gate(diffs).proceed


def test_the_page_renders_the_lost_outright_table(client):
    r = client.get("/admin/etl")
    assert r.status_code == 200
    assert "https://x.edu/gone" in r.text
    assert "Lost outright" in r.text or "lost outright" in r.text.lower()


def test_the_page_is_not_indexable(client):
    assert "noindex" in client.get("/admin/etl").headers.get(
        "X-Robots-Tag", "")


def test_with_no_diff_the_page_still_renders(client, diffs):
    diffs.unlink()
    diffs.with_suffix(".approval").unlink()
    r = client.get("/admin/etl")
    assert r.status_code == 200
    assert "prepare" in r.text


def test_post_reaches_the_handler_rather_than_422(client, diffs):
    """The recurring trap in this codebase.

    `from __future__ import annotations` makes every annotation a string,
    and FastAPI resolves those against MODULE globals. A `Request` imported
    inside the router factory is invisible there, so `request: Request` is
    read as a request BODY and every POST returns 422 before the handler
    runs -- including the refusals, so even the auth checks stop working.

    Asserted on a REFUSAL, not the happy path: 403 proves the handler ran
    and made a judgement, which 422 never does.
    """
    r = client.post("/admin/etl/approve",
                    data=_form(diffs, email="stranger@example.com"))
    assert r.status_code == 403, (
        f"expected the handler to refuse, got {r.status_code} -- a 422 means "
        f"FastAPI never called it")


# --- rendering the diff --------------------------------------------------

def test_the_diff_is_rendered_not_dumped(client):
    """The report is markdown we generate. Showing it as raw text made the
    reviewer read the source of a document instead of the document."""
    r = client.get("/admin/etl")
    assert "<table" in r.text
    assert "<strong>3</strong>" in r.text
    assert "## Summary" not in r.text, "raw markdown reached the page"


def test_markup_in_a_page_title_cannot_become_live_html():
    """The diff carries urls and titles harvested from the web. Escaping
    happens before any markdown is interpreted, so a crawled page whose
    title contains a tag renders as text on a page behind a login."""
    out = R.render_markdown("| 1 | <script>alert(1)</script> |")
    assert "<script>" not in out
    assert "&lt;script&gt;" in out


def test_a_guide_url_keeps_its_query_string():
    """c.php guide urls carry an ampersand, and `&amp;` in an href IS the
    ampersand -- dropping the escape would drop the `p` parameter and land
    the reader on the wrong tab."""
    out = R.render_markdown("| 1 | https://libguides.lib.miamioh.edu/c.php?g=1&p=2 |")
    assert 'href="https://libguides.lib.miamioh.edu/c.php?g=1&amp;p=2"' in out


# --- disagreeing with the diff -------------------------------------------

def _reject(diffs, **over):
    body = {"email": "a@miamioh.edu", "password": "correct horse",
            "reason": "the events guide goes stale every semester",
            "urls": "https://www.lib.miamioh.edu/events\nhttps://x.edu/two",
            "diff_file": diffs.name, "diff_hash": gate.hash_diff_file(diffs)}
    body.update(over)
    return body


def test_sending_it_back_records_who_and_why(client, diffs, monkeypatch):
    monkeypatch.setattr(R, "_mail_rejection", lambda *a, **k: None)
    r = client.post("/admin/etl/reject", data=_reject(diffs),
                    follow_redirects=False)
    assert r.status_code == 303
    rec = R.rejection_of(diffs)
    assert rec["by"] == "a@miamioh.edu"
    assert "goes stale" in rec["reason"]
    assert "https://www.lib.miamioh.edu/events" in rec["urls"]


def test_sending_it_back_does_not_approve_it(client, diffs, monkeypatch):
    """The whole point. A rejection must never satisfy the gate."""
    monkeypatch.setattr(R, "_mail_rejection", lambda *a, **k: None)
    client.post("/admin/etl/reject", data=_reject(diffs),
                follow_redirects=False)
    assert not gate.verify_gate(diffs).proceed


def test_a_reason_is_required(client, diffs, monkeypatch):
    monkeypatch.setattr(R, "_mail_rejection", lambda *a, **k: None)
    r = client.post("/admin/etl/reject", data=_reject(diffs, reason="  "))
    assert r.status_code == 400
    assert R.rejection_of(diffs) is None


def test_a_stranger_cannot_send_it_back(client, diffs, monkeypatch):
    monkeypatch.setattr(R, "_mail_rejection", lambda *a, **k: None)
    r = client.post("/admin/etl/reject",
                    data=_reject(diffs, email="stranger@example.com"))
    assert r.status_code == 403
    assert R.rejection_of(diffs) is None


def test_the_objection_is_shown_on_the_page(client, diffs, monkeypatch):
    monkeypatch.setattr(R, "_mail_rejection", lambda *a, **k: None)
    client.post("/admin/etl/reject", data=_reject(diffs),
                follow_redirects=False)
    page = client.get("/admin/etl").text
    assert "a@miamioh.edu" in page
    assert "goes stale" in page
    assert "https://www.lib.miamioh.edu/events" in page
