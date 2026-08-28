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


KEY = "TOKEN123"


@pytest.fixture
def client(diffs, monkeypatch):
    """A client that already holds the admin key.

    Every request goes through `?key=` because the page requires it -- see
    the admin-key tests at the bottom for why.
    """
    monkeypatch.setenv("ETL_APPROVERS", "a@miamioh.edu,b@miamioh.edu")
    monkeypatch.setenv("ETL_APPROVAL_PASSWORD", "correct horse")
    app = FastAPI()
    app.include_router(R.build_etl_approval_router({"admin_token": KEY}))
    raw = TestClient(app)

    class _Keyed:
        """Appends the key so the tests read as what they are about."""

        @staticmethod
        def _u(url):
            return url + ("&" if "?" in url else "?") + f"key={KEY}"

        def get(self, url, **kw):
            return raw.get(self._u(url), **kw)

        def post(self, url, **kw):
            return raw.post(self._u(url), **kw)

    return _Keyed()


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


# --- the admin key -------------------------------------------------------
#
# This shipped with no guard, copied from the kill switch -- which is
# deliberately keyless because it must work when everything else is broken.
# Corpus review has no such requirement, and the cost was visible: the
# console's nav is built from the key on the request, so a keyless page
# rendered a keyless menu and every tab became a dead link into a 401.

@pytest.fixture
def keyed(diffs, monkeypatch):
    monkeypatch.setenv("ETL_APPROVERS", "a@miamioh.edu")
    monkeypatch.setenv("ETL_APPROVAL_PASSWORD", "correct horse")
    app = FastAPI()
    app.include_router(
        R.build_etl_approval_router({"admin_token": "TOKEN123"}))
    return TestClient(app)


def test_without_the_admin_key_the_page_is_refused(keyed):
    assert keyed.get("/admin/etl").status_code == 401


def test_a_wrong_admin_key_is_refused(keyed):
    assert keyed.get("/admin/etl?key=nope").status_code == 401


def test_with_the_key_every_nav_tab_carries_it(keyed):
    """The reported bug. A tab that drops the key is a dead link."""
    import re
    html = keyed.get("/admin/etl?key=TOKEN123").text
    nav = re.search(r"<nav class='tabs'>(.*?)</nav>", html, re.S)
    assert nav, "no nav rendered"
    hrefs = re.findall(r"href='([^']+)'", nav.group(1))
    assert hrefs, "no tabs rendered"
    for h in hrefs:
        assert "key=TOKEN123" in h, f"tab without the key: {h}"


def test_the_key_guards_looking_and_the_passphrase_guards_signing(keyed, diffs):
    """Holding the admin key lets you read a diff, not approve one."""
    r = keyed.post("/admin/etl/approve?key=TOKEN123",
                   data=_form(diffs, password="wrong"))
    assert r.status_code == 403
    assert not gate.verify_gate(diffs).proceed


# --- the one-click path: fetch, sign, live -------------------------------
#
# The web team update the site on Saturdays and used to wait for Monday's
# cron, then for somebody with shell access. These are about the ways a
# button like that goes wrong -- starting work nobody authorised, and
# showing a green page over a corpus nobody rebuilt.


@pytest.fixture(autouse=True)
def _no_real_etl(monkeypatch):
    """Nothing in this file may actually crawl the site or embed anything.

    An accidental real run here would put 410 requests on our own web
    server and spend money, from a unit test.
    """
    from src.api.admin import etl_jobs

    etl_jobs.reset_for_tests()
    started: list = []
    monkeypatch.setattr(
        etl_jobs, "start",
        lambda phase, *, started_by: (started.append((phase, started_by)),
                                      (True, f"{phase} started"))[1])
    monkeypatch.setattr(R, "_started_for_tests", started, raising=False)
    yield started
    etl_jobs.reset_for_tests()


def test_fetch_starts_a_prepare(client, _no_real_etl):
    r = client.post("/admin/etl/fetch",
                    data={"email": "a@miamioh.edu",
                          "password": "correct horse"})
    assert r.status_code in (200, 303)
    assert _no_real_etl == [("prepare", "a@miamioh.edu")]


def test_fetch_refuses_a_wrong_passphrase_and_starts_nothing(
        client, _no_real_etl):
    """A crawl is cheap but it is not free, and it replaces the diff
    whoever else is mid-review is reading."""
    r = client.post("/admin/etl/fetch",
                    data={"email": "a@miamioh.edu", "password": "wrong"})
    assert r.status_code == 403
    assert _no_real_etl == []


