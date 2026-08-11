"""Refuse to let patron or staff data reach a public repository again.

WHY THIS EXISTS
    A CSV carrying patron PII and staff details was committed and pushed to
    a public GitHub repo. The only defence at the time was .gitignore, and
    it was one directory level off, so it matched nothing and nobody
    noticed. .gitignore is a convenience, not a control: it cannot see a
    file added with `-f`, it cannot see a file already tracked, and it says
    nothing about the CONTENTS of a file whose name looks innocent.

    This looks at content, and it runs before the commit rather than after
    the push.

WHAT IT BLOCKS, AND WHY IT IS NOT JUST "ANY EMAIL"
    A scanner that fires on every commit gets bypassed within a fortnight,
    and a bypassed scanner protects nothing. So the rules below are shaped
    like the actual accident rather than like a regex sweep. The repo today
    holds ~450 email/phone matches -- library service numbers the bot is
    SUPPOSED to hand out, the public subject-librarian directory, and unit
    test fixtures. None of those is a leak, and blocking them would train
    everyone to reach for --no-verify.

    Three rules, each aimed at a way the real accident happens:

      1. CREDENTIALS -- one is enough. An API key or private key in a diff
         is never a fixture and never a false alarm worth tolerating.

      2. BULK PERSONAL DATA -- many DISTINCT people in one file. This is
         the spreadsheet-of-patrons shape. Counting distinct values is what
         separates it from a test that repeats one fake address twenty
         times, which is the single most common innocent pattern here.

      3. NEW SPREADSHEETS -- a .csv/.tsv/.xlsx being ADDED. Every such file
         in this repo today is a one-time input to a converter, none is
         read at runtime, and the leak arrived as exactly this. Adding one
         should require saying so out loud.

    Anything below those thresholds prints as a NOTE and does not block.
    The point is that a human sees it, not that the machine is certain.

MODES
    --staged        added lines of the pending commit (the pre-commit hook)
    --diff BASE     added lines since BASE (what CI runs on a PR)
    --all           every tracked file, whole (the audit; never used to gate)

EXIT CODES
    0 nothing blocking, 1 blocked, 2 usage error.

BYPASS
    `git commit --no-verify` skips this, deliberately -- a hook that cannot
    be overridden gets uninstalled instead. That is exactly why the same
    check also runs in CI, where the person bypassing is not the person
    approving.
"""

from __future__ import annotations

import argparse
import re
import subprocess
from collections import defaultdict
from pathlib import Path

# --- credentials: one is enough -------------------------------------------

