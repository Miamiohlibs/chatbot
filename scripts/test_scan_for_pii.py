"""The scanner has two ways to fail, and only one of them is loud.

It can miss a leak. It can also fire on ordinary work, which is quieter and
worse -- people stop reading it, then they pass --no-verify by reflex, and
the control is gone while everyone still believes it is there. That is how
the .gitignore rule failed: it was present, and it matched nothing.

So the must-not-block cases below matter at least as much as the must-block
ones. They are taken from real files in this repo.

    python3 -m pytest scripts/test_scan_for_pii.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from scan_for_pii import (  # noqa: E402
    BULK_THRESHOLD_CODE,
    BULK_THRESHOLD_DATA,
    _scan_text,
    bulk_threshold,
)


def _lines(text: str):
    return list(enumerate(text.strip("\n").splitlines(), 1))


def _verdict(path: str, text: str) -> str:
    secrets, people = _scan_text(_lines(text))
    if secrets:
        return "blocked-credential"
    if sum(len(v) for v in people.values()) >= bulk_threshold(path):
        return "blocked-bulk"
    return "pass"


# --- must block: the shapes the accident actually takes -------------------


def test_patron_roster_csv_is_blocked():
    """The leak, reproduced: a spreadsheet of people."""
    assert _verdict("patrons.csv", """
name,email,phone
Patron One,patron-one@miamioh.edu,513-555-0142
Patron Two,patron-two@miamioh.edu,513-555-0198
Patron Three,patron-three@miamioh.edu,513-555-0110
Patron Four,patron-four@miamioh.edu,513-555-0177
""") == "blocked-bulk"


def test_transcript_export_jsonl_is_blocked():
    """Same data, a file extension that no spreadsheet rule would catch.
    This is why bulk counting exists alongside the suffix check."""
    assert _verdict("chats.jsonl", """
{"user":"patron-one@miamioh.edu","q":"can i renew my books"}
{"user":"patron-two@miamioh.edu","q":"where is king library"}
{"user":"patron-three@miamioh.edu","q":"printing on regionals"}
{"user":"patron-four@miamioh.edu","q":"3d printer hours"}
""") == "blocked-bulk"


def test_patron_ip_addresses_count_as_people():
    """The LibChat records that leaked carried IPs, not just names."""
    assert _verdict("access.log", """
2026-07-01 10.14.22.8 GET /chat
2026-07-01 10.14.22.9 GET /chat
2026-07-01 10.14.23.4 GET /chat
2026-07-01 10.14.23.9 GET /chat
""") == "blocked-bulk"


def test_one_api_key_is_enough():
    assert _verdict("config.py",
                    'OPENAI_API_KEY = "sk-proj-NOTAREALKEYNOTAREALKEY000000"'
                    ) == "blocked-credential"


def test_private_key_block_is_enough():
    assert _verdict("deploy.pem",
                    "-----BEGIN RSA PRIVATE KEY-----") == "blocked-credential"


# --- must NOT block: real content from this repo ---------------------------


def test_library_service_number_passes():
    """The bot's job is handing this out. If answering a patron trips the
    leak scanner, the scanner is wrong."""
    assert _verdict("src/graph/new_orchestrator.py", """
FALLBACK = "You can reach us at 513-529-4141 or ask at the desk."
""") == "pass"


def test_repeated_test_fixture_passes():
    """Counted DISTINCT, so twenty uses of one fake address is one person.
    This is the commonest innocent pattern in the test suite."""
    assert _verdict("src/synthesis/test_corrections.py", "\n".join(
        ['    save(created_by="jane.librarian@miamioh.edu")'] * 20
    )) == "pass"


def test_operator_allowlist_test_passes():
    """test_killswitch.py necessarily names several operators -- it tests an
    allowlist. At a flat threshold of 8 this blocked, and replaying real
    commits is how that was caught."""
    assert _verdict("src/api/admin/test_killswitch.py", """
ALLOWED = "op-one@miamioh.edu,op-two@miamioh.edu,op-three@miamioh.edu"
def test_rejects_stranger():
    assert not check("stranger@miamioh.edu")
def test_case_insensitive():
    assert check("OP-ONE@miamioh.edu") and check("Op-One@MiamiOH.edu")
def test_blank_is_refused():
    assert not check("") and not check("a@miamioh.edu") and not check("b@miamioh.edu")
""") == "pass"


def test_env_example_placeholders_pass():
    assert _verdict(".env.example", """
OPENAI_API_KEY=sk-proj-xxxxxxxxxxxxxxxxxxxx
ALERT_EMAIL_TO=you@example.com
DATABASE_URL=postgresql://user:changeme@localhost:5432/db
KILLSWITCH_PASSPHRASE=REPLACE-ME
""") == "pass"


def test_subject_librarian_answer_passes():
    """Naming the right librarian IS the answer to a subject question."""
    assert _verdict("src/tools/subject_aliases.py", """
HISTORY = ("A Subject Librarian", "subject-librarian@miamioh.edu")
""") == "pass"


# --- the calibration itself ------------------------------------------------


def test_data_files_are_held_to_a_stricter_standard():
    """An export needs four strangers to trip; source needs twelve. The
    accident arrives as a data file, so that is where the line is tight."""
    assert bulk_threshold("export.csv") == BULK_THRESHOLD_DATA
    assert bulk_threshold("dump.jsonl") == BULK_THRESHOLD_DATA
    assert bulk_threshold("src/main.py") == BULK_THRESHOLD_CODE
    assert bulk_threshold("docs/guide.md") == BULK_THRESHOLD_CODE
    assert BULK_THRESHOLD_DATA < BULK_THRESHOLD_CODE
