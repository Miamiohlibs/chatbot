"""Creating a conversation must never fail because of the origin marker.

On 2026-08-21 it did. The migration added Conversation.origin, the canonical
schema had it, and the GENERATED Prisma client did not -- the Python client
builds from a copy of the schema that nobody had synced. Every visitor
carrying the staff-test cookie then got FieldNotFoundError, which surfaced
as a socket handshake that would not complete: a librarian who clicked the
test link could no longer use the chatbot at all.

An optional label must not be able to cost somebody their conversation.
"""

from types import SimpleNamespace as NS

import pytest

from src.memory import conversation_store


class _Prisma:
    """Rejects `origin`, exactly as a client behind the schema does."""

    def __init__(self, reject_origin=True):
        self.calls = []
        self.reject = reject_origin
        self.conversation = NS(create=self._create)

    async def _create(self, data=None):
        self.calls.append(dict(data or {}))
        if self.reject and "origin" in (data or {}):
            from prisma.errors import FieldNotFoundError
            raise FieldNotFoundError(
                {"error": "Could not find field at "
                          "`createOneConversation.data.origin`"})
        return NS(id="c-1")


@pytest.fixture
def patched(monkeypatch):
    def _install(prisma):
        async def _noop():
            return None
        monkeypatch.setattr(conversation_store, "ensure_connection", _noop)
        monkeypatch.setattr(conversation_store, "get_prisma_client",
                            lambda: prisma)
        return prisma
    return _install


@pytest.mark.asyncio
async def test_a_stale_client_costs_the_label_not_the_conversation(patched):
    p = patched(_Prisma(reject_origin=True))
    cid = await conversation_store.create_conversation(origin="staff")
    assert cid == "c-1", "the patron must still get a conversation"
    assert len(p.calls) == 2, "it should retry without the marker"
    assert "origin" not in p.calls[1]


@pytest.mark.asyncio
async def test_the_marker_is_written_when_the_client_knows_the_field(patched):
    p = patched(_Prisma(reject_origin=False))
    await conversation_store.create_conversation(origin="staff")
    assert p.calls == [{"toolUsed": [], "origin": "staff"}]
    assert len(p.calls) == 1, "no pointless retry on the happy path"


@pytest.mark.asyncio
async def test_ordinary_traffic_writes_no_origin(patched):
    p = patched(_Prisma(reject_origin=False))
    await conversation_store.create_conversation()
    assert p.calls == [{"toolUsed": []}]


@pytest.mark.asyncio
async def test_a_real_database_outage_still_raises(patched):
    """The retry must not swallow genuine failures.

    Only the origin path retries, and only once. A database that is simply
    down has to surface, or the socket handler silently hands out
    conversations that were never stored.
    """
    class _Down(_Prisma):
        async def _create(self, data=None):
            raise RuntimeError("postgres is unreachable")

    patched(_Down())
    with pytest.raises(RuntimeError):
        await conversation_store.create_conversation()


@pytest.mark.asyncio
async def test_the_fallback_is_logged_not_silent(patched, caplog):
    # A label quietly going missing is how a measurement becomes wrong
    # without anyone noticing.
    patched(_Prisma(reject_origin=True))
    with caplog.at_level("WARNING"):
        await conversation_store.create_conversation(origin="staff")
    assert any("origin" in r.message.lower() or "origin" in str(r.args).lower()
               for r in caplog.records)


def test_the_deploy_syncs_the_two_schemas():
    """build.sh must sync before it generates.

    The two schema files exist for a real reason -- the Python CLI needs the
    datasource url inlined -- but nothing forced them to agree, and a copy
    that nobody syncs is a copy that is wrong.
    """
    import pathlib
    build = (pathlib.Path(__file__).resolve().parents[3] / "build.sh")
    text = build.read_text()
    assert "--sync-prisma" in text, "build.sh does not sync the schemas"
    assert text.index("--sync-prisma") < text.index("prisma generate"), \
        "the sync has to happen BEFORE the client is generated"
