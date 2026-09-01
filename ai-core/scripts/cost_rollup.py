"""
Daily cost-rollup cron job.

Reads ModelTokenUsage rows from the previous day, multiplies tokens by
the current OpenAI per-model price, writes one DailyCost row per
(date, model) pair. The dashboard reads DailyCost for trend charts
and the alert-on-anomaly check.

Without this, a prompt-prefix drift that tanks the cache hit rate
burns budget silently for weeks before anyone notices. That's the
exact failure mode the plan calls out under Operations Op 3 "Cost
tracking".

Run via cron: `0 2 * * *` (2 AM daily, after the day's traffic is
logged and before the morning digest email).

Usage:
    python -m scripts.cost_rollup                 # roll up yesterday
    python -m scripts.cost_rollup --date 2026-04-22
    python -m scripts.cost_rollup --backfill 30   # last 30 days

Status: SCAFFOLD. Prisma isn't importable in the sandbox. The logic
is structured as pure functions around `compute_daily_cost()` so the
business logic is testable without the DB; the DB read/write is a
thin wrapper that's easy to add.
"""

from __future__ import annotations

import re

import argparse
import asyncio
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Optional


logger = logging.getLogger("cost_rollup")


# --- Price table ---------------------------------------------------------
#
# USD per 1M tokens. Kept as a module constant (not a YAML / DB
# config) because (a) pricing changes are rare and deliberate,
# (b) grep-ability matters -- "where did we get that $X number" should
# resolve to a file, not a DB row.
#
# Rates re-read 2026-09-01 against OpenAI's pricing pages.
#
# An UNKNOWN model -> compute_cost_usd returns $0 and logs a WARN: the
# rollup still records the token counts, it just can't price them. A
# guessed rate would be worse than a flagged $0, so that stays.
#
# What did NOT stay: this comment used to offer a dated model snapshot as
# an example of a harmlessly-unknown model. It was not harmless. That model
# served 1,518 production turns from 2025-12-17 to 2026-05-12, and every
# cost report for that period read $0.00. Two consequences:
#   1. dated snapshots now normalise to their base model (normalise_model),
#      so pinning a version no longer zeroes the bill;
#   2. anything that shows money to a human must call is_priced() and
#      print "unpriced", because a silent $0 is indistinguishable from
#      free and that is precisely how five months went unbilled.
# Operator-maintained: add a row when a new model ships.

PRICE_PER_1M_TOKENS: dict[str, dict[str, float]] = {
    # $ per 1M tokens: input / cached input / output.
    #
    # ONLY the GPT-5.6 line plus the embedding model. Operator ruling
    # 2026-09-01: nothing below 5.6 is kept anywhere in this codebase, so the
    # twenty legacy rows that used to live here are gone.
    #
    # Safe, and checked rather than assumed: every DailyCost row ever written
    # by a pre-5.6 model totals $0.02, across three rows in July 2026 and one
    # in May. `usd` is computed at rollup time and STORED,
    # so dropping a price cannot move a number already banked, and the
    # ModelTokenUsage rows behind those two days no longer exist (that table
    # starts 2026-08-03) so a re-roll could not recompute them either.
    #
    # If a non-5.6 name ever reappears, compute_cost_usd returns 0.0 AND logs a
    # warning, and is_priced() reports False so anything shown to a human reads
    # "unpriced" rather than "$0". That safety net is why this table can be
    # short -- it is what the old long table was compensating for.
    #
    # Rates read off OpenAI's pricing pages on 2026-09-01.
    #
    # KNOWN LIMITATION, worth saying out loud: this is ONE price per model, and
    # it prices historical rows at TODAY's rate. When a price changes, past
    # reports move with it. Proper reconciliation would need effective-dated
    # prices; until then, treat old totals as indicative, not invoice-grade.

    # --- GPT-5.6 -------------------------------------------------------------
    # Sol is priced but NOT wired: no tier points at it. It is here so the
    # operator can move REASONING onto it without the most expensive model on
    # the menu silently billing $0 -- which is exactly how a retired model
    # once ran five months unbilled.
    #
    # Sol FELL to this rate on 2026-08-21, from 5.00 / 0.50 / 30.00. OpenAI
    # calls it promotional through at least 2026-11-21; if that lapses, this
    # row goes back up and every past total moves with it (see above).
    "gpt-5.6-sol": {"input": 4.00, "cached_input": 0.40, "output": 20.00},
    "gpt-5.6-terra": {"input": 2.00, "cached_input": 0.20, "output": 12.00},
    "gpt-5.6-luna": {"input": 0.20, "cached_input": 0.02, "output": 1.20},

    # --- Embeddings ----------------------------------------------------------
    # Input-only: embeddings have no output tokens, hence 0.0. cached_input is
    # set EQUAL to input because OpenAI does not discount cached embedding
    # input -- not because the number is unknown.
    "text-embedding-3-large": {
        "input": 0.13,
        "cached_input": 0.13,
        "output": 0.0,
    },
}

