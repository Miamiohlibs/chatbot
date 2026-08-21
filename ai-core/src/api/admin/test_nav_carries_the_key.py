"""Every admin page must keep the operator signed in.

Until SSO is switched on, `?key=` IS the session. A page that renders the
top menu without it hands the operator seven dead links and no way back
except the browser button -- which is exactly what /admin/review/{id} did,
the page you land on most.

This renders each page through its real handler and asserts the invariant,
so the next page added is covered without anyone remembering to.
"""

import datetime as dt
from types import SimpleNamespace as NS

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

KEY = "s3cret-key"


def _links(html: str) -> list[str]:
    import re
    return re.findall(r"""href=['"](/admin[^'"]*)['"]""", html)


def keyless_admin_links(html: str) -> list[str]:
    """Admin links that would drop the session."""
    out = []
    for href in _links(html):
        if href.startswith("/admin/sso/"):
            continue          # the SSO endpoints are the way IN; no key needed
        if "key=" not in href:
            out.append(href)
    return out


# --- fakes -----------------------------------------------------------------


def _msg(cid="c-1", content="when do you close", type_="user", **kw):
    return NS(id=f"m-{type_}-{content[:6]}", conversationId=cid,
              content=content, type=type_,
              timestamp=dt.datetime(2026, 8, 21, 15, tzinfo=dt.timezone.utc),
              wasRefusal=kw.get("refusal", False), isPositiveRated=None,
              confidence="high", intent="hours", citedUrls=[], citedChunkIds=[],
              modelUsed="", latencyMs=12, reviewedAt=None, reviewedBy=None,
              scopeCampus=None, scopeLibrary=None)


class _DB:
    def __init__(self):
        msgs = [_msg(), _msg(content="King closes at 9pm.", type_="assistant")]
        self.message = NS(find_many=self._msgs, find_unique=self._one_msg,
                          count=self._count, update=self._noop)
        self.conversation = NS(
            find_unique=lambda where=None: self._conv(),
            find_many=self._none, count=self._count)
        self.correctionticket = NS(find_many=self._tickets,
                                   find_unique=self._ticket,
                                   update=self._noop, count=self._count)
        self.manualcorrection = NS(find_many=self._none, create=self._noop,
                                   count=self._count)
        self.modeltokenusage = NS(find_many=self._none, group_by=self._none)
        self.toolexecution = NS(find_many=self._none)
        self.conversationfeedback = NS(find_unique=self._nofb,
                                       find_many=self._none)
        self._m = msgs

    async def _msgs(self, where=None, order=None, take=None, skip=None):
        return self._m

    async def _one_msg(self, where=None):
        return self._m[0]

    async def _conv(self):
        return NS(id="c-1", createdAt=dt.datetime(2026, 8, 21,
                                                  tzinfo=dt.timezone.utc),
                  toolUsed=[])

    async def _none(self, **_):
        return []

    async def _count(self, **_):
        return 1

    async def _noop(self, **_):
        return None

    async def _nofb(self, where=None):
        return None

    async def _tickets(self, **_):
        return [self._t()]

    async def _ticket(self, where=None):
        return self._t()

    @staticmethod
    def _t():
        return NS(id="t-1",
                  createdAt=dt.datetime(2026, 8, 21, tzinfo=dt.timezone.utc),
                  librarianName="A Librarian", librarianEmail="a@miamioh.edu",
                  question="when do you close", botAnswer="9pm",
                  expectedAnswer="9pm on weekdays", sourceUrl="",
                  status="open", reviewedAt=None, emailSent=True)


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("SERVICE_PAUSE_FLAG", str(tmp_path / "PAUSED"))

    async def _ok() -> None:
        return None

    db = _DB()
    deps = {"db": db, "guard": _ok, "require_librarian": _ok,
            "admin_token": KEY, "librarian_code": "code"}

    from src.api.admin.conversations_router import build_conversations_router
    from src.api.admin.corrections_router import build_corrections_router
    from src.api.admin.cost_view_router import build_cost_view_router
    from src.api.admin.hub_router import build_hub_router
    from src.api.admin.killswitch_router import build_killswitch_router
    from src.api.admin.review_view_router import build_review_view_router
    from src.api.admin.ticket_router import build_ticket_router

    app = FastAPI()
    for build in (build_review_view_router, build_conversations_router,
                  build_ticket_router, build_corrections_router,
                  build_cost_view_router, build_hub_router):
        app.include_router(build(deps))
    app.include_router(build_killswitch_router({}))
    return TestClient(app, raise_server_exceptions=False)


PAGES = [
    "/admin/",
    "/admin/conversations",
    "/admin/review",
    "/admin/review/c-1",          # the one that was broken
    "/admin/tickets/view",
    "/admin/tickets/t-1",
    "/admin/corrections/view",
    "/admin/cost",
]


@pytest.mark.parametrize("path", PAGES)
def test_every_admin_link_on_the_page_carries_the_key(client, path):
    r = client.get(f"{path}?key={KEY}")
    assert r.status_code == 200, f"{path} -> {r.status_code}"
    bad = keyless_admin_links(r.text)
    assert not bad, f"{path} renders link(s) that drop the session: {bad}"


@pytest.mark.parametrize("path", PAGES)
def test_the_top_menu_is_present_on_every_page(client, path):
    # A page with no nav is a dead end even when its own links are fine.
    r = client.get(f"{path}?key={KEY}")
    assert "/admin/conversations" in r.text or "class='tabs'" in r.text, path


def test_the_detector_would_have_caught_the_bug_it_was_written_for():
    # Non-vacuity: prove the helper flags a keyless admin link.
    assert keyless_admin_links("<a href='/admin/review'>x</a>") == ["/admin/review"]
    assert keyless_admin_links(f"<a href='/admin/review?key={KEY}'>x</a>") == []
    # SSO endpoints are exempt -- they are how you get a session.
    assert keyless_admin_links("<a href='/admin/sso/login'>in</a>") == []
