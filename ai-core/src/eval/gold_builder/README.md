# gold_builder

Generates `../golden_real_traffic.jsonl` — the gold set built from
questions real people asked the bot between 2026-08-03 and 2026-09-16.

```bash
cd src/eval/gold_builder
../../../.venv/bin/python build.py
```

The JSONL is the artifact the harness reads and the thing to review; this
directory exists so the 348 rows can be edited in one place instead of
retyping a shared rubric or a URL forty times, and so `emit()` can keep
failing the build on a duplicate id or a duplicate question.

`base.py` holds the URL pool, the row constructor, and the pass that sets
`scope_library` — which is deliberately *not* read from `resolve_scope()`,
because a gold field copied from the code under test measures nothing.

One category per file. Adding a question means adding a `g(...)` call; the
rubric in `expected_answer` says what a correct reply must contain, not
what the bot said.