def test_fetch_refuses_somebody_not_on_the_approver_list(client, _no_real_etl):
    r = client.post("/admin/etl/fetch",
                    data={"email": "stranger@example.com",
                          "password": "correct horse"})
    assert r.status_code == 403
    assert _no_real_etl == []


def test_approving_starts_the_rebuild(client, diffs, _no_real_etl):
    """Signing is what makes it live now. The whole point of the ask."""
    r = client.post("/admin/etl/approve", data={
        "email": "a@miamioh.edu", "password": "correct horse", "ack": "yes",
        "diff_hash": gate.hash_diff_file(diffs), "diff_file": diffs.name,
    })
    assert r.status_code in (200, 303)
    assert ("apply", "a@miamioh.edu") in _no_real_etl


def test_a_refused_signature_starts_no_rebuild(client, diffs, _no_real_etl):
    client.post("/admin/etl/approve", data={
        "email": "a@miamioh.edu", "password": "wrong", "ack": "yes",
        "diff_hash": gate.hash_diff_file(diffs), "diff_file": diffs.name,
    })
    assert _no_real_etl == []


def test_signing_without_reading_starts_no_rebuild(client, diffs,
                                                   _no_real_etl):
    """The tick box is the gate. Seven minutes of slower answers for a
    diff nobody read is worse than no button at all."""
    client.post("/admin/etl/approve", data={
        "email": "a@miamioh.edu", "password": "correct horse", "ack": "",
        "diff_hash": gate.hash_diff_file(diffs), "diff_file": diffs.name,
    })
    assert _no_real_etl == []


def test_a_stale_diff_starts_no_rebuild(client, diffs, _no_real_etl):
    """If a prepare ran while the page was open, the signature would be
    on content the signer never saw -- and the rebuild would be of it."""
    client.post("/admin/etl/approve", data={
        "email": "a@miamioh.edu", "password": "correct horse", "ack": "yes",
        "diff_hash": "stale-hash", "diff_file": diffs.name,
    })
    assert _no_real_etl == []


def test_the_page_says_what_approving_costs(client):
    """Seven minutes, and answers at 25 seconds instead of 7. Measured
    figures, on the button, before it is pressed -- hiding them would make
    this feel free."""
    body = client.get("/admin/etl").text
    assert "seven minutes" in body
    assert "25 seconds" in body
    assert "keeps answering" in body


def test_the_page_offers_the_fetch_button(client):
    body = client.get("/admin/etl").text
    assert "/admin/etl/fetch" in body
    assert "Fetch the latest site content" in body


# --- acting on your own objection ----------------------------------------
#
# "Send back" recorded a note for an operator to act on. Once the person
# who reads those notes hands over, that is a message to nobody. The
# reviewer can now exclude the pages they named -- with their name, their
# reason and a one-click undo, so the original objection to a form doing
# this (an anonymous change outliving its conversation) still holds.


@pytest.fixture
def store(tmp_path, monkeypatch):
    from scripts.etl import crawl_exclusions

    monkeypatch.setattr(crawl_exclusions, "STORE_PATH",
                        tmp_path / "crawl_exclusions.json")
    return crawl_exclusions


def _send_back(client, diffs, **extra):
    form = {"email": "a@miamioh.edu", "password": "correct horse",
            "reason": "the events guide goes stale every semester",
            "urls": "https://www.lib.miamioh.edu/research/instruction/workshops",
            "diff_hash": gate.hash_diff_file(diffs), "diff_file": diffs.name}
    form.update(extra)
    return client.post("/admin/etl/reject", data=form)


def test_sending_back_alone_changes_nothing(client, diffs, store):
    """The plain button keeps its old meaning. Somebody who wants to
    object without changing the corpus still can."""
    r = _send_back(client, diffs)
    assert r.status_code in (200, 303)
    assert store.load() == []


def test_sending_back_with_exclude_stops_the_crawl_collecting_it(
        client, diffs, store):
    r = _send_back(client, diffs, exclude="yes")
    assert r.status_code == 200
    urls = [e["url"] for e in store.load()]
    assert "https://www.lib.miamioh.edu/research/instruction/workshops" in urls


def test_the_exclusion_carries_the_reviewer_and_the_reason(client, diffs,
                                                           store):
    _send_back(client, diffs, exclude="yes")
    e = store.load()[0]
    assert e["by"] == "a@miamioh.edu"
    assert "goes stale" in e["reason"]


def test_a_wrong_passphrase_excludes_nothing(client, diffs, store):
    _send_back(client, diffs, exclude="yes", password="wrong")
    assert store.load() == []


