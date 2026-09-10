#!/usr/bin/env python3
"""Who signed in through Miami SSO, when, and whether it worked.

    sso_logins.py                  # everything the logs still hold
    sso_logins.py --days 7         # just the last week
    sso_logins.py --summary        # one line per person
    sso_logins.py --failures       # only refusals and IdP errors

WHY THIS EXISTS
The answer lives in ai-core/logs/app.log, NOT in journald -- `journalctl -u
chatbot` shows almost nothing, which is the first place anybody looks and
the reason this question kept coming back to the maintainer. It is also
three different log lines that have to be read together before the picture
makes sense.

WHAT THE THREE LINES MEAN

  "SSO sign-in: uid=..."          The whole round trip worked. Miami
                                  authenticated them, the assertion
                                  validated, we read a uid. They are in.

  "SSO sign-in refused for uid="  OUR refusal, and the reason matters:
                                  "not on the list" is the uid lists,
                                  "department" is SSO_REQUIRED_DEPARTMENT.
                                  Their Miami login itself was fine -- this
                                  is a successful authentication we then
                                  turned away, which is what a tester
                                  without access should see.

  "SAML assertion rejected"       THEIR side. Every one so far carried
                                  status Responder, the IdP's own code for
                                  "my end broke", and they stopped when
                                  Miami IT finished configuring on
                                  2026-09-04. If these reappear, it is not
                                  something to debug here.

A refusal is not a failure and the summary counts them apart, because
reading them together makes a working integration look broken.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import re
import sys
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parents[1] / "logs"
# Rotated files too: app.log alone covers days, not weeks, and "who has ever
# signed in" is exactly the question that reaches past one rotation.
LOG_GLOB = "app.log*"

_UID = re.compile(r"uid=(\S+?)(?:\s|$|,)")
_NAME = re.compile(r"\(([^)]+)\)")
_DEPT = re.compile(r"muohioeduDepartment=([^;]+)")


def _events(days: int | None) -> list[dict]:
    cutoff = None
    if days:
        cutoff = (dt.datetime.now() - dt.timedelta(days=days)).strftime("%Y-%m-%d")
    out: list[dict] = []
    for path in sorted(LOG_DIR.glob(LOG_GLOB)):
        try:
            raw = path.read_text(errors="replace")
        except OSError:
            continue          # a rotated file mid-compression, or not ours
        for line in raw.splitlines():
            if "SSO sign-in" not in line and "assertion rejected" not in line:
                continue
            try:
                d = json.loads(line)
            except ValueError:
                continue      # a non-JSON line in a JSON log is not our problem
            ts = str(d.get("timestamp", ""))[:19]
            if cutoff and ts[:10] < cutoff:
                continue
            msg = str(d.get("message", ""))
            uid = (_UID.search(msg) or [None, "—"])[1]
            if msg.startswith("SSO sign-in refused"):
                why = ("not on the access list" if "not on the list" in msg
                       else "department does not match" if "department" in msg
                       else "refused")
                out.append({"ts": ts, "kind": "refused", "uid": uid, "note": why})
            elif msg.startswith("SSO sign-in:"):
                name = _NAME.search(msg)
                dept = _DEPT.search(msg)
                out.append({"ts": ts, "kind": "ok", "uid": uid,
                            "note": (name.group(1) if name else ""),
                            "dept": (dept.group(1).strip() if dept else "")})
            elif "assertion rejected" in msg:
                out.append({"ts": ts, "kind": "idp_error", "uid": "—",
                            "note": "their side (Responder)"})
    out.sort(key=lambda e: e["ts"])
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--days", type=int, default=0,
                    help="only the last N days (default: everything)")
    ap.add_argument("--summary", action="store_true",
                    help="one line per person instead of per event")
    ap.add_argument("--failures", action="store_true",
                    help="only refusals and IdP errors")
    args = ap.parse_args()

    events = _events(args.days or None)
    if args.failures:
        events = [e for e in events if e["kind"] != "ok"]
    if not events:
        print("No SSO events in the logs for that window.")
        # Not an error: a quiet week is a legitimate answer, and exiting
        # non-zero would make a wrapper treat it as a fault.
        return 0

    if args.summary:
        by = collections.defaultdict(
            lambda: {"ok": 0, "refused": 0, "first": "", "last": "",
                     "name": "", "dept": ""})
        for e in events:
            if e["kind"] == "idp_error":
                continue      # nobody to attribute it to
            r = by[e["uid"]]
            r[e["kind"]] += 1
            r["first"] = r["first"] or e["ts"]
            r["last"] = e["ts"]
            r["name"] = r["name"] or e.get("note", "") if e["kind"] == "ok" else r["name"]
            r["dept"] = r["dept"] or e.get("dept", "")
        print(f"{'uid':<16}{'in':>4}{'refused':>9}  {'last seen':<20}name / why")
        for uid, r in sorted(by.items(), key=lambda kv: -kv[1]["ok"]):
            print(f"{uid:<16}{r['ok']:>4}{r['refused']:>9}  {r['last']:<20}"
                  f"{r['name'] or ''}")
        idp = sum(1 for e in events if e["kind"] == "idp_error")
        if idp:
            print(f"\n{idp} assertion(s) rejected on Miami's side. Those carry "
                  "no uid -- the IdP failed before telling us who it was.")
        return 0

    mark = {"ok": "in ", "refused": "no ", "idp_error": "ERR"}
    for e in events:
        extra = e.get("dept") or ""
        print(f"{e['ts']}  {mark[e['kind']]} {e['uid']:<16}{e['note']}"
              + (f"   [{extra}]" if extra else ""))
    ok = sum(1 for e in events if e["kind"] == "ok")
    print(f"\n{len(events)} events: {ok} signed in, "
          f"{sum(1 for e in events if e['kind'] == 'refused')} refused by us, "
          f"{sum(1 for e in events if e['kind'] == 'idp_error')} rejected by Miami.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
