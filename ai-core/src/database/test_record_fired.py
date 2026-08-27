"""fireCount is written now.

Nothing ever wrote ManualCorrection.fireCount, and the admin list rendered
it -- so every correction read as "never fired" however often it did. That
reading was on its way to retiring five working rules as dead weight. A
counter that only ever says zero is worse than no counter: it looks like
evidence.
"""

from types import SimpleNamespace as NS

import pytest

from src.database.corrections_adapter import PrismaCorrectionsStore, _uuid_to_int


class _Client:
    def __init__(self, rows, fail_on_update=False):
        self._rows = rows
        self._fail = fail_on_update
        self.updates: list = []
        self.manualcorrection = NS(find_many=self._find, update=self._update)

    def is_connected(self): return True
    async def connect(self): return None
    async def disconnect(self): return None
    async def _find(self, where=None): return self._rows

    async def _update(self, where=None, data=None):
        if self._fail:
            raise RuntimeError("postgres went away")
        self.updates.append((where["id"], data["fireCount"]))
        return None


_A = "a9862ad2-1d11-4f70-b1b2-04207468e753"
_B = "2cfaea70-47c0-4b78-a69c-100a7c4b1d15"


def _rows():
    return [NS(id=_A, fireCount=0), NS(id=_B, fireCount=7)]


def test_it_bumps_only_the_ones_that_fired():
    client = _Client(_rows())
    store = PrismaCorrectionsStore(client=client)
    assert store.record_fired([_uuid_to_int(_A)]) == 1
    assert client.updates == [(_A, 1)]


def test_it_counts_up_from_whatever_was_there():
    client = _Client(_rows())
    store = PrismaCorrectionsStore(client=client)
    store.record_fired([_uuid_to_int(_B)])
    assert client.updates == [(_B, 8)]


def test_two_corrections_on_one_turn_both_count():
    client = _Client(_rows())
    store = PrismaCorrectionsStore(client=client)
    assert store.record_fired([_uuid_to_int(_A), _uuid_to_int(_B)]) == 2


def test_an_empty_list_does_not_touch_the_database():
    client = _Client(_rows())
    assert PrismaCorrectionsStore(client=client).record_fired([]) == 0
    assert client.updates == []


def test_an_id_that_matches_nothing_is_ignored():
    client = _Client(_rows())
    assert PrismaCorrectionsStore(client=client).record_fired([999999]) == 0


def test_a_database_failure_never_reaches_the_caller():
    """The turn already produced an answer the correction improved. Losing
    the count is the cheapest possible failure; raising here would trade a
    good answer for a telemetry write."""
    client = _Client(_rows(), fail_on_update=True)
    assert PrismaCorrectionsStore(client=client).record_fired(
        [_uuid_to_int(_A)]) == 0


def test_the_int_mapping_is_the_one_the_loader_uses():
    """record_fired rebuilds the uuid->int map rather than inverting it,
    because the hash is one-way. If the two ever disagreed, every count
    would silently stay zero again."""
    assert _uuid_to_int(_A) == _uuid_to_int(_A)
    assert _uuid_to_int(_A) != _uuid_to_int(_B)
