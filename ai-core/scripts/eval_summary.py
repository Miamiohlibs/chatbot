#!/usr/bin/env python3
"""Reduce an eval run to the part that belongs in a public repo.

    eval_summary.py <run-dir> <out.jsonl>

WHY
    A run's per-case output carries `bot_answer` and `judge_reason`, and a
    good answer to "who is the biology librarian" contains a name, an email
    and a telephone number. Across 349 questions that is 141 contact
    occurrences in 3.4 MB of regenerable log -- which is the
    spreadsheet-of-people shape scan_for_pii.py exists to stop, and it
    stopped it. The content happened to be the published staff directory
    this time. The shape is the risk, not this batch.

    So the RAW output lives in /opt/chatbot-private-data/eval/ with the
    conversation exports, and this writes the reviewable half: which
    question got which verdict. That is what a score comparison actually
    needs, and it carries no contact details at all.

    Verified by the same scanner. If a field is ever added here that
    reintroduces answer text, the scanner will say so before the commit.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

KEEP = ("question_id", "category", "judge_verdict", "judge_citation_validity",
        "intent_match", "path_match", "scope_match", "actual_intent",
        "actual_path", "bot_was_refusal", "bot_refusal_trigger",
        "model_used", "bot_citations_count", "latency_ms")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("run_dir", type=pathlib.Path)
    ap.add_argument("out", type=pathlib.Path)
    args = ap.parse_args()

    rows = []
    for p in sorted(args.run_dir.glob("*.jsonl")):
        for line in p.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                rows.append({k: r.get(k) for k in KEEP})
    rows.sort(key=lambda r: (r["category"] or "", r["question_id"] or ""))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as f:
        f.write(f"// {args.run_dir.name}: {len(rows)} cases. Verdicts only --\n"
                f"// the answers and the judge's reasoning are in\n"
                f"// /opt/chatbot-private-data/eval/{args.run_dir.name}/\n")
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"{len(rows)} cases -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