SECRET_PATTERNS: "tuple[tuple[str, str], ...]" = (
    ("openai-style api key", r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    ("google api key", r"\bAIza[A-Za-z0-9_-]{20,}\b"),
    ("aws access key", r"\bAKIA[0-9A-Z]{16}\b"),
    ("private key block", r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----"),
    ("github token", r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    ("slack token", r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b"),
    # An assignment with a real-looking literal. Placeholder-ish values are
    # filtered by ALLOW below, which is what keeps .env.example quiet.
    ("hardcoded secret", r"(?i)\b(?:password|passwd|secret|api_?key|token)\s*"
                         r"[=:]\s*['\"][^'\"\s]{12,}['\"]"),
)

# --- personal data: counted, not individually fatal ------------------------

PERSON_PATTERNS: "tuple[tuple[str, str], ...]" = (
    ("miami email", r"\b[A-Za-z0-9._%+-]+@miamioh\.edu\b"),
    ("email", r"\b[A-Za-z0-9._%+-]+@(?!miamioh\.edu)[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    ("us phone", r"(?<!\d)(?:\(\d{3}\)\s*|\d{3}[-.\s])\d{3}[-.\s]?\d{4}(?!\d)"),
    ("ip address", r"(?<!\d)(?:\d{1,3}\.){3}\d{1,3}(?!\d)"),
    ("banner id", r"\b\+\d{9}\b"),
)

# How many DISTINCT people in one file before it looks like a roster rather
# than a fixture. Two thresholds, because the accident has a shape: data
# files are where exports land, and source files are where fixtures live.
#
# Calibrated by replaying the last fifteen real commits through this check.
# At a flat 8, `test_killswitch.py` blocked -- it tests an email ALLOWLIST,
# so it necessarily names several operators, and there is no version of
# that test that names one. A hook that blocks one commit in fifteen is a
# hook that gets uninstalled, so source files were relaxed to 12 (the
# leaked file had thousands of rows; nothing real sits between 8 and 12).
#
# Data files went the other way, to 4. An export with four different people
# in it is already the thing we are trying to stop, and no legitimate
# .json/.jsonl in this repo needs to introduce four strangers at once.
BULK_THRESHOLD_CODE = 12
BULK_THRESHOLD_DATA = 4

SPREADSHEET_SUFFIXES = {".csv", ".tsv", ".xlsx", ".xls"}
DATA_SUFFIXES = SPREADSHEET_SUFFIXES | {
    ".json", ".jsonl", ".ndjson", ".sql", ".dump", ".bak", ".log",
}


def bulk_threshold(path: str) -> int:
    return (BULK_THRESHOLD_DATA if Path(path).suffix.lower() in DATA_SUFFIXES
            else BULK_THRESHOLD_CODE)

# Substrings that make a match uninteresting: the library's own published
# contact details (the bot exists to repeat these), documentation
# placeholders, and non-routable addresses.
ALLOW: "tuple[str, ...]" = (
    "529-4141", "529-2433", "529-3935", "529-2789", "529-1567", "529-6638",
    "example.com", "example.org", "example.edu", "@x.example",
    "you@", "someone@", "user@", "test@", "foo@", "bar@", "noreply@",
    "your-", "<your", "REPLACE", "changeme", "CHANGE_ME", "placeholder",
    "xxxxx", "XXXXX", "sk-proj-xxx", "sk-...", "...",
    "127.0.0.1", "0.0.0.0", "255.255.255", "localhost", "8.8.8.8",
)


# The one exemption, and the only one that should ever exist.
#
# A test for a leak scanner has to contain leak specimens -- a fake API key
# that does not match the API-key pattern tests nothing. So this file is
# skipped, and the specimens inside it are invented (the names and the key
# are not anybody's).
#
# Before adding a second entry here, be suspicious: every other case that
# looks like it needs one is really a request to loosen a threshold, and
# the thresholds are calibrated and tested. An exemption is invisible in a
# way a threshold is not -- it is a file nobody scans again, ever.
EXEMPT_PATHS: "dict[str, str]" = {
    "scripts/test_scan_for_pii.py":
        "must contain specimens of what it blocks, or it tests nothing",
}


def _interesting(text: str) -> bool:
    return not any(a in text for a in ALLOW)


def _scan_text(lines: "list[tuple[int, str]]") -> "tuple[list, dict]":
    """-> (credential findings, {label: {distinct values}})."""
    secrets = []
    people: "dict[str, set]" = defaultdict(set)
    for lineno, line in lines:
        if not _interesting(line):
            continue
        for label, pattern in SECRET_PATTERNS:
            for m in re.finditer(pattern, line):
                if _interesting(m.group(0)):
                    secrets.append((lineno, label, m.group(0)))
        for label, pattern in PERSON_PATTERNS:
            for m in re.finditer(pattern, line):
                hit = m.group(0)
                if _interesting(hit):
                    people[label].add(hit.lower())
    return secrets, people


# --- where the lines come from --------------------------------------------


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True).stdout


def _added_lines(diff_args: "list[str]") -> "dict[str, list[tuple[int, str]]]":
    """Parse a unified diff into {path: [(line number, added line)]}.

    Only ADDED lines. Touching a file that already contains fixtures must
    not block the commit -- only what this change introduces counts.
    """
    out = _git("diff", *diff_args, "--unified=0", "--no-color",
               "--diff-filter=ACM")
    per_file: "dict[str, list[tuple[int, str]]]" = defaultdict(list)
    path = None
    lineno = 0
    for line in out.splitlines():
        if line.startswith("+++ b/"):
            path = line[6:]
        elif line.startswith("@@"):
            m = re.search(r"\+(\d+)", line)
            lineno = int(m.group(1)) if m else 0
        elif line.startswith("+") and not line.startswith("+++"):
            if path:
                per_file[path].append((lineno, line[1:]))
            lineno += 1
    return per_file


def _added_paths(diff_args: "list[str]") -> "list[str]":
    """Files this change ADDS (not modifies)."""
    out = _git("diff", *diff_args, "--name-only", "--diff-filter=A")
    return [f for f in out.splitlines() if f.strip()]


def _whole_tracked() -> "dict[str, list[tuple[int, str]]]":
    per_file = {}
    for f in _git("ls-files").splitlines():
        p = Path(f)
        if not p.is_file():
            continue
        try:
            if b"\0" in p.open("rb").read(4096):
                continue
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        per_file[f] = list(enumerate(text.splitlines(), 1))
    return per_file


# --- reporting -------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Block patron/staff data and credentials from being committed.")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--staged", action="store_true",
                   help="added lines of the pending commit")
    g.add_argument("--diff", metavar="BASE",
                   help="added lines since BASE (CI)")
    g.add_argument("--all", action="store_true",
                   help="every tracked file, whole -- audit only, never gates")
    args = ap.parse_args()

    if args.staged:
        diff_args = ["--cached"]
    elif args.diff:
        diff_args = [f"{args.diff}...HEAD"]
    else:
        diff_args = None

    if diff_args is None:
        per_file = _whole_tracked()
        new_sheets: "list[str]" = []
    else:
        per_file = _added_lines(diff_args)
        new_sheets = [f for f in _added_paths(diff_args)
                      if Path(f).suffix.lower() in SPREADSHEET_SUFFIXES]

    blocking: "list[str]" = []
    notes: "list[str]" = []
    exempted: "list[str]" = []

    for path, lines in sorted(per_file.items()):
        if path in EXEMPT_PATHS:
            exempted.append(f"  exempt: {path} -- {EXEMPT_PATHS[path]}")
            continue
        secrets, people = _scan_text(lines)
        for lineno, label, hit in secrets:
            shown = hit[:12] + "..." if len(hit) > 15 else hit
            blocking.append(f"  CREDENTIAL  {path}:{lineno}  {label}: {shown}")

        distinct = sum(len(v) for v in people.values())
        if not distinct:
            continue
        detail = ", ".join(f"{len(v)} {k}" for k, v in sorted(people.items()))
        if distinct >= bulk_threshold(path):
            blocking.append(
                f"  BULK DATA   {path}  {distinct} distinct values ({detail})")
        else:
            notes.append(f"  note: {path}  {detail}")

    for f in new_sheets:
        blocking.append(f"  SPREADSHEET {f}  a new .{f.rsplit('.', 1)[-1]} is being added")

    # Always print exemptions. A rule that skips something silently is how
    # the .gitignore miss went unnoticed for months.
    if exempted:
        print("\nSkipped by exemption:")
        print("\n".join(exempted))

    if notes and not args.all:
        print("\nPersonal-looking values in this change (not blocking):")
        print("\n".join(notes))

    if args.all:
        # Audit mode reports but never fails: the existing repo has ~450
        # legitimate matches, and a red audit that is always red is noise.
        if blocking:
            print("\nAudit -- worth a human eye:")
            print("\n".join(blocking))
        print(f"\n  {len(per_file)} tracked text file(s) scanned. "
              f"Audit does not gate; use --staged or --diff for that.")
        return 0

    if blocking:
        print("\nBLOCKED -- this change looks like it carries data, not code:\n")
        print("\n".join(blocking))
        print(
            "\nNothing was committed.\n"
            "  * A credential: rotate it, then remove it. Do not just amend --\n"
            "    if it was ever pushed, treat it as public.\n"
            "  * A roster or export: it belongs in /opt/chatbot-private-data/,\n"
            "    not in git. This repo is public.\n"
            "  * A spreadsheet you are sure is safe: say so in the commit\n"
            "    message and re-run with `git commit --no-verify`. CI will\n"
            "    still flag it, which is the point -- somebody else sees it.\n")
        return 1

    print(f"  scan clean -- {len(per_file)} file(s) checked")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
