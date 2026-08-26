"""Run the multi-turn scenarios against the LIVE production socket.

Not the eval harness. This connects the way the chat widget does --
websocket to /smartchatbot/socket.io, one `message` event per turn, all
turns in ONE conversation -- so what it measures is what a patron gets,
including the socket layer, the real tool surface and the conversation
history the serving path assembles.

    python -m src.eval.multiturn.run                  # all scenarios
    python -m src.eval.multiturn.run --only anaphora  # one kind
    python -m src.eval.multiturn.run --no-judge       # transcripts only

EVERY CONVERSATION IS MARKED AT THE SOURCE. The client sends the
`mu_chat_origin=staff` cookie the staff-test link sets, so these land in
the database with origin="staff" and can never be counted as patrons. That
matters more here than in the eval harness, which never touches the
production database at all.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(dotenv_path=ROOT.parent / ".env")

from src.eval.multiturn.scenarios import SCENARIOS, Scenario  # noqa: E402

BASE = os.getenv("MULTITURN_BASE_URL", "https://chatbot.lib.miamioh.edu")
SOCKET_PATH = "/smartchatbot/socket.io"
STAFF_COOKIE = "mu_chat_origin=staff"

# A turn can legitimately take a while: retrieval, an agent loop and a
# synthesis call. Long enough not to call a slow answer a missing one.
TURN_TIMEOUT_S = float(os.getenv("MULTITURN_TURN_TIMEOUT", "120"))


def run_scenario(sc: Scenario) -> dict:
    """One conversation, all its turns, through the live socket."""
    import socketio

    sio = socketio.Client(logger=False, engineio_logger=False)
    box: dict = {}

    @sio.on("message")
    def _on_message(data):  # noqa: ANN001
        box["payload"] = data

    turns: list = []
    conversation_id = None
    try:
        sio.connect(
            BASE,
            socketio_path=SOCKET_PATH,
            transports=["websocket"],
            headers={"Cookie": STAFF_COOKIE},
            wait_timeout=25,
        )
        time.sleep(1.0)
        for i, text in enumerate(sc.turns):
            box.pop("payload", None)
            started = time.monotonic()
            sio.emit("message", {"message": text})
            deadline = time.time() + TURN_TIMEOUT_S
            while time.time() < deadline and "payload" not in box:
                time.sleep(0.25)
            payload = box.get("payload") or {}
            conversation_id = payload.get("conversationId") or conversation_id
            turns.append({
                "n": i,
                "user": text,
                "bot": payload.get("message") or "",
                "intent": payload.get("intent"),
                "is_refusal": payload.get("is_refusal"),
                "stopped": payload.get("agent_stopped_reason"),
                "citations": [c.get("url") for c in (payload.get("citations") or [])
                              if isinstance(c, dict)],
                "latency_ms": int((time.monotonic() - started) * 1000),
                "answered": bool(payload),
            })
            time.sleep(0.6)
    except Exception as exc:  # noqa: BLE001 -- a dead socket is a result
        turns.append({"n": len(turns), "user": "(connection)", "bot": "",
                      "error": f"{type(exc).__name__}: {exc}", "answered": False})
    finally:
        try:
            sio.disconnect()
        except Exception:  # noqa: BLE001
            pass

    return {
        "id": sc.id,
        "kind": sc.kind,
        "expect": sc.expect,
        "conversation_id": conversation_id,
        "turns": turns,
    }


def _transcript(result: dict) -> str:
    out = []
    for t in result["turns"]:
        out.append(f"USER: {t['user']}")
        out.append(f"BOT: {t.get('bot') or '(no answer received)'}")
        if t.get("citations"):
            out.append("  links shown: " + ", ".join(t["citations"]))
    return "\n".join(out)


JUDGE_SYSTEM = """You are grading a library chatbot on ONE thing: whether it handled a MULTI-TURN conversation correctly.

You are given the full transcript and a statement of what the final answer had to do given the turns before it.

Judge ONLY the multi-turn obligation. Do not grade writing style, and do not fact-check individual claims -- a separate single-turn suite does that. A factually thin answer that correctly carries the context is a PASS here; a beautifully written answer that lost the thread is a FAIL.

Reply as JSON, nothing else:
{"verdict": "pass" | "fail" | "partial", "reason": "<one sentence, concrete>"}

- pass    -- the final answer does what the expectation requires
- partial -- it carries the context but leaves the patron short (e.g. names the right thing but withholds what they asked for)
- fail    -- the thread was lost: wrong subject, wrong building, wrong person, a fresh classification of a follow-up, or a refusal of something the earlier turns had already established"""


def judge(result: dict) -> dict:
    from langchain_core.messages import HumanMessage, SystemMessage
    from langchain_openai import ChatOpenAI

    from src.config.models import is_reasoning_model, resolve_model

    model = os.getenv("MULTITURN_JUDGE_MODEL") or resolve_model("basic")
    kwargs = {"model": model, "api_key": os.getenv("OPENAI_API_KEY", "")}
    if not is_reasoning_model(model):
        kwargs["temperature"] = 0.0
    llm = ChatOpenAI(**kwargs)
    msg = llm.invoke([
        SystemMessage(content=JUDGE_SYSTEM),
        HumanMessage(content=(
            f"Transcript:\n{_transcript(result)}\n\n"
            f"What the final answer had to do:\n{result['expect']}\n\n"
            "JSON verdict:"
        )),
    ])
    raw = (msg.content or "").strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1].lstrip("json").strip()
    try:
        return json.loads(raw)
    except Exception:  # noqa: BLE001 -- an unparseable verdict is a result
        return {"verdict": "unparsed", "reason": raw[:200]}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--only", help="Run one kind (anaphora|flow_state|carry_over|correction) or one scenario id.")
    ap.add_argument("--no-judge", action="store_true", help="Transcripts only, no LLM grading.")
    ap.add_argument("--out", default="multiturn_results.jsonl")
    args = ap.parse_args()

    picked = [s for s in SCENARIOS
              if not args.only or args.only in (s.kind, s.id)]
    if not picked:
        print(f"no scenario matches {args.only!r}", file=sys.stderr)
        return 2

    results = []
    for sc in picked:
        print(f"--- {sc.id} ({sc.kind}, {len(sc.turns)} turns)", flush=True)
        res = run_scenario(sc)
        if not args.no_judge:
            res["judge"] = judge(res)
            print(f"    {res['judge'].get('verdict')}: "
                  f"{res['judge'].get('reason','')[:100]}", flush=True)
        results.append(res)

    Path(args.out).write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in results) + "\n",
        encoding="utf-8")

    if not args.no_judge:
        from collections import Counter
        tally = Counter(r["judge"].get("verdict") for r in results)
        print("\n" + "=" * 60)
        for v in ("pass", "partial", "fail", "unparsed"):
            if tally.get(v):
                print(f"  {v:<10} {tally[v]}")
        print(f"  {'total':<10} {len(results)}")
        failed = [r for r in results if r["judge"].get("verdict") == "fail"]
        if failed:
            print("\nfailed:")
            for r in failed:
                print(f"  {r['id']}: {r['judge'].get('reason','')}")
        return 1 if failed else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
