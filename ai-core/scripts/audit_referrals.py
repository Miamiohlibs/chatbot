"""Check every person the bot names against the liaison directory.

WHY THIS EXISTS
    The Head of Advise & Instruct asked, 2026-08-12, whether the bot
    PREDICTS which staff member to contact, and said his staff's major
    concern is "receiving referrals from the bot that don't make sense, and
    having to recover/redirect frustrated clientele". He asked to see the
    feature in good operation before approving it.

    An assurance is not evidence. This is the instrument: it asks the live
    bot a battery of referral questions, pulls out every person it names,
    and checks each one against the Librarian/Subject tables that are synced
    from the published liaison directory. It prints a table, and it exits
    non-zero if anything is wrong, so it can be re-run before any release
    and by anyone who wants to see for themselves.

WHAT COUNTS AS A FAILURE
    * naming somebody who is not in the roster at all
    * naming somebody for a subject they are not the liaison for
    * naming ANYBODY for a subject the directory does not cover -- the
      honest answer there is "no liaison listed", and inventing a plausible
      neighbour is precisely the complaint

    Refusing to answer a question it should have answered is reported too,
    separately: it is a quality problem rather than a wrong referral, and
    the two deserve different responses.

THE PASS COUNT IS NOISY. THE WRONG-REFERRAL COUNT IS NOT.
    Every question here goes through the agent, which decides for itself
    whether to call the lookup, and that decision varies. Measured
    2026-08-12: the SAME code, run twice in a row, scored 23/36 and 22/36,
    and across a morning of changes the figure moved between 22 and 30
    without a clean causal story. Several of those points were run-to-run
    variance being read as cause and effect.

    So do not tune against this number. A single run says almost nothing
    about a few points either way; use it to catch a COLLAPSE, and use the
    per-question marks to see which questions are unstable.

    What has been stable across every run is the thing that matters: zero
    wrong referrals, six runs out of six. That is the number to defend, and
    it is a property of the guards, not of the model's mood.

    For judging whether a change to the referral logic worked, prefer the
    unit tests -- they call the functions directly and are deterministic.

WHAT IT DELIBERATELY DOES NOT DO
    It does not check whether the liaison list itself is right. That is the
    library's data, not the bot's behaviour.

USAGE
    python -m scripts.audit_referrals              # one pass
    python -m scripts.audit_referrals --repeat 3   # also measures flakiness
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from collections import defaultdict

URL = "http://127.0.0.1:8081"
PATH = "/smartchatbot/socket.io"

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@miamioh\.edu", re.IGNORECASE)
REFUSAL = "don't have a reliable answer"


# (question, expectation)
#   ("liaison", "<subject as the directory spells it>") -- must name that
#       subject's liaison and nobody else
#   ("nobody",) -- must name no one; the directory does not cover this
#   ("someone",) -- a named service contact; must be in the roster
BATTERY: "tuple[tuple[str, tuple], ...]" = (
    # plainly named subjects
    ("who is the librarian for chemistry", ("liaison", "Chemistry and Biochemistry")),
    ("I need the history librarian", ("liaison", "History")),
    ("who is the nursing librarian", ("liaison", "Nursing")),
    ("who do I talk to about psychology research", ("liaison", "Psychology")),

    # the department a programme sits in, not the programme's own name --
    # this is the case that looks like a bad match and is not
    ("who is the liaison for paper science and engineering",
     ("liaison", "Chemical, Paper, and Biomedical Engineering")),

    # a topic, not a subject name: the model has to choose what to look up,
    # which is the step the Head of Advise & Instruct asked about
    ("I need help with competitive intelligence research", ("someone",)),
    ("who can help me find market share data", ("someone",)),

    # named services with an explicit, hand-maintained owner
    ("who do I contact about special collections", ("someone",)),
    ("who is the makerspace contact", ("someone",)),

    # nothing in the directory covers these; naming anyone is the failure
    ("who is the librarian for underwater basket weaving", ("nobody",)),
    ("who is the liaison for astrology", ("nobody",)),
    ("who is the quidditch librarian", ("nobody",)),
)


async def ask(question: str) -> str:
    import socketio

    sc = socketio.AsyncClient(reconnection=False)
    box: list = []
    sc.on("message", lambda d: box.append((d or {}).get("message", "")))
    await sc.connect(URL, socketio_path=PATH, transports=["websocket"],
                     wait_timeout=10)
    await sc.emit("message", question)
    for _ in range(600):
        if box:
            break
        await asyncio.sleep(0.1)
    try:
        await sc.disconnect()
    except Exception:  # noqa: BLE001
        pass
    return box[0] if box else ""


def roster() -> "tuple[dict, dict]":
    """(email -> name, subject -> {emails}) from the synced tables."""
    import subprocess

    def q(sql: str) -> "list[str]":
        r = subprocess.run(
            ["docker", "exec", "chatbot-postgres", "psql", "-U", "myuser",
             "-d", "smartchatbot", "-tAc", sql],
            capture_output=True, text=True)
        if r.returncode != 0:
            r = subprocess.run(
                ["sudo", "docker", "exec", "chatbot-postgres", "psql", "-U",
                 "myuser", "-d", "smartchatbot", "-tAc", sql],
                capture_output=True, text=True)
        return [ln for ln in r.stdout.splitlines() if ln.strip()]

    people = {}
    for ln in q('SELECT lower(email)||\'|\'||name FROM "Librarian" '
                'WHERE email IS NOT NULL;'):
        e, _, n = ln.partition("|")
        people[e.strip()] = n.strip()

    by_subject: "dict[str, set]" = defaultdict(set)
    for ln in q('SELECT s.name||\'|\'||lower(l.email) FROM "Subject" s '
                'JOIN "LibrarianSubject" ls ON ls."subjectId"=s.id '
                'JOIN "Librarian" l ON l.id=ls."librarianId" '
                'WHERE l.email IS NOT NULL;'):
        s, _, e = ln.partition("|")
        by_subject[s.strip().lower()].add(e.strip())
    return people, by_subject


def judge(answer: str, expect: tuple, people: dict, by_subject: dict) -> tuple:
    """-> (verdict, detail). verdict in {ok, WRONG, refused, unverified}."""
    named = {e.lower() for e in EMAIL_RE.findall(answer)}
    # the bot's own contact points are not referrals to a person
    named = {e for e in named if not e.startswith(("speccoll@", "ill@", "mia-ill@"))}

    if REFUSAL in answer:
        return "refused", "no answer given"

    kind = expect[0]
    if kind == "nobody":
        if named:
            return "WRONG", f"named {sorted(named)} for a subject with no liaison"
        return "ok", "named nobody, as it should"

    unknown = [e for e in named if e not in people]
    if unknown:
        return "WRONG", f"{unknown} is not in the librarian roster"

    if kind == "someone":
        if not named:
            return "refused", "named nobody"
        return "ok", f"{sorted(named)} (all in roster)"

    subject = expect[1].lower()
    expected = by_subject.get(subject, set())
    if not expected:
        return "unverified", f"'{expect[1]}' has no liaison row to check against"
    if not named:
        return "refused", f"named nobody for {expect[1]}"
    wrong = named - expected
    if wrong:
        return "WRONG", (f"named {sorted(wrong)} for {expect[1]}, whose liaison "
                         f"is {sorted(expected)}")
    return "ok", f"{sorted(named)} matches the directory"


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repeat", type=int, default=1,
                    help="ask each question N times, to expose flakiness")
    args = ap.parse_args()

    people, by_subject = roster()
    print(f"roster: {len(people)} librarians, "
          f"{len(by_subject)} subjects with a liaison\n")

    tally: "dict[str, int]" = defaultdict(int)
    bad: list = []
    for question, expect in BATTERY:
        verdicts = []
        for _ in range(args.repeat):
            answer = await ask(question)
            v, detail = judge(answer, expect, people, by_subject)
            verdicts.append((v, detail))
            tally[v] += 1
            if v == "WRONG":
                bad.append((question, detail))
            await asyncio.sleep(1.0)

        shown = verdicts[0][1]
        marks = "".join({"ok": ".", "WRONG": "X", "refused": "r",
                         "unverified": "?"}[v] for v, _ in verdicts)
        print(f"  [{marks}] {question}")
        print(f"        {shown}")

    total = sum(tally.values())
    print(f"\n  {tally['ok']}/{total} correct, {tally['WRONG']} wrong referrals, "
          f"{tally['refused']} refused, {tally['unverified']} unverifiable")
    if bad:
        print("\n  WRONG REFERRALS -- these are the ones that matter:")
        for q, d in bad:
            print(f"    {q}\n      {d}")
    print("\n  legend: . correct   X wrong referral   r refused   ? unverifiable")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
