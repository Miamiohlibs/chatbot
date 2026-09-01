"""
Read-only cost panel (Op 3 "Cost tracking" -- the viewable surface).

There was no way to SEE spend: ModelTokenUsage logs every turn's tokens and
cost_rollup.py aggregates DailyCost, but nothing rendered it. This adds a
token-gated `/admin/cost` HTML page (and `/admin/cost.json`) that computes USD
LIVE from ModelTokenUsage via cost_rollup.compute_cost_usd -- so it shows real
dollars even before the DailyCost cron is scheduled.

SECURITY: same fail-closed model as the review surface -- mounted only when
ADMIN_API_TOKEN is set, gated by make_token_guard (X-Admin-Token header or
?key=). It exposes only AGGREGATE token/cost numbers (no conversation content),
but the token gate keeps spend figures internal anyway.

READ-ONLY: find_many on ModelTokenUsage only. Any DB error degrades to an empty
panel, never a 500.
"""
from __future__ import annotations

import calendar
import datetime as _dt
import html
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

# Oxford, not UTC. A month boundary at UTC midnight puts the last four
# hours of the 31st into the next month's purse.
LIBRARY_TZ = "America/New_York"

from src.api.admin.review_queries import local_dt as _local_dt
from src.api.admin.review_view_router import make_token_guard  # reuse the guard

try:
    from scripts.cost_rollup import (
        PRICE_PER_1M_TOKENS,
        compute_cost_usd,
        is_priced,
        normalise_model,
    )
except Exception:  # noqa: BLE001 -- keep importable if pricing module moves
    PRICE_PER_1M_TOKENS: dict = {}  # type: ignore

    def compute_cost_usd(model, input_tokens, cached_input_tokens, output_tokens):  # type: ignore
        return 0.0

    def is_priced(model):  # type: ignore
        return False

    def normalise_model(model):  # type: ignore
        return model

try:
    from starlette.requests import Request  # type: ignore
except Exception:  # noqa: BLE001
    Request = Any  # type: ignore

logger = logging.getLogger(__name__)

__all__ = ["build_cost_view_router", "make_token_guard"]


def _e(v: Any) -> str:
    return html.escape("" if v is None else str(v))


_STYLE = (
    # SCOPED to .cost, and stripped of everything the shared shell already
    # owns. This block used to redefine body/h1/h2/table/th and ship a
    # `.card` that collided with the shell's ticket card -- injected after
    # the shell's stylesheet, so it won on equal specificity and restyled
    # the top menu. The Cost page looked like a different application.
    #
    # What is left is the part the shell has no opinion on: numbers.
    ".cost table{font-variant-numeric:tabular-nums}"
    ".cost td,.cost th{text-align:right}"
    ".cost th:first-child,.cost td:first-child{text-align:left}"
    ".cost .big{font-size:1.7rem;font-weight:700;line-height:1.1;"
    "font-variant-numeric:tabular-nums}"
    # Tokens, not hex, and not the pre-2026-08-30 variable names. As
    # written these were `var(--muted)` and `var(--miami)`, which no
    # longer exist, plus three hardcoded near-whites that turned into
    # bright blocks the moment the console followed a dark system.
    ".cost .muted{color:hsl(var(--muted-foreground));font-size:.78rem}"
    ".cost .warn{color:hsl(var(--primary-ink));font-weight:600}"
    ".cost .alert{border:1px solid hsl(var(--danger) / .35);"
    "background:hsl(var(--danger-bg));color:hsl(var(--foreground));"
    "border-radius:8px;padding:.7rem 1rem;margin:.8rem 0;font-size:.85rem}"
    ".cost code{background:hsl(var(--muted));padding:1px 4px;"
    "border-radius:3px}"
)


def _page(title: str, body: str, *, key: str = "", who=None) -> str:
    """Render into the SHARED admin shell so this page has the same tab bar
    as every other operator surface.

    It used to render its own bare document. That left Cost as the one page
    with no way out except the browser's back button -- the operator console
    stopped looking like one console the moment you opened it. The private
    stylesheet below is still applied on top, because the tables here are
    numeric and want their own alignment rules; it no longer replaces the
    shell.
    """
    from src.api.admin import admin_ui

    return admin_ui.page(
        title,
        f"<style>{_STYLE}</style><div class='cost'>{body}</div>",
        current="/admin/cost", key=key, who=who)


