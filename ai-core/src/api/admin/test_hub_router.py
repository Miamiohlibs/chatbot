"""Tests for the operator/staff hub landing pages."""
from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_AI_CORE = _HERE.parent.parent.parent
sys.path.insert(0, str(_AI_CORE))

import pytest  # noqa: E402

fastapi = pytest.importorskip("fastapi")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src.api.admin.hub_router import build_hub_router  # noqa: E402


def _client(admin="admintok", code="staffcode"):
    app = FastAPI()
    app.include_router(build_hub_router({
        "admin_token": admin, "librarian_code": code,
    }))
    return TestClient(app)


def test_hubs_fail_closed():
    c = _client()
    assert c.get("/admin/").status_code == 401
    assert c.get("/admin/?key=wrong").status_code == 401
    assert c.get("/librarian/").status_code == 401
    # empty configured secrets stay closed
    c2 = _client(admin="", code="")
    assert c2.get("/admin/?key=").status_code == 401
    assert c2.get("/librarian/?key=").status_code == 401


def test_admin_hub_links_carry_key_and_list_surfaces():
    c = _client()
    r = c.get("/admin/?key=admintok")
    assert r.status_code == 200
    for path in ("/admin/tickets/view?key=admintok",
                 # Flagged folded into Conversations on 2026-08-27, so the
                 # dashboard points there. Two links to one page would
                 # invite the reader to hunt for a difference that no
                 # longer exists.
                 "/admin/conversations?key=admintok",
                 "/admin/corrections/view?key=admintok",
                 "/admin/cost?key=admintok",
                 "/smoketest",
                 # the dashboard shares the staff HUB, not the bare form:
                 # one link for staff to bookmark, and it shows them no
                 # admin surfaces (redesign 2026-07-28)
                 "/librarian/?key=staffcode"):
        assert path in r.text, path
    # counts render as the lead element, colored by whether work waits
    assert "waiting on you" in r.text or "Nothing needs you" in r.text


def test_the_stop_button_is_reachable_from_the_dashboard():
    """It shipped with no link anywhere in the UI, so taking the bot out
    of service required knowing the URL. During an incident that is
    exactly when nobody remembers it."""
    c = _client()
    r = c.get("/admin/?key=admintok")
    assert "/admin/service?key=admintok" in r.text


def test_an_out_of_service_bot_says_so_at_the_top(tmp_path, monkeypatch):
    """The dashboard has to answer "is it up?" before anything else."""
    from src.api.admin import killswitch_router as ks

    flag = tmp_path / "SERVICE_PAUSED"
    monkeypatch.setattr(ks, "_FLAG_PATH", flag)
    c = _client()

    assert "OUT OF SERVICE" not in c.get("/admin/?key=admintok").text

    ks.pause(who="test", note="bad hours answer")
    body = c.get("/admin/?key=admintok").text
    assert "OUT OF SERVICE" in body
    # the banner precedes the queue counts, not buried under them
    headline = next(s for s in ("waiting on you", "Nothing needs you")
                    if s in body)
    assert body.index("OUT OF SERVICE") < body.index(headline)
    assert "bad hours answer" in body, "say why it was paused"
    assert "Put it back in service" in body


def test_dashboard_groups_tools_by_job():
    """One flat "Tools" bucket mixed three different jobs; the operator
    could not tell from the headings which card did what."""
    c = _client()
    r = c.get("/admin/?key=admintok")
    assert "When an answer is wrong" in r.text
    assert "Keep it running" in r.text
    assert "<h2>Tools</h2>" not in r.text


def test_librarian_hub_scoped_to_staff():
    c = _client()
    r = c.get("/librarian/?key=staffcode")
    assert r.status_code == 200
    assert "/librarian/ticket?key=staffcode" in r.text
    # no admin surfaces leak into the staff page
    assert "/admin/" not in r.text.replace("/admin/?", "")
    assert "admintok" not in r.text


def test_staff_hub_drops_ask_us_and_says_what_reporting_costs_them():
    """Staff already live on the Ask Us page -- linking it told them
    nothing. What they actually want to know is whether reporting a bad
    answer lands follow-up work on them."""
    c = _client()
    r = c.get("/librarian/?key=staffcode")
    assert "research-support/ask" not in r.text
    assert "What happens after you send it" in r.text
    # The four-step list was cut to two on 2026-08-21 -- length read as a
    # process. The reassurance that matters moved to the line above it, and
    # that is what this asserts: the wording changed, the promise did not.
    assert "Nothing comes back to you" in r.text

def test_the_dashboard_no_longer_offers_flagged_as_its_own_place():
    """It is the same page now. A second name for one destination is how
    somebody ends up checking both and wondering which is authoritative.

    /admin/review itself still redirects -- that is for bookmarks, not for
    the dashboard to keep advertising."""
    body = _client().get("/admin/?key=admintok").text
    assert ">Flagged<" not in body
    assert "/admin/review" not in body


# --- the headline stopped adding two different things together ----------

def _hub(**counts):
    from src.api.admin.hub_router import render_admin_hub

    base = {"tickets": 0, "flagged": 0, "praised": 0, "corrections": 0}
    base.update(counts)
    return render_admin_hub("K", "CODE", None, base,
                            presence_snapshot={
                                "open": 0, "in_conversation": 0, "waiting": 0,
                                "longest_wait_s": 0.0, "safe_to_restart": True,
                                "verdict": "Nobody is connected.",
                                "warm_up_s": 60, "active_window_s": 300})


def test_a_flagged_turn_is_not_a_ticket():
    """This summed them and called the total "items waiting on you". A
    ticket is a colleague asking for something; a flagged turn MIGHT have
    gone badly -- and on 2026-08-31 the queue held 326, of which 313 were
    our own replays and staff testing."""
    body = _hub(tickets=0, flagged=326)
    assert "326 items waiting on you" not in body
    assert "No tickets waiting" in body
    assert "326 flagged turns" in body


def test_both_are_named_when_both_exist():
    body = _hub(tickets=3, flagged=12)
    assert "3 tickets to work" in body
    assert "12 flagged turns" in body
    # The headline sentence itself, not the whole document -- a bare "15"
    # matches the stylesheet's own `10% 15%`.
    import re
    lede = re.search(r"<p class='lede'>(.*?)</p>", body, re.S).group(1)
    assert "15" not in lede, f"the two counts were summed: {lede}"


def test_a_quiet_console_says_so():
    assert "Nothing needs you right now" in _hub()


def test_a_big_queue_offers_the_sweep():
    body = _hub(flagged=326)
    assert "/admin/review/close-testing" in body
    assert "Most of that queue is our own testing" in body


def test_a_swept_queue_does_not_nag():
    """After a sweep it is around thirty, and the hint would be noise."""
    assert "close-testing" not in _hub(flagged=27)