# OpenAI pins dated snapshots ("<model>-2026-08-21"), and pinned ids appear in
# our own history. They bill as the base model, so strip the date rather than
# requiring a table row per snapshot -- otherwise every pin is another silent
# $0.
_DATED_SNAPSHOT_RE = re.compile(r"^(.*?)-(\d{4}-\d{2}-\d{2})$")


def normalise_model(model: str) -> str:
    """Base model id for pricing: strips a trailing -YYYY-MM-DD snapshot."""
    m = _DATED_SNAPSHOT_RE.match((model or "").strip())
    return m.group(1) if m else (model or "").strip()


# --- Data shapes ----------------------------------------------------------


@dataclass(frozen=True)
class UsageRow:
    """One ModelTokenUsage row, plus the call_site column added for
    per-site cost attribution."""

    model: str
    input_tokens: int
    cached_input_tokens: int
    output_tokens: int
    call_site: str = "unknown"


@dataclass(frozen=True)
class DailyCostRow:
    """One DailyCost row -- the output of rollup. One row per
    (date, model, call_site) to match the DailyCost @@unique key, so
    the dashboard answers "which part of the pipeline costs money"
    (synthesizer vs judge vs agent), not just "terra in general"."""

    the_date: date
    model: str
    call_site: str
    input_tokens: int
    cached_input_tokens: int
    output_tokens: int
    call_count: int
    usd: float

    def as_dict(self) -> dict:
        return {
            "date": self.the_date.isoformat(),
            "model": self.model,
            "call_site": self.call_site,
            "input_tokens": self.input_tokens,
            "cached_input_tokens": self.cached_input_tokens,
            "output_tokens": self.output_tokens,
            "call_count": self.call_count,
            "usd": round(self.usd, 4),
        }


# --- Pure rollup logic ---------------------------------------------------


def compute_cost_usd(
    model: str,
    input_tokens: int,
    cached_input_tokens: int,
    output_tokens: int,
) -> float:
    """Compute USD cost for one usage row.

    Unknown models return 0.0 and log a warning. Treat unknown models
    as cost-free rather than crashing -- an experimental model
    mis-deployed shouldn't block the rollup for everyone else.

    $0 is safe for the ROLLUP but dangerous as a REPORT: a retired model
    served 1,518 turns unpriced and read as free on every cost page. Anything
    that displays a total must call `is_priced()` and say "unpriced"
    out loud rather than printing a $0 that looks like a real zero.

    NOTE: `input_tokens` in the OpenAI billing model is the TOTAL
    input tokens (including the cached portion). The cached portion
    gets a discount; the uncached portion is billed at full rate. So
    billable_uncached = input_tokens - cached_input_tokens.
    """
    rates = PRICE_PER_1M_TOKENS.get(normalise_model(model))
    if rates is None:
        logger.warning(
            "Unknown model %s -- treating as $0 for rollup (add to PRICE_PER_1M_TOKENS)",
            model,
        )
        return 0.0

    uncached = max(0, input_tokens - cached_input_tokens)
    cached = min(cached_input_tokens, input_tokens)
    return (
        uncached * rates["input"] / 1_000_000
        + cached * rates["cached_input"] / 1_000_000
        + output_tokens * rates["output"] / 1_000_000
    )


