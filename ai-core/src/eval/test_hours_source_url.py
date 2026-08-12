"""Which page an hours answer sends the patron to.

A space inside a building has its own hours -- the MakerSpace is
9am-4pm by appointment while King around it is 7:30am-9pm -- so citing
the building hours hub after a MakerSpace answer sends the student to a
page that contradicts what they were just told. Gold requires the
space's own page for both MakerSpace cases.
"""
from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent.parent))

from src.eval.real_backends import (  # noqa: E402
    _HOURS_HUB_URL,
    _HOURS_SOURCE_URL,
)


def test_a_space_with_its_own_page_cites_that_page():
    assert (_HOURS_SOURCE_URL["makerspace"]
            == "https://www.lib.miamioh.edu/use/spaces/makerspace/")
    assert _HOURS_SOURCE_URL["special"] == "https://spec.lib.miamioh.edu/home/"


def test_a_building_still_cites_the_hours_hub():
    """Only the spaces whose hours DIFFER from their building get an
    override; a building's own hours are what the hub publishes."""
    for building in ("king", "wertz", "rentschler", "gardner_harvey"):
        assert building not in _HOURS_SOURCE_URL, building


def test_every_override_is_a_real_verified_url():
    """An unverified deep link as a cited URL is how /about/hours/ -> 404
    got shipped once. These are both in the UrlSeen allowlist, which is
    what the answer validator checks against."""
    for url in list(_HOURS_SOURCE_URL.values()) + [_HOURS_HUB_URL]:
        assert url.startswith("https://")
        assert url.endswith("/"), f"{url} -- trailing slash matters to UrlSeen"
        assert "miamioh.edu" in url
