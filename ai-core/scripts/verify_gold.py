#!/usr/bin/env python3
"""Check every claim in a gold set against what we can actually source.

    verify_gold.py                          # the real-traffic set
    verify_gold.py --gold path/to.jsonl
    verify_gold.py --only names             # one check
    verify_gold.py --quiet                  # findings only, no summary

WHY THIS EXISTS
    A gold set is the standard the bot is measured against, so a wrong row
    does not just miss a bug -- it manufactures one, and the score stops
    meaning anything. Reviewing 349 rows by hand is not realistic, and the
    failure that prompted this was not subtle: a rubric asserted "the
    Amelia Hoover Music Library". There is no such library. The real one is
    the Amos Music Library, closed in 2023, named in four places in this
    repo. Nobody typed a fact they doubted; the name simply arrived
    plausible and went unchecked.

    That is the same failure the bot gets marked down for, so it gets the
    same treatment: every proper noun, person, email, telephone number and
    URL in a rubric has to be traceable to something we hold.

WHAT COUNTS AS A SOURCE
    * the serving Weaviate corpus -- our own crawl of the library website,
      which is as close to "check it against the site" as we get offline
    * the Librarian table, which data_health verifies against the staff CSV
    * UrlSeen, every URL the crawler has ever fetched
    * the repo's own docs, for facts recorded during operator review

    Nothing here touches the network. A finding means "no source we hold
    supports this", which is a prompt to go and look -- not proof of error.
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_AI_CORE = _HERE.parent
sys.path.insert(0, str(_AI_CORE))

for _line in (_AI_CORE.parent / ".env").read_text().splitlines():
    if "=" in _line and not _line.startswith("#"):
        _k, _, _v = _line.partition("=")
        os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))

DEFAULT_GOLD = _AI_CORE / "src" / "eval" / "golden_real_traffic.jsonl"

# Capitalised runs of 2+ words: "Amos Music Library", "Jenny Presnell".
# One capitalised word is too noisy -- sentences start with them.
#
# Sentence boundaries are cut BEFORE matching. Without that, the last word
# of one sentence and the first of the next join into phrases like
# "PDF. Copyright" and "ID. It", which are not names of anything and which
# buried the one real finding in forty lines of noise.
_SENTENCE_SPLIT = re.compile(r"(?<=[.;:!?])\s+|\s+--\s+|\n+|\s+\u2014\s+")
_PROPER = re.compile(r"\b([A-Z][a-zA-Z'’&-]+(?:\s+(?:of|and|the|&|for)\s+)?"
                     r"(?:\s+[A-Z][a-zA-Z'’&-]+)+)\b")
_EMAIL = re.compile(r"\b[\w.+-]+@[\w.-]+\.\w+\b")
_PHONE = re.compile(r"\(\d{3}\)\s*\d{3}-\d{4}|\b\d{3}-\d{3}-\d{4}\b")

# Phrases that are ours, not the library's: rubric vocabulary, the names of
# our own machinery, and ordinary title-case English. Matching one of these
# is not a claim about the world.
_OURS = {
    "ask us", "databases a-z", "interlibrary loan", "miami university",
    "miami university libraries", "the libraries", "special collections",
    "university archives", "research guides", "subject liaisons",
    "subject librarian", "course reserves", "home delivery", "crowd index",
    "reading room", "reading rooms", "student center", "creative cloud",
    "adobe creative cloud", "microsoft office", "apple pencils",
    "apple pencil", "labor day", "fall break", "do not", "must not",
    "it must", "the bot", "the answer", "the question", "the patron",
    "the row", "the rubric", "the corpus", "live libcal", "libcal",
    "primo", "ohiolink", "searchohio", "myaccount", "mulaa", "ill",
    "web services", "data services", "scholarly communication",
    "artificial intelligence center", "howe writing center",
    "writing center", "game nights", "library game nights",
    "game night", "digital campus", "swank digital campus",
    "printing & wifi", "printing and wifi", "oxford", "hamilton",
    "middletown", "king library", "king", "wertz", "rentschler",
    "gardner-harvey", "sword", "armstrong", "laws hall", "chromebook",
    "chromebooks", "ipad", "ipads", "ipad pros", "kic", "ebsco", "jstor",
    "pubmed", "web of science", "kanopy", "abbyy", "qgis", "spss",
    "bloomberg", "mla directory", "inside higher ed", "chronicle of higher",
    "new york times", "wall street journal", "cincinnati enquirer",
    "dayton daily news", "o globo", "slate magazine", "the ohio",
    "ohio newspapers", "refusal", "correctly", "live",
}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip().lower()


def load_sources() -> dict:
    """Everything we can check a claim against, as one lowercased blob plus
    the structured bits (people, emails, urls) that deserve exact matching."""
    src = {"text": [], "people": set(), "emails": set(), "urls": set(),
           "phones": set()}

    # 1. the corpus -- our crawl of the website
    try:
        import weaviate
        c = weaviate.connect_to_local(
            host=os.getenv("WEAVIATE_HOST", "127.0.0.1"),
            port=int(os.getenv("WEAVIATE_HTTP_PORT", "8080")),
            grpc_port=int(os.getenv("WEAVIATE_GRPC_PORT", "50051")))
        try:
            coll = c.collections.get(os.environ["WEAVIATE_CHUNK_COLLECTION"])
            for o in coll.iterator():
                p = o.properties
                src["text"].append(_norm(str(p.get("text") or "")))
                u = str(p.get("source_url") or p.get("url") or "")
                if u:
                    src["urls"].add(u.rstrip("/"))
        finally:
            c.close()
    except Exception as e:                      # noqa: BLE001
        print(f"!! corpus unavailable ({e}); skipping corpus-backed checks",
              file=sys.stderr)

    # 2. the staff roster + every URL the crawler has fetched
    try:
        import asyncio

        import asyncpg

        async def _pg():
            url = os.environ["DATABASE_URL"].split("?")[0]
            conn = await asyncpg.connect(url)
            try:
                for r in await conn.fetch(
                        'SELECT name, email, phone FROM "Librarian"'):
                    if r["name"]:
                        src["people"].add(_norm(r["name"]))
                        parts = r["name"].split()
                        if len(parts) >= 2:      # "Roger A Justus" -> "roger justus"
                            src["people"].add(_norm(f"{parts[0]} {parts[-1]}"))
                    if r["email"]:
                        src["emails"].add(r["email"].strip().lower())
                    if r["phone"]:
                        src["phones"].add(r["phone"].strip())
                for r in await conn.fetch('SELECT url FROM "UrlSeen"'):
                    if r["url"]:
                        src["urls"].add(r["url"].rstrip("/"))
            finally:
                await conn.close()

        asyncio.run(_pg())
    except Exception as e:                      # noqa: BLE001
        print(f"!! database unavailable ({e}); skipping roster checks",
              file=sys.stderr)

    # 3. the repo's own prose -- operator rulings live here, not on the site
    for sub in ("docs",):
        d = _AI_CORE.parent / sub
        if not d.exists():
            continue
        for p in d.rglob("*.md"):
            try:
                src["text"].append(_norm(p.read_text(errors="replace")))
            except OSError:
                continue
    for p in (_AI_CORE / "src" / "graph").glob("*.py"):
        try:
            src["text"].append(_norm(p.read_text(errors="replace")))
        except OSError:
            continue

    src["blob"] = "\n".join(src["text"])
    return src


def check_row(row: dict, src: dict, only: "set[str]") -> "list[tuple[str,str]]":
    """(kind, message) for everything in this row we cannot source."""
    out = []
    prose = f"{row.get('expected_answer','')} {row.get('notes','') or ''}"

    if "names" in only:
        # The RUBRIC only. A note is commentary about what went wrong, and
        # quoting the wrong name there is the point of writing it -- the
        # first version of this check flagged its own correction notes.
        pieces = _SENTENCE_SPLIT.split(row.get("expected_answer", ""))
        for piece in pieces:
            # Drop the first word of a sentence: it is capitalised by
            # grammar, not because it names anything.
            piece = re.sub(r"^\W*\w+\s+", "", piece)
            for m in _PROPER.finditer(piece):
                phrase = m.group(1).strip(" .,")
                low = _norm(phrase)
                if low in _OURS or len(low) < 6:
                    continue
                if any(low in o or o in low for o in _OURS):
                    continue
                if low in src["blob"]:
                    continue
                # a person we hold, written either way round
                if low in src["people"]:
                    continue
                out.append(("name",
                            f'"{phrase}" appears in no source we hold'))

    if "people" in only and src["people"]:
        # Two-word Capitalised phrases that look like a person: flag when the
        # row also carries an email, which is how a liaison row is written.
        for m in _EMAIL.finditer(prose):
            addr = m.group(0).lower()
            if addr in src["emails"]:
                continue
            if addr.split("@")[0] in {"create", "archives", "librarygamesnights"}:
                continue
            out.append(("email", f"{addr} is not in the Librarian table"))

    if "phones" in only:
        for m in _PHONE.finditer(prose):
            ph = m.group(0)
            if ph in src["phones"] or _norm(ph) in src["blob"]:
                continue
            if ph in {"(513) 529-4141"}:         # the service desk
                continue
            out.append(("phone", f"{ph} is in neither the roster nor the corpus"))

    if "urls" in only and src["urls"]:
        for u in row.get("allowed_urls", []):
            base = u.split("?")[0].rstrip("/")
            if base in src["urls"] or u.rstrip("/") in src["urls"]:
                continue
            if any(s.startswith(base) for s in src["urls"]):
                continue
            out.append(("url", f"{u} has never been fetched by the crawler"))

    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--gold", type=Path, default=DEFAULT_GOLD)
    ap.add_argument("--only", default="names,people,phones,urls",
                    help="comma-separated: names, people, phones, urls")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()
    only = {s.strip() for s in args.only.split(",") if s.strip()}

    rows = [json.loads(l) for l in args.gold.read_text().splitlines()
            if l.strip() and not l.startswith("//")]
    if not args.quiet:
        print(f"checking {len(rows)} rows in {args.gold.name}\n")

    src = load_sources()
    if not args.quiet:
        print(f"sources: {len(src['text'])} documents, "
              f"{len(src['people'])} people, {len(src['urls'])} urls\n")

    # A bad URL is one fact, however many rows repeat it, so URLs are
    # reported per URL. Printing them per row buried five real findings
    # under 358 copies of the same line.
    kinds = collections.Counter()
    urls: "dict[str, list[str]]" = collections.defaultdict(list)
    flagged = 0
    for r in rows:
        found = check_row(r, src, only)
        rowlevel = [(k, m) for k, m in found if k != "url"]
        for _k, m in [(k, m) for k, m in found if k == "url"]:
            urls[m.split(" has never")[0]].append(r["id"])
            kinds["url"] += 1
        if not rowlevel:
            continue
        flagged += 1
        print(f"{r['id']}")
        print(f"    Q: {r['question'][:88]}")
        for kind, msg in rowlevel:
            kinds[kind] += 1
            print(f"    [{kind}] {msg}")
        print()

    if urls:
        print("URLs the crawler has never fetched:\n")
        for u, ids in sorted(urls.items(), key=lambda kv: -len(kv[1])):
            print(f"  {len(ids):4} rows  {u}")
            if len(ids) <= 3:
                print(f"            {', '.join(ids)}")
        print()

    print(f"{flagged} of {len(rows)} rows carry an unsourced claim; "
          f"{len(urls)} distinct URLs are unfetched ({dict(kinds)})")
    print("\nA finding is a prompt to go and look, not proof of error: the "
          "corpus is a crawl and does not hold everything the site says.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