def test_excluding_with_no_pages_named_records_nothing(client, diffs, store):
    """The reason is required, the pages are not. Ticking exclude with an
    empty list must not be read as "exclude everything"."""
    _send_back(client, diffs, exclude="yes", urls="")
    assert store.load() == []


def test_putting_a_page_back_is_one_click(client, diffs, store):
    _send_back(client, diffs, exclude="yes")
    assert store.load()
    r = client.post("/admin/etl/include", data={
        "url": "https://www.lib.miamioh.edu/research/instruction/workshops",
        "email": "b@miamioh.edu", "password": "correct horse"})
    assert r.status_code == 200
    assert store.load() == []


def test_putting_a_page_back_needs_the_passphrase_too(client, diffs, store):
    _send_back(client, diffs, exclude="yes")
    client.post("/admin/etl/include", data={
        "url": "https://www.lib.miamioh.edu/research/instruction/workshops",
        "email": "b@miamioh.edu", "password": "wrong"})
    assert store.load(), "a wrong passphrase put the page back anyway"


def test_the_page_lists_what_has_been_excluded(client, diffs, store):
    _send_back(client, diffs, exclude="yes")
    body = client.get("/admin/etl").text
    assert "Pages reviewers have excluded" in body
    assert "a@miamioh.edu" in body
    assert "goes stale" in body


def test_the_page_says_nothing_changes_until_somebody_signs(client, diffs,
                                                            store):
    """An exclusion does not touch the live index. Somebody still has to
    fetch, read the new diff and sign -- the gate is not bypassed."""
    _send_back(client, diffs, exclude="yes")
    body = client.get("/admin/etl").text
    assert "nothing changes until somebody" in body.lower() or \
           "next fetch" in body.lower()


# --- pressing the button has to look like it did something ---------------
#
# Reported from the live console, 2026-08-28: "this can't fetch, and if you
# fill in the wrong details there is no message at all."
#
# Both had in fact worked. The fetch ran and finished in 46 seconds, and a
# wrong passphrase did return "Wrong passphrase." What failed was showing
# it: the notice was a bare tinted line with no padding sitting above a
# large white card and a red button, and the page told the READER to
# reload for progress, so pressing Fetch looked like pressing nothing.


def test_a_wrong_passphrase_says_so(client, diffs):
    r = client.post("/admin/etl/fetch",
                    data={"email": "a@miamioh.edu", "password": "nope"})
    assert r.status_code == 403
    assert "Wrong passphrase" in r.text


def test_an_email_not_on_the_list_says_so(client, diffs):
    r = client.post("/admin/etl/fetch",
                    data={"email": "stranger@example.com",
                          "password": "correct horse"})
    assert r.status_code == 403
    assert "not on the approver list" in r.text


def test_a_notice_is_styled_like_a_notice(client):
    """A bare tinted line next to a red button is a whisper. Padding and a
    rule are what make somebody see it."""
    from src.api.admin import admin_ui as ui

    assert "padding" in ui.STYLE.split(".warn,.good{")[1].split("}")[0]
    assert "border-left" in ui.STYLE.split(".warn,.good{")[1].split("}")[0]


def test_starting_a_fetch_confirms_it_started(client, diffs, _no_real_etl):
    """Not a silent redirect to a page that looks unchanged -- the
    reasonable conclusion from that is that the button is broken."""
    r = client.post("/admin/etl/fetch",
                    data={"email": "a@miamioh.edu",
                          "password": "correct horse"})
    assert r.status_code == 200
    assert "Fetching the site now" in r.text


def test_the_page_refreshes_itself_while_a_job_runs(client, diffs,
                                                    monkeypatch):
    from src.api.admin import etl_jobs

    monkeypatch.setattr(etl_jobs, "is_running", lambda: True)
    assert "http-equiv='refresh'" in client.get("/admin/etl").text


def test_it_stops_refreshing_once_the_job_is_done(client, diffs, monkeypatch):
    """A page that reloads for ever fights the reader trying to read a
    diff on it -- which is the whole point of the page."""
    from src.api.admin import etl_jobs

    monkeypatch.setattr(etl_jobs, "is_running", lambda: False)
    assert "http-equiv='refresh'" not in client.get("/admin/etl").text


def test_it_no_longer_tells_the_reader_to_reload(client, diffs, monkeypatch):
    from src.api.admin import etl_jobs

    monkeypatch.setattr(etl_jobs, "is_running", lambda: True)
    body = client.get("/admin/etl").text
    assert "Reload this page" not in body