async def _aggregate(db: Any, days: int) -> dict:
    """Read ModelTokenUsage for the window, group by (day, model, callSite),
    compute USD live. Returns a dict the views render. Never raises."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows: list = []
    try:
        if not db.is_connected():
            await db.connect()
        rows = await db.modeltokenusage.find_many(where={"createdAt": {"gte": since}})
    except Exception as e:  # noqa: BLE001
        logger.warning("cost panel: ModelTokenUsage read failed: %s", e)
        rows = []

    by_key: dict = defaultdict(lambda: {"in": 0, "cached": 0, "out": 0, "n": 0})
    by_day: dict = defaultdict(lambda: {"in": 0, "cached": 0, "out": 0, "n": 0, "usd": 0.0})
    for r in rows:
        # LIBRARY-LOCAL day, not the UTC one. The box runs UTC, so an 8pm
        # Eastern conversation has a createdAt of 00:xx the NEXT day and was
        # being counted against tomorrow. Evening is peak library use, so
        # every night's spend was landing on the following row and the daily
        # chart was wrong every day.
        _local = _local_dt(r.createdAt)
        day = (_local or r.createdAt).date().isoformat()
        model = r.llmModelName or "?"
        site = r.callSite or "—"
        p = int(r.promptTokens or 0)
        c = int(r.cachedInputTokens or 0)
        o = int(r.completionTokens or 0)
        for bucket in (by_key[(day, model, site)], by_day[day]):
            bucket["in"] += p
            bucket["cached"] += c
            bucket["out"] += o
            bucket["n"] += 1

    rows_out = []
    total = {"in": 0, "cached": 0, "out": 0, "n": 0, "usd": 0.0}
    for (day, model, site), a in by_key.items():
        usd = compute_cost_usd(model, a["in"], a["cached"], a["out"])
        by_day[day]["usd"] += usd
        rows_out.append({
            "day": day, "model": model, "site": site,
            "turns": a["n"], "input": a["in"], "cached": a["cached"],
            "output": a["out"], "usd": usd,
            # A $0 here can mean "free" or "we have no rate" -- say which.
            "priced": bool(is_priced(model)),
        })
        total["in"] += a["in"]; total["cached"] += a["cached"]
        total["out"] += a["out"]; total["n"] += a["n"]; total["usd"] += usd
    rows_out.sort(key=lambda x: (x["day"], -x["usd"]), reverse=True)
    days_out = [{"day": d, **v} for d, v in sorted(by_day.items(), reverse=True)]
    return {"window_days": days, "rows": rows_out, "days": days_out, "total": total}


_MONTH_SQL = """
SELECT to_char(("createdAt" AT TIME ZONE 'UTC' AT TIME ZONE $1)::date,
               'YYYY-MM') AS month,
       "llmModelName" AS model,
       COALESCE("callSite", '') AS site,
       SUM("promptTokens")::bigint      AS inp,
       SUM("cachedInputTokens")::bigint AS cached,
       SUM("completionTokens")::bigint  AS outp,
       COUNT(*)::int                    AS calls
