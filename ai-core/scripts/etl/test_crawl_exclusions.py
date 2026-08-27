"""A reviewer can act on their own objection.

Reviewing a diff used to end in a note. `record_rejection` says so --
"A REJECTION IS A RECORD, NOT AN EDIT" -- and the reasoning was sound
while there was an operator to read those notes: a web form rewriting the
crawl rules would make a change that outlives the conversation with
nobody's name on it.

The operator handed over. An objection that waits for one is a message to
nobody: the reviewer says a page does not belong, presses send, and the
page is still there every week after.

So the loop closes -- and the original concern is answered by making the
change impossible to be silent, not by preventing it. These tests are
about that half.
"""

import datetime as dt
import json

import pytest

from scripts.etl import crawl_exclusions as X

_WHEN = dt.datetime(2026, 8, 27, 18, tzinfo=dt.timezone.utc)
# NOT a page config already excludes -- /about/news-events/ is on the
# prefix list, and a fixture that collides with it would test the prefix
# rule while appearing to test this one.
_URL = "https://www.lib.miamioh.edu/research/instruction/workshops"


@pytest.fixture(autouse=True)
def _store(tmp_path, monkeypatch):
    monkeypatch.setattr(X, "STORE_PATH", tmp_path / "crawl_exclusions.json")
    yield tmp_path / "crawl_exclusions.json"


class TestItRecordsWhoAndWhy:
    def test_an_entry_carries_the_name_the_date_and_the_reason(self):
        """The whole objection to a form doing this was that the change
        would be anonymous. It cannot be."""
        X.add([_URL], by="ken@miamioh.edu", reason="goes stale every term",
              when=_WHEN)
        e = X.load()[0]
        assert e["by"] == "ken@miamioh.edu"
        assert e["at"].startswith("2026-08-27")
        assert e["reason"] == "goes stale every term"

    def test_adding_the_same_page_twice_does_not_duplicate_it(self):
        X.add([_URL], by="a@x.edu", reason="r")
        assert X.add([_URL], by="b@x.edu", reason="r2") == []
        assert len(X.load()) == 1

    def test_the_first_reason_is_kept_not_the_second(self):
        """Whoever excluded it owns the record. Letting a later press
        overwrite the name would lose who actually decided."""
        X.add([_URL], by="ken@miamioh.edu", reason="first")
        X.add([_URL], by="someone@x.edu", reason="second")
        assert X.load()[0]["by"] == "ken@miamioh.edu"


class TestMatching:
    def test_a_trailing_slash_does_not_defeat_it(self):
        """The reviewer copies a link out of the diff; the diff and the
        sitemap do not always agree about the slash."""
        X.add([_URL], by="a@x.edu", reason="r")
        assert X.is_excluded(_URL + "/")

    def test_the_scheme_does_not_defeat_it(self):
        X.add([_URL], by="a@x.edu", reason="r")
        assert X.is_excluded(_URL.replace("https://", "http://"))

    def test_case_does_not_defeat_it(self):
        X.add([_URL], by="a@x.edu", reason="r")
        assert X.is_excluded(_URL.upper().replace("HTTPS", "https"))

    def test_a_different_page_is_untouched(self):
        X.add([_URL], by="a@x.edu", reason="r")
        assert X.is_excluded("https://www.lib.miamioh.edu/about/hours") is None

    def test_it_matches_the_exact_page_and_not_its_children(self):
        """EXACT urls only, by design. A prefix typed into a web form
        cannot be reviewed the way a prefix in config.py can, and `/use/`
        would quietly remove a quarter of the corpus."""
        X.add(["https://www.lib.miamioh.edu/use"], by="a@x.edu", reason="r")
        assert X.is_excluded("https://www.lib.miamioh.edu/use/borrow/ill") is None


class TestUndo:
    def test_removing_puts_the_page_back(self):
        X.add([_URL], by="a@x.edu", reason="r")
        assert X.remove(_URL, by="b@x.edu") is True
        assert X.is_excluded(_URL) is None

    def test_removing_something_absent_reports_it_rather_than_lying(self):
        assert X.remove(_URL, by="b@x.edu") is False


class TestFailureDirection:
    def test_an_unreadable_store_crawls_everything_rather_than_nothing(self,
                                                                      _store):
        """The safe direction. Too much in the corpus is visible in the
        next diff and a reviewer can act on it; an empty corpus would go
        unnoticed until the bot started refusing everything."""
        _store.write_text("{ this is not json", encoding="utf-8")
        assert X.load() == []
        assert X.is_excluded(_URL) is None

    def test_a_missing_store_is_not_an_error(self):
        assert X.load() == []

    def test_rows_without_a_url_are_dropped(self, _store):
        _store.write_text(json.dumps([{"by": "a@x.edu"}, {"url": _URL}]),
                          encoding="utf-8")
        assert len(X.load()) == 1


class TestTheCrawlerHonoursIt:
    def test_an_excluded_page_is_skipped_and_says_who_excluded_it(self):
        from scripts.etl import discover

        X.add([_URL], by="ken@miamioh.edu", reason="r")
        skipped, why = discover._is_excluded(_URL)
        assert skipped is True
        assert "ken@miamioh.edu" in why

    def test_an_ordinary_page_is_still_collected(self):
        from scripts.etl import discover

        assert discover._is_excluded(
            "https://www.lib.miamioh.edu/about/tours") == (False, None)

    def test_the_config_lists_still_win(self):
        """A maintainer's deliberate rule outranks a form. If they ever
        disagree, nothing changes quietly."""
        from scripts.etl import discover

        skipped, why = discover._is_excluded(
            "https://www.lib.miamioh.edu/libraryhealthy/anything")
        assert skipped is True
        assert why.startswith("prefix=")
