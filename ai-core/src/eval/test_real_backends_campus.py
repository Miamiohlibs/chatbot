"""Campus on a librarian from the LibGuides API.

The LibApps API carries no campus, and lookup_librarian's filter read
"drop this person if their campus differs" -- so with the field empty it
could never fire, and "History - HC" was answered with Oxford's subject
librarian. Nothing downstream could tell that Krista McDonald is at
Hamilton and Jenny Presnell is not.
"""

from __future__ import annotations

import src.eval.real_backends as rb


def test_campus_is_backfilled_by_email(monkeypatch) -> None:
    monkeypatch.setattr(rb, "_CAMPUS_BY_EMAIL",
                        {"mcdonak@miamioh.edu": "Hamilton"})
    d = rb._libguide_lib_to_dict({"first_name": "Krista", "last_name": "McDonald",
                                  "email": "mcdonak@miamioh.edu"})
    assert d["campus"] == "Hamilton"


def test_the_api_value_wins_when_it_has_one(monkeypatch) -> None:
    """The backfill fills a gap; it does not overrule the source."""
    monkeypatch.setattr(rb, "_CAMPUS_BY_EMAIL", {"x@y.edu": "Hamilton"})
    d = rb._libguide_lib_to_dict({"first_name": "A", "last_name": "B",
                                  "email": "x@y.edu", "campus": "Oxford"})
    assert d["campus"] == "Oxford"


def test_an_unknown_email_degrades_to_none(monkeypatch) -> None:
    """A missing campus must cost the filter, never the lookup."""
    monkeypatch.setattr(rb, "_CAMPUS_BY_EMAIL", {})
    assert rb._campus_from_db("stranger@x.edu") is None
    assert rb._campus_from_db(None) is None


def test_a_lookup_failure_degrades_to_none(monkeypatch) -> None:
    def _boom(_fn):
        raise RuntimeError("db down")
    monkeypatch.setattr(rb, "_CAMPUS_BY_EMAIL", None)
    monkeypatch.setattr(rb, "_db", _boom)
    assert rb._campus_from_db("anyone@x.edu") is None