FROM "ModelTokenUsage"
GROUP BY 1, 2, 3
"""


async def _by_month(db: Any) -> list[dict]:
    """Spend per calendar month, split into the two purses.

    WHY THIS IS THE FIRST TABLE ON THE PAGE
        The budget is a MONTHLY pair of purses and the guard enforces
        month-to-date. This page had a 7-day window, a by-day table and an
        all-time total, and no month anywhere -- so the number the money
        is actually governed by was the one number you could not read.
        Asked for 2026-08-31.

    Grouped in Postgres on the Oxford month, so there is no read cap and
    no day-boundary bug; priced in Python, because the price table is
    Python and the grouped result is a few dozen rows either way.

    Each month is measured against the purse that applied THAT month, not
    today's -- the student purse went from $25 to $45 at launch on
    2026-08-13, and holding July up against September's ceiling would say
    something untrue about July.
    """
    from scripts.cost_rollup import compute_cost_usd
    from src.config import budget as B
    from src.observability.spend_ledger import DEV_CALL_SITES

    try:
        if not db.is_connected():
            await db.connect()
        rows = await db.query_raw(_MONTH_SQL, LIBRARY_TZ)
    except Exception:  # noqa: BLE001 -- the page degrades, it never 500s
        logger.warning("cost by-month aggregate failed", exc_info=True)
        return []

    months: dict = {}
    for r in rows or []:
        m = str(r["month"])
        slot = months.setdefault(m, {"month": m, "serving": 0.0, "eval": 0.0,
                                     "calls": 0})
        usd = compute_cost_usd(str(r["model"] or ""), int(r["inp"] or 0),
                               int(r["cached"] or 0), int(r["outp"] or 0))
        key = "eval" if str(r["site"] or "") in DEV_CALL_SITES else "serving"
        slot[key] += usd
        slot["calls"] += int(r["calls"] or 0)

    out = []
    for m in sorted(months, reverse=True):
        row = months[m]
        y, mo = (int(x) for x in m.split("-"))
        # THE PURSE AS THE GUARD SAW IT, NOT AS THE MONTH OPENED.
        #
        # The student purse moved from $25 to $45 on 2026-08-13, mid-month.
        # Asking split_for() for the 1st gives August a $25 ceiling, while
        # budget_guard has been enforcing $45 against the same month-to-date
        # all along -- a table that contradicts the control it is reporting
        # on is worse than no table. Take the purse in force when the month
        # closed, and for the month still running, the one in force now.
        last = _dt.date(y, mo, calendar.monthrange(y, mo)[1])
        today = _dt.date.today()
        purse_serving, purse_eval = B.split_for(min(last, today))
        row["purse_serving"] = purse_serving
        row["purse_eval"] = purse_eval
        row["total"] = row["serving"] + row["eval"]
        out.append(row)
    return out


async def _model_history(db: Any) -> list[dict]:
    """Every model this deployment has EVER billed, all-time. Never raises.

    Uses a single group_by aggregate rather than scanning ModelTokenUsage, so
    this stays cheap as the table grows (2,554 rows on 2026-07-31).

    This panel exists because a retired model served 1,518 turns across the
    whole pre-rebuild era (2025-12 to 2026-05) while absent from the price
    table, so every cost report read $0.00. A model you have forgotten you
    ran is exactly the one you cannot see the bill for, hence all-time and
    hence the explicit `priced` flag.

    That matters MORE now, not less: the price table was cut to GPT-5.6 only
    on 2026-09-01, so anything outside that line is unpriced by design and
    this flag is the thing that makes it visible.
    """
    try:
        if not db.is_connected():
            await db.connect()
        groups = await db.modeltokenusage.group_by(
            by=["llmModelName"],
            count=True,
            sum={
                "promptTokens": True,
                "cachedInputTokens": True,
                "completionTokens": True,
            },
            min={"createdAt": True},
            max={"createdAt": True},
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("cost panel: model history aggregate failed: %s", e)
        return []

    out: list[dict] = []
    for g in groups:
        model = g.get("llmModelName") or "?"
        s = g.get("_sum") or {}
        inp = int(s.get("promptTokens") or 0)
        cached = int(s.get("cachedInputTokens") or 0)
        outp = int(s.get("completionTokens") or 0)
        base = normalise_model(model)
        out.append({
            "model": model,
            # Shown when a dated snapshot was billed as its base model, so the
            # rate a row was priced at is never a mystery.
            "priced_as": base if base != model else None,
            "priced": bool(is_priced(model)),
            "turns": int((g.get("_count") or {}).get("_all") or 0),
            "input": inp,
            "cached": cached,
            "output": outp,
            "first_seen": _day_of(g.get("_min", {}).get("createdAt")),
            "last_seen": _day_of(g.get("_max", {}).get("createdAt")),
            "usd": compute_cost_usd(model, inp, cached, outp),
        })
    out.sort(key=lambda r: -r["turns"])
    return out


def _day_of(value: Any) -> str:
    """group_by returns createdAt as an ISO string, find_many as a datetime."""
    if value is None:
        return "—"
    if hasattr(value, "date"):
        return value.date().isoformat()
    return str(value)[:10]


# Models we DO call but never write a ModelTokenUsage row for, so the usage
# log cannot see them. src/llm/client.py:embed() calls the embeddings API
# directly -- once per turn for kNN intent classification, plus once per
# uncached exemplar at startup -- without recording anything.
#
# Left uninstrumented deliberately: embed() is synchronous and on the hot
# path, and the spend is trivial (~$0.014 to embed all 5,300 exemplars at
# $0.13/1M). But the rate card must not print "never used" about a model we
# call every single turn, so it says "not logged" instead of lying.
_USED_BUT_UNLOGGED = frozenset({"text-embedding-3-large"})


def _rate_card(history: list[dict]) -> list[dict]:
    """The price table itself, annotated with whether we've ever used each row.

    Rendering the rate card next to the usage makes the failure modes visible
    at a glance: a model with usage but no price (bills as $0), a price with no
    usage (dead row worth pruning), and a model whose usage we never log."""
    used = {normalise_model(h["model"]) for h in history}

    # Only rows we actually call. The table used to print all of
    # PRICE_PER_1M_TOKENS -- 48 models against the two this service runs on
    # -- which buried the two numbers an operator came to read. The price
    # table still covers every model, so an unpriced one is still caught;
    # what changed is that the PAGE shows what we spend on, not what OpenAI
    # sells. `_hidden_rate_rows` reports the count so the omission is
    # visible rather than silent.
    return [
        {
            "model": name,
            "input": r["input"],
            "cached_input": r["cached_input"],
            "output": r["output"],
            "used": name in used,
            "unlogged": name in _USED_BUT_UNLOGGED,
        }
        for name, r in sorted(PRICE_PER_1M_TOKENS.items())
        if name in used or name in _USED_BUT_UNLOGGED
    ]


def _hidden_rate_rows(history: list[dict]) -> int:
    """How many priced models the rate card leaves out."""
    used = {normalise_model(h["model"]) for h in history}
    return sum(1 for n in PRICE_PER_1M_TOKENS
               if n not in used and n not in _USED_BUT_UNLOGGED)


def _cache_pct(d: dict) -> str:
    inp = d.get("in", 0)
    return f"{(100.0 * d.get('cached', 0) / inp):.1f}%" if inp else "—"


def build_cost_view_router(deps: dict) -> Any:
    """deps: {db: PrismaClient, guard: token-guard dependency}."""
    try:
        from fastapi import APIRouter, Depends, Query  # type: ignore
        from fastapi.responses import HTMLResponse, JSONResponse  # type: ignore
    except Exception:  # noqa: BLE001 -- offline sandbox placeholder
        class _Placeholder:
            def __init__(self, *a, **k): ...
        return _Placeholder()

    db = deps["db"]
    guard = deps["guard"]
    router = APIRouter(tags=["admin-cost"])

    @router.get("/admin/cost.json")
    async def cost_json(days: int = Query(7, ge=1, le=90), who=Depends(guard)):
        data = await _aggregate(db, days)
        history = await _model_history(db)
        data["total"]["usd"] = round(data["total"]["usd"], 4)
        for r in data["rows"]:
            r["usd"] = round(r["usd"], 6)
        for d in data["days"]:
            d["usd"] = round(d["usd"], 4)
        for h in history:
            h["usd"] = round(h["usd"], 4)
        data["model_history"] = history
        data["rate_card"] = _rate_card(history)
        data["unpriced_models"] = [h["model"] for h in history if not h["priced"]]
        return JSONResponse(data)

    @router.get("/admin/cost", response_class=HTMLResponse)
    async def cost_html(days: int = Query(7, ge=1, le=90), key: str = "",
                        who=Depends(guard)):
        # Carried onto every in-page link so the window switcher does not
        # drop the caller's credentials. Empty when there is no key, which is
        # the SSO case -- the cookie travels on its own.
        _kq = f"&key={_e(key)}" if key else ""
        d = await _aggregate(db, days)
        history = await _model_history(db)
        months = await _by_month(db)

        def _month_row(r: dict) -> str:
            def _against(spent: float, purse: float) -> str:
                if not purse:
                    return "<td class='muted'>—</td>"
                pct = spent / purse * 100
                cls = " class='warn'" if pct >= 95 else ""
                return f"<td{cls}>{pct:.0f}% of ${purse:.0f}</td>"

            this_month = r["month"] == _dt.date.today().strftime("%Y-%m")
            lead = (f"<b>{_e(r['month'])}</b> <span class='muted'>so far"
                    f"</span>" if this_month else _e(r["month"]))
            return (
                f"<tr><td>{lead}</td>"
                f"<td>${r['serving']:.2f}</td>{_against(r['serving'], r['purse_serving'])}"
                f"<td>${r['eval']:.2f}</td>{_against(r['eval'], r['purse_eval'])}"
                f"<td>${r['total']:.2f}</td><td>{r['calls']:,}</td></tr>")

        month_rows = "".join(_month_row(r) for r in months) or (
            "<tr><td colspan='7' class='muted'>Nothing recorded yet.</td></tr>")
        t = d["total"]
        cards = (
            f"<div class='stat calm'><div class='muted'>Spend (last {days}d)</div>"
            f"<div class='big'>${t['usd']:.2f}</div></div>"
            f"<div class='stat calm'><div class='muted'>Conversations turns</div>"
            f"<div class='big'>{t['n']:,}</div></div>"
            f"<div class='stat calm'><div class='muted'>Total tokens</div>"
            f"<div class='big'>{(t['in'] + t['out']):,}</div></div>"
            f"<div class='stat calm'><div class='muted'>Input cache hit</div>"
            f"<div class='big'>{_cache_pct(t)}</div></div>"
        )
        day_rows = "".join(
            f"<tr><td>{_e(x['day'])}</td><td>${x['usd']:.4f}</td>"
            f"<td>{x['n']:,}</td><td>{x['in']:,}</td><td>{x['out']:,}</td>"
            f"<td>{_cache_pct(x)}</td></tr>"
            for x in d["days"]
        ) or "<tr><td colspan='6' class='muted'>No usage logged in this window.</td></tr>"
        brk_rows = "".join(
            f"<tr><td>{_e(r['day'])}</td><td>{_e(r['model'])}</td>"
            f"<td>{_e(r['site'])}</td>"
            + (f"<td>${r['usd']:.4f}</td>" if r["priced"] else "<td class='warn'>unpriced</td>")
            + f"<td>{r['turns']:,}</td>"
            f"<td>{r['input']:,}</td><td>{r['cached']:,}</td><td>{r['output']:,}</td></tr>"
            for r in d["rows"]
        ) or "<tr><td colspan='8' class='muted'>—</td></tr>"
        # All-time history. Sits ABOVE the window tables on purpose: the
        # window can only ever show models still in use, and the expensive
        # surprise is the one you stopped running months ago.
        hist_rows = "".join(
            "<tr>"
            f"<td>{_e(h['model'])}"
            + (
                f" <span class='muted'>→ priced as {_e(h['priced_as'])}</span>"
                if h["priced_as"] else ""
            )
            + "</td>"
            + (
                f"<td>${h['usd']:.2f}</td>"
                if h["priced"]
                else "<td class='warn'>unpriced</td>"
            )
            + f"<td>{h['turns']:,}</td><td>{h['input']:,}</td>"
            f"<td>{h['cached']:,}</td><td>{h['output']:,}</td>"
            f"<td>{_e(h['first_seen'])}</td><td>{_e(h['last_seen'])}</td></tr>"
            for h in history
        ) or "<tr><td colspan='8' class='muted'>No usage ever logged.</td></tr>"
        hist_total = sum(h["usd"] for h in history if h["priced"])
        unpriced = [h for h in history if not h["priced"]]
        banner = ""
        if unpriced:
            names = ", ".join(_e(h["model"]) for h in unpriced)
            banner = (
                f"<div class='alert'><b>{len(unpriced)} model(s) have usage but "
                f"no price row, so they are billing as $0 here:</b> {names}. "
                f"Add them to <code>PRICE_PER_1M_TOKENS</code> in "
                f"<code>scripts/cost_rollup.py</code> — the all-time total below "
                f"is an UNDER-count until you do.</div>"
            )
        card_rows = "".join(
            f"<tr><td>{_e(c['model'])}</td><td>${c['input']:.3f}</td>"
            f"<td>${c['cached_input']:.3f}</td><td>${c['output']:.3f}</td>"
            + (
                "<td>yes</td>" if c["used"]
                else "<td class='warn'>used, not logged</td>" if c["unlogged"]
                else "<td class='muted'>never</td>"
            )
            + "</tr>"
            for c in _rate_card(history)
        )

        body = (
                        f"{banner}"
            # The window switcher used to print a literal ellipsis where the
            # key belongs -- `key=…` -- so every one of these links landed on
            # a 401 and the page was stuck on its 7-day default. The key is
            # carried through properly now, and omitted entirely when the
            # caller arrived by session rather than by token.
            f"<div class='muted'>Live from ModelTokenUsage, priced with current "
            f"per-model rates. Window: "
            + " · ".join(
                (f"<b>{n}d</b>" if n == days
                 else f"<a href='/admin/cost?days={n}{_kq}'>{n}d</a>")
                for n in (1, 7, 30, 90)
            )
            + f" · <a href='/admin/cost.json?days={days}{_kq}'>JSON</a></div>"
            f"<div class='stats'>{cards}</div>"
            f"<h2>By month</h2>"
            f"<div class='muted'>What the budget is actually measured on. "
            f"Each month is held against the purse that applied THAT month "
            f"— the student purse moved from $25 to $45 at launch.</div>"
            f"<table><tr><th>Month</th><th>Students</th><th>of purse</th>"
            f"<th>Dev &amp; eval</th><th>of purse</th><th>Total</th>"
            f"<th>Calls</th></tr>{month_rows}</table>"
            f"<h2>By day</h2><table><tr><th>Day</th><th>USD</th><th>Turns</th>"
            f"<th>Input tok</th><th>Output tok</th><th>Cache hit</th></tr>{day_rows}</table>"
            # FOLDED, NOT REMOVED.
            #
            # Three dense tables sat between the reader and nothing. They
            # answer real questions -- which call site is expensive, is a
            # model priced at all -- and none of them is the question
            # somebody opens this page with, which is "how much have we
            # spent this month". Operator, 2026-08-31: the rate card does
            # not need to be that prominent.
            f"<details><summary>By day · model · call site "
            f"<span class='dim'>which call site the money went to</span>"
            f"</summary>"
            f"<table><tr><th>Day</th><th>Model</th>"
            f"<th>Call site</th><th>USD</th><th>Turns</th><th>Input</th>"
            f"<th>Cached</th><th>Output</th></tr>{brk_rows}</table></details>"
            f"<details><summary>Every model ever used "
            f"<span class='dim'>all time, ${hist_total:.2f}</span></summary>"
            f"<div class='muted'>Ignores the {days}-day window. Sorted by turns. "
            f"A dated snapshot (e.g. <code>-2026-03-17</code>) is priced at its "
            f"base model's rate.</div>"
            f"<table><tr><th>Model</th><th>USD</th><th>Turns</th><th>Input tok</th>"
            f"<th>Cached tok</th><th>Output tok</th><th>First used</th>"
            f"<th>Last used</th></tr>{hist_rows}</table></details>"
            f"<details><summary>Rate card "
            f"<span class='dim'>$ per 1M tokens</span></summary>"
            f"<div class='muted'>From <code>PRICE_PER_1M_TOKENS</code>. One rate "
            f"per model applied to ALL history, so a price change also moves past "
            f"totals; treat old figures as indicative, not invoice-grade. "
            f"<b>used, not logged</b> = we call it but write no ModelTokenUsage "
            f"row, so its spend appears nowhere above (embeddings: roughly "
            f"$0.01 all-time, hence untracked rather than urgent).</div>"
            f"<table><tr><th>Model</th><th>Input</th><th>Cached input</th>"
            f"<th>Output</th><th>Ever used here</th></tr>{card_rows}</table></details>"
        )
        return HTMLResponse(_page("Cost", body, key=key, who=who))

    return router