def is_priced(model: str) -> bool:
    """True if we can actually price this model.

    Callers that show money to a human MUST branch on this: a $0 from
    compute_cost_usd means either "genuinely free" or "we have no idea",
    and those must not look the same on a dashboard.
    """
    return normalise_model(model) in PRICE_PER_1M_TOKENS


def rollup_by_model(
    usage_rows: list[UsageRow], the_date: date
) -> list[DailyCostRow]:
    """Aggregate a day's usage into one DailyCostRow per
    (model, call_site). Name kept for back-compat with callers; it now
    rolls up per (model, call_site) per the operator's Option-A
    decision (the DailyCost @@unique key is (date, model, callSite)).
    `call_count` = number of ModelTokenUsage rows in that bucket."""
    totals: dict[tuple[str, str], dict] = {}
    for r in usage_rows:
        key = (r.model, r.call_site or "unknown")
        t = totals.setdefault(
            key, {"input": 0, "cached": 0, "output": 0, "n": 0}
        )
        t["input"] += r.input_tokens
        t["cached"] += r.cached_input_tokens
        t["output"] += r.output_tokens
        t["n"] += 1

    return [
        DailyCostRow(
            the_date=the_date,
            model=model,
            call_site=call_site,
            input_tokens=t["input"],
            cached_input_tokens=t["cached"],
            output_tokens=t["output"],
            call_count=t["n"],
            usd=compute_cost_usd(
                model, t["input"], t["cached"], t["output"]
            ),
        )
        for (model, call_site), t in totals.items()
    ]


def anomaly_ratio(today_total: float, trailing_avg: float) -> float:
    """Return today's spend as a multiple of the trailing 7-day average.

    Alert threshold per plan Op 3: ratio >= 1.5 pages Slack/email
    ("daily token cost > 1.5x the 7-day average").
    """
    if trailing_avg <= 0:
        return 0.0
    return today_total / trailing_avg


# --- DB wrapper (gated) ---------------------------------------------------


async def _aload_usage_rows(the_date: date) -> list[UsageRow]:
    from prisma import Prisma  # type: ignore

    # [00:00, next 00:00) UTC for the bucket date. createdAt is
    # timestamptz; tz-aware bounds avoid an off-by-a-few-hours bleed.
    start = datetime(
        the_date.year, the_date.month, the_date.day, tzinfo=timezone.utc
    )
    end = start + timedelta(days=1)
    db = Prisma()
    await db.connect()
    try:
        recs = await db.modeltokenusage.find_many(
            where={"createdAt": {"gte": start, "lt": end}}
        )
    finally:
        await db.disconnect()
    return [
        UsageRow(
            model=getattr(r, "llmModelName", "") or "unknown",
            input_tokens=getattr(r, "promptTokens", 0) or 0,
            cached_input_tokens=getattr(r, "cachedInputTokens", 0) or 0,
            output_tokens=getattr(r, "completionTokens", 0) or 0,
            # Legacy rows have callSite=None -> bucket as "unknown"
            # (DailyCost.callSite is a non-null column).
            call_site=getattr(r, "callSite", None) or "unknown",
        )
        for r in (recs or [])
    ]


