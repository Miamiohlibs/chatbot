"""Promotion is a recorded action, not a hand-edit.

`mark_applied` writes `promoted: no`, which is true when written and stops
being true the moment somebody points WEAVIATE_CHUNK_COLLECTION at the
collection. Nothing updated it, so the marker for the LIVE corpus said
`promoted: no` for as long as it served -- and this file is the only
on-disk record of which collection a cleanup script must not sweep up. A
record that is wrong in the reassuring direction is worse than no record:
the 2026-07-29 incident was a cleanup deleting a good collection because
disk said it was not in use.
"""

import datetime as dt

import pytest

from scripts.etl import gate

_NOW = dt.datetime(2026, 8, 27, 3, 16, tzinfo=dt.timezone.utc)


def _applied(tmp_path, promoted="no"):
    diff = tmp_path / "2026-08-25_1935.md"
    diff.write_text("# diff\n", encoding="utf-8")
    marker = diff.with_suffix(".applied")
    marker.write_text(
        "applied_at: 2026-08-26T00:40:35+00:00\n"
        "approved_by: qum@miamioh.edu\n"
        "diff_hash: abc\n"
        "collection: Chunk_vv20260826_0039\n"
        f"promoted: {promoted}\n"
        "# DO NOT DELETE the collection above: it is approved and\n"
        "# awaiting promotion. `promoted: no` means nothing serves\n"
        "# from it yet -- that is expected, not a sign it is junk.\n",
        encoding="utf-8")
    return diff, marker


def test_it_records_when_promotion_happened(tmp_path):
    diff, marker = _applied(tmp_path)
    gate.mark_promoted(diff, "Chunk_vv20260826_0039", _NOW)
    body = marker.read_text(encoding="utf-8")
    assert "promoted: 2026-08-27T03:16:00+00:00" in body
    assert "promoted: no" not in body


def test_the_collection_name_survives(tmp_path):
    """The line a cleanup script reads. Losing it is the failure mode this
    whole marker exists for."""
    diff, marker = _applied(tmp_path)
    gate.mark_promoted(diff, "Chunk_vv20260826_0039", _NOW)
    assert "collection: Chunk_vv20260826_0039" in marker.read_text()


def test_the_promoted_no_explainer_goes_away(tmp_path):
    """Left in place it sits under a timestamp saying the opposite, and a
    file that argues with itself reads as unreliable, not as current."""
    diff, marker = _applied(tmp_path)
    gate.mark_promoted(diff, "Chunk_vv20260826_0039", _NOW)
    body = marker.read_text(encoding="utf-8")
    assert "`promoted: no` means nothing serves" not in body
    assert "awaiting promotion" not in body


def test_promoting_a_diff_with_no_marker_raises(tmp_path):
    diff = tmp_path / "x.md"
    diff.write_text("# diff\n", encoding="utf-8")
    with pytest.raises(FileNotFoundError):
        gate.mark_promoted(diff, "C", _NOW)


def test_promoted_collection_reads_back_what_was_written(tmp_path):
    diff, _ = _applied(tmp_path)
    assert gate.promoted_collection(diff) is None
    gate.mark_promoted(diff, "Chunk_vv20260826_0039", _NOW)
    assert gate.promoted_collection(diff) == "Chunk_vv20260826_0039"


def test_an_unpromoted_marker_reports_none(tmp_path):
    """`promoted: no` must not read as promoted -- that is the direction
    that gets a live collection deleted."""
    diff, _ = _applied(tmp_path)
    assert gate.promoted_collection(diff) is None


def test_find_latest_applied_picks_the_newest(tmp_path, monkeypatch):
    import time

    from scripts.etl import config

    monkeypatch.setattr(config, "DIFF_REPORT_DIR", str(tmp_path))
    old_diff, old_marker = _applied(tmp_path)
    new_diff = tmp_path / "2026-08-26_0040.md"
    new_diff.write_text("# diff\n", encoding="utf-8")
    time.sleep(0.01)
    new_diff.with_suffix(".applied").write_text(
        "collection: Chunk_new\npromoted: no\n", encoding="utf-8")
    assert gate.find_latest_applied_diff() == new_diff


def test_a_diff_that_was_never_applied_is_not_a_candidate(tmp_path,
                                                          monkeypatch):
    from scripts.etl import config

    monkeypatch.setattr(config, "DIFF_REPORT_DIR", str(tmp_path))
    (tmp_path / "pending.md").write_text("# diff\n", encoding="utf-8")
    assert gate.find_latest_applied_diff() is None