def _load_usage_rows(the_date: date) -> list[UsageRow]:
    """Load ModelTokenUsage rows for `the_date` (UTC day). Sync wrapper
    around async Prisma -- this is a one-shot cron script, no running
    loop, so asyncio.run is correct. Any failure (Prisma not
    generated, tunnel/DB down) -> NotImplementedError so the CLI
    reports cleanly and exits 2 instead of dumping a traceback."""
    try:
        return asyncio.run(_aload_usage_rows(the_date))
    except ImportError as e:
        raise NotImplementedError(
            "Prisma client not generated -- run `python -m prisma "
            "generate` (venv-targeted), then retry."
        ) from e
    except Exception as e:  # noqa: BLE001
        raise NotImplementedError(
            f"Could not load ModelTokenUsage for {the_date} "
            f"({type(e).__name__}: {e}). Is the DB/tunnel up?"
        ) from e


async def _awrite_daily_cost(rows: list[DailyCostRow]) -> int:
    from prisma import Prisma  # type: ignore

    db = Prisma()
    await db.connect()
    n = 0
    try:
        for row in rows:
            # prisma-client-py can't serialize a bare datetime.date;
            # the @db.Date column takes a datetime. Midnight UTC of the
            # bucket day -> the DB still stores just the date part.
            dt = datetime(
                row.the_date.year, row.the_date.month, row.the_date.day,
                tzinfo=timezone.utc,
            )
            payload = {
                "date": dt,
                "model": row.model,
                "callSite": row.call_site,
                "inputTokens": row.input_tokens,
                "cachedTokens": row.cached_input_tokens,
                "outputTokens": row.output_tokens,
                "callCount": row.call_count,
                "usd": float(round(row.usd, 6)),
            }
            # Idempotent: the @@unique([date, model, callSite]) key ->
            # prisma compound key `date_model_callSite`. Re-running a
            # date overwrites that bucket (no duplicate rows).
            await db.dailycost.upsert(
                where={
                    "date_model_callSite": {
                        "date": dt,
                        "model": row.model,
                        "callSite": row.call_site,
                    }
                },
                data={"create": payload, "update": payload},
            )
            n += 1
    finally:
        await db.disconnect()
    return n


def _write_daily_cost(rows: list[DailyCostRow]) -> None:
    """Idempotent upsert of DailyCost rows. Sync wrapper (cron script).
    A failure raises NotImplementedError so the CLI exits 2 cleanly."""
    if not rows:
        return
    try:
        n = asyncio.run(_awrite_daily_cost(rows))
        logger.info("wrote/updated %d DailyCost row(s)", n)
    except ImportError as e:
        raise NotImplementedError(
            "Prisma client not generated -- cannot write DailyCost."
        ) from e
    except Exception as e:  # noqa: BLE001
        raise NotImplementedError(
            f"Could not write DailyCost ({type(e).__name__}: {e}). "
            f"Is the DB/tunnel up?"
        ) from e


# --- CLI -----------------------------------------------------------------


def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Daily OpenAI cost rollup.")
    parser.add_argument(
        "--date",
        type=_parse_date,
        default=None,
        help="ISO date (YYYY-MM-DD). Defaults to yesterday.",
    )
    parser.add_argument(
        "--backfill",
        type=int,
        default=0,
        help="Roll up the last N days (inclusive of today-1).",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    dates: list[date]
    if args.backfill:
        today = date.today()
        dates = [today - timedelta(days=i) for i in range(1, args.backfill + 1)]
    else:
        dates = [args.date or (date.today() - timedelta(days=1))]

    for d in dates:
        try:
            usage = _load_usage_rows(d)
        except NotImplementedError as e:
            logger.error("Cannot roll up %s: %s", d, e)
            return 2
        rows = rollup_by_model(usage, d)
        logger.info(
            "%s: %d models, total $%.4f",
            d,
            len(rows),
            sum(r.usd for r in rows),
        )
        _write_daily_cost(rows)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "DailyCostRow",
    "PRICE_PER_1M_TOKENS",
    "UsageRow",
    "anomaly_ratio",
    "compute_cost_usd",
    "rollup_by_model",
]
