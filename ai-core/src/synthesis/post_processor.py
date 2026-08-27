"""
The load-bearing citation / URL / scope validator.

Every synthesizer output goes through `process_synthesizer_output()`
before it leaves the backend. If ANY check fails, the output is
DOWNGRADED to a refusal -- we never silently drop an invalid citation
and ship the remaining text. The whole point of this module is that the
LLM is not trusted as the last line of defense on citations; this is.

Four independent checks, in order:

  1. Confidence gate. The synthesizer returns
     `confidence in {"low", "medium", "high"}`. `low` is a refusal.
     (Also: the literal token "REFUSAL" anywhere in the answer is
     treated as a self-flag; the synthesizer prompt instructs the model
     to emit it when the answer isn't in the sources.)

  2. Citation match. Every `[n]` that appears in the answer text must
     resolve to an entry in `citations[]`. Bare `[1]` with no matching
     citation entry is a fabricated reference.

  3. URL validation. Every URL mentioned in the answer must appear
     either (a) in `citations[n].url` for some cited n, or (b) in the
     allowlist of known-live URLs (UrlSeen table, passed in as a set).
     URLs in the answer but not in the allowlist are fabricated and
     fail the check.

  4. Cross-campus citation check. Every cited chunk's provenance
     metadata must have `campus == scope.campus` OR `campus == "all"`.
     Prevents the King-hours-for-Hamilton-question failure mode. Also
     the service-not-at-this-building check: if any evidence-bundle
     metadata flags the service as unavailable at scope.campus, we
     refuse with SERVICE_NOT_AT_BUILDING.

Ordering matters. Confidence is checked first because a low-confidence
answer is refused regardless of citation quality -- no point running
URL regexes against text the bot itself admitted it wasn't sure about.
Cross-campus is last because it's the most context-dependent and
produces the most specific refusal copy.

See plan:
  - Citation and refusal contract -> "Why force structured citations
    rather than asking the model nicely"
  - Data preparation playbook §8 -> cross-campus refusal guard

NOTE: This module is deliberately pure logic. It imports no LLM client,
no HTTP, no DB. It takes inputs, returns outputs, and is fully unit-
testable against fixtures. All I/O (UrlSeen lookup, chunk provenance
join) happens in the caller.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field, replace
from typing import Literal, Optional

logger = logging.getLogger(__name__)

from src.synthesis.refusal_templates import (
    RefusalContext,
    RefusalTrigger,
    render_refusal,
)


# --- Public shapes ---------------------------------------------------------

Confidence = Literal["low", "medium", "high"]


@dataclass(frozen=True)
class Citation:
    """One citation in the synthesizer's structured output.

    `n` is the citation number the model wrote (1-indexed). `chunk_id`
    is the id of the evidence-bundle row the model was pointing at (the
    synthesizer knows the chunk ids because retrieval returns them).
    The caller provides the `campus` and `library` fields by joining
    chunk_id -> ChunkProvenance before running validation.
    """

    n: int
    url: str
    snippet: str
    chunk_id: Optional[str] = None
    campus: Optional[str] = None
    library: Optional[str] = None


@dataclass(frozen=True)
class SynthesizerOutput:
    """Structured output from the synthesizer LLM call.

    Shape mirrors what OpenAI structured-outputs returns. The post-
    processor treats this as authoritative input; validation happens
    on its fields, not on the raw text.
    """

    answer: str
    citations: list[Citation] = field(default_factory=list)
    confidence: Confidence = "medium"


@dataclass(frozen=True)
class ValidationFailure:
    """One failed check. Zero or more of these feed into the decision
    to downgrade. A list of failures is still logged even when the
    downgrade already fired on the first one -- useful for debugging
    prompt / retrieval regressions."""

    trigger: RefusalTrigger
    detail: str
    """Human-readable reason; goes to debug logs and the eval report,
    NEVER to the user (the refusal template handles user-facing copy)."""


@dataclass(frozen=True)
class Refusal:
    """A post-processor refusal decision. `message` is the templated
    user-facing text; `trigger` is the enum value that caused it; the
    full failure list is preserved for logging."""

    trigger: RefusalTrigger
    message: str
    failures: list[ValidationFailure] = field(default_factory=list)

    closest_urls: list = field(default_factory=list)
    """Pages retrieval DID find, when the answer had to be withdrawn.

    A refusal used to discard them and offer Ask Us alone. That is right
    when retrieval found nothing, and wrong when it found the page the
    patron was asking about: "how do I access materials in Special
    Collections" was answered with Ask Us while
    spec.lib.miamioh.edu/home/visiting sat in the evidence (eval
    2026-08-26, sc_access_request).

    Handing over the page is NOT the same as asserting what is on it --
    which is the line the operator drew on 2026-08-17. The bot still does
    not state an undocumented fact; it says where to look.
    """


@dataclass(frozen=True)
class PostProcessorResult:
    """What `process_synthesizer_output()` returns.

    Exactly one of `answer` / `refusal` is set. Caller renders on the
    one that's populated; UI never has to check both.
    """

    answer: Optional[SynthesizerOutput] = None
    refusal: Optional[Refusal] = None

    @property
    def is_refusal(self) -> bool:
        return self.refusal is not None


# --- Citation-reference pattern --------------------------------------------

_CITATION_REF_RE = re.compile(r"\[(\d+)\]")
"""Matches `[1]`, `[23]`, etc. Any [n] in answer text is a citation
reference and must resolve to a citations[] entry."""

_URL_RE = re.compile(
    r"https?://[^\s<>\"'\])}]+",
    re.IGNORECASE,
)
"""Matches bare URLs. Deliberately conservative: stops at whitespace,
angle-bracket, or closing punctuation so we don't greedy-match into
Markdown syntax. URLs in Markdown links `[text](url)` still match the
url portion."""

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
"""Matches email addresses. Used for the trusted-evidence faithfulness
check: every email the model writes MUST appear verbatim in some
evidence item. Catches the directory-paraphrase bug
(bennethm@miamioh.edu -> bennett@miamioh.edu) and invented contacts.
Never false-positives on hours / "Closed" -- those aren't emails."""


# --- The main entry point --------------------------------------------------

# --- staff-privacy redaction helpers -------------------------------------
#
# Line-based on purpose. Removing just the email address would leave the
# name standing beside it, and a list of names is the roster the rule
# exists to prevent -- the demonstrated 2026-05-16 violation was names.

_SUBSTANCE_MIN_WORDS = 8
"""Words that must survive redaction for the answer to still be worth
sending. Below this the answer was the roster, not a page that happened to
name someone, and the refusal is the honest response.

Calibrated against both real shapes rather than picked round. A roster
answer collapses to nothing once its contact lines go -- "You can contact
X or Y [1]." leaves zero words -- while a roster with a header leaves only
the header ("Here are the librarians who can help:", seven). The archives
answer this was built for leaves ten: "Records of University contracts are
held by the University Archives"."""


def _strip_contact_lines(answer: str,
                         individual_emails: set) -> "tuple[str, int]":
    """Drop whole lines carrying an individual staff email.

    Returns (kept_text, lines_dropped).
    """
    lines = (answer or "").splitlines()
    kept, dropped = [], 0
    for line in lines:
        low = line.lower()
        if any(e in low for e in individual_emails):
            dropped += 1
            continue
        kept.append(line)
    text = "\n".join(kept)
    # Collapse the blank runs the removal leaves behind.
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")
    return text.strip(), dropped


def _carries_substance(text: str) -> bool:
    """Is there still an answer here, or only punctuation and markers?"""
    stripped = _EMAIL_RE.sub(" ", text or "")
    stripped = re.sub(r"\[\d+\]", " ", stripped)      # citation markers
    stripped = re.sub(r"[^\w\s]", " ", stripped)       # bullets, dashes
    return len(stripped.split()) >= _SUBSTANCE_MIN_WORDS


def process_synthesizer_output(
    output: SynthesizerOutput,
    *,
    scope_campus: str,
    url_allowlist: set[str],
    also_campuses: "tuple[str, ...]" = (),
    service_unavailable_trigger: Optional[RefusalContext] = None,
    evidence: Optional[list] = None,
) -> PostProcessorResult:
    """Validate the synthesizer's structured output. Downgrade to a
    refusal if any check fails.

    Args:
        output: Parsed synthesizer result (answer, citations, confidence).
        scope_campus: The resolved Scope.campus for this turn. Used in
            the cross-campus check and, if a refusal fires, to render
            campus-appropriate refusal copy.
        url_allowlist: Set of canonical URLs that are considered live
            (loaded from Postgres UrlSeen table by the caller). URLs
            in the answer must be a member of this set OR appear in
            one of the citations. A model URL that is in neither is
            fabricated.
        service_unavailable_trigger: If the caller has already
            determined (before synthesis) that the requested service
            isn't offered at scope.campus, passing the RefusalContext
            here will short-circuit to a SERVICE_NOT_AT_BUILDING
            refusal. None otherwise.

    Returns:
        A PostProcessorResult. Exactly one of `answer` / `refusal`
        is set.
    """
    # Short-circuit: if the caller pre-determined the service isn't
    # offered here, skip synthesis-level checks and refuse directly.
    if service_unavailable_trigger is not None:
        return PostProcessorResult(
            refusal=Refusal(
                trigger=RefusalTrigger.SERVICE_NOT_AT_BUILDING,
                message=render_refusal(
                    RefusalTrigger.SERVICE_NOT_AT_BUILDING,
                    service_unavailable_trigger,
                ),
                failures=[
                    ValidationFailure(
                        trigger=RefusalTrigger.SERVICE_NOT_AT_BUILDING,
                        detail=(
                            f"Service '{service_unavailable_trigger.service_name}' "
                            f"is not offered at {scope_campus}."
                        ),
                    )
                ],
            )
        )

    # --- 0. Domain-typo normalizer (Miami University email domain) ---
    # The synth occasionally writes typo'd variants of the Miami domain
    # ("miamiohio.edu" instead of "miamioh.edu", "muohio.edu" — the old
    # pre-2013 domain — etc). Caught in R8 retest: bot told a student to
    # activate NYT with "your miamiohio.edu email". None of these typo
    # forms are valid; rewrite to the canonical "miamioh.edu" rather
    # than refuse — the answer is otherwise correct and a refusal here
    # would be worse for the user than a quiet correction.
    #
    # Cheap, deterministic, and structurally cannot break a legitimate
    # answer: no real string we'd want to keep contains "miamiohio.edu"
    # or "muohio.edu" (the old domain has been gone since 2013).
    _NORMALIZE_DOMAINS = {
        "miamiohio.edu": "miamioh.edu",
        "miamiohio.org": "miamioh.edu",
        "muohio.edu": "miamioh.edu",
    }
    import re as _re
    from dataclasses import replace as _dc_replace
    for typo, canonical in _NORMALIZE_DOMAINS.items():
        if typo in output.answer.lower():
            output = _dc_replace(
                output,
                answer=_re.sub(
                    _re.escape(typo),
                    canonical,
                    output.answer,
                    flags=_re.IGNORECASE,
                ),
            )

    failures: list[ValidationFailure] = []

    # --- 1. Confidence gate ---
    if output.confidence == "low":
        failures.append(
            ValidationFailure(
                trigger=RefusalTrigger.MODEL_SELF_FLAGGED,
                detail="Synthesizer returned confidence=low.",
            )
        )
    if "REFUSAL" in output.answer:
        failures.append(
            ValidationFailure(
                trigger=RefusalTrigger.MODEL_SELF_FLAGGED,
                detail="Synthesizer emitted the literal REFUSAL token.",
            )
        )

    # --- 2. Citation match ---
    referenced_ns = {int(m.group(1)) for m in _CITATION_REF_RE.finditer(output.answer)}
    available_ns = {c.n for c in output.citations}
    missing_ns = referenced_ns - available_ns
    if missing_ns:
        failures.append(
            ValidationFailure(
                trigger=RefusalTrigger.CITATION_INVALID,
                detail=(
                    f"Answer references citation numbers "
                    f"{sorted(missing_ns)} that don't exist in citations[]."
                ),
            )
        )

    # --- 2b. Citation must be backed by retrieved evidence ---
    # A cited URL MUST be the source_url of a chunk the agent actually
    # retrieved. Without this, the synthesizer LLM can fabricate a citation
    # straight from its prompt's hard-coded reference-URL list even when
    # retrieval returned nothing -- the exact "made-up URL" failure the
    # citation contract exists to prevent (2026-06-08 Adobe-404 incident:
    # bot served `/use/technology/software/adobe/` with [1] while evidence
    # was empty). Empty evidence => every cited URL is unbacked => refuse,
    # which is the correct outcome for a no-sources turn. Normalize trailing
    # slash + case so a cosmetic mismatch isn't a spurious refusal.
    #
    # Only enforced when the caller passes `evidence` (None = legacy / unit
    # callers that don't supply it; an explicit [] = a real turn with zero
    # evidence, which SHOULD fail any citation). The production synthesizer
    # always passes the post-corrections bundle.
    if evidence is not None:
        def _norm_url(u: str) -> str:
            return (u or "").strip().rstrip("/").lower()

        evidence_urls = {
            _norm_url(getattr(c, "source_url", "")) for c in evidence
        }
        # Operator-verified Q&A chunks embed the canonical ANSWER url in their
        # TEXT, which often differs from the chunk's source_url (e.g. the NYT
        # gold chunk's source_url is .../az/databases but the operator answer
        # points to .../newspapers). A url written into retrieved evidence is
        # backed by retrieval -- NOT a fabrication from the prompt -- so it's a
        # legitimate citation. Without this, those curated answers refused with
        # CITATION_INVALID (prod eval 2026-06-28). Still blocks URLs the model
        # invents that appear in NO retrieved chunk.
        for c in evidence:
            for m in _URL_RE.finditer(getattr(c, "text", "") or ""):
                evidence_urls.add(_norm_url(m.group(0).rstrip(".,);:")))
        evidence_urls.discard("")
        for c in output.citations:
            if not c.url:
                continue
            if _norm_url(c.url) not in evidence_urls:
                failures.append(
                    ValidationFailure(
                        trigger=RefusalTrigger.CITATION_INVALID,
                        detail=(
                            f"Citation [{c.n}] URL {c.url!r} is not the "
                            f"source_url of any retrieved evidence chunk "
                            f"-- fabricated or pulled from the prompt's "
                            f"reference list rather than a real source."
                        ),
                    )
                )

    # --- 3. URL validation ---
    urls_in_answer = {m.group(0).rstrip(".,);:") for m in _URL_RE.finditer(output.answer)}
    cited_urls = {c.url for c in output.citations}
    for url in urls_in_answer:
        if url in cited_urls:
            continue
        if url in url_allowlist:
            continue
        failures.append(
            ValidationFailure(
                trigger=RefusalTrigger.CITATION_INVALID,
                detail=f"URL {url!r} in answer is neither cited nor in the allowlist.",
            )
        )

    # --- 3b. Trusted-evidence email faithfulness ---
    # Every email the model emits MUST appear verbatim in some evidence
    # item. The whole point of wiring lookup_librarian was to surface
    # the EXACT directory address; a paraphrased/typo'd email
    # (bennethm@ -> bennett@) or an invented one is a fabrication. This
    # is deterministic, cheap, and structurally cannot false-positive
    # on hours / "Closed" / room text (none contain an "@"). Skipped
    # when the caller didn't pass evidence (older callers / unit tests).
    if evidence:
        evidence_blob = " ".join(getattr(c, "text", "") or "" for c in evidence)
        for em in {m.group(0) for m in _EMAIL_RE.finditer(output.answer)}:
            if em not in evidence_blob:
                failures.append(
                    ValidationFailure(
                        trigger=RefusalTrigger.CITATION_INVALID,
                        detail=(
                            f"Email {em!r} in answer is not present "
                            f"verbatim in any evidence item "
                            f"(fabricated or paraphrased contact)."
                        ),
                    )
                )

    # --- 3c. Staff-privacy roster guard ---
    # Operator rule (2026-05-16): the bot must NEVER proactively expose
    # staff contact lists. The demonstrated violation
    # (hh_chat_with_librarian) dumped 5 librarians' names for a generic
    # "can I chat with a librarian?". Deterministic, ~zero false
    # positive: a legitimate single-person lookup ("the history
    # librarian" -> Jenny Presnell) has exactly ONE individual email;
    # >=2 distinct INDIVIDUAL emails in one answer is a roster dump.
    #
    # IMPORTANT (2026-05-23): department inbox emails (archives@,
    # speccoll@, refdesk@, library@, ill@, etc.) are NOT individual
    # staff. They are public group inboxes documented on the website.
    # Treat them as zero-count for the roster check so questions like
    # "what's the archivist's email" can return both archives@ AND
    # speccoll@ without falsely tripping the privacy guard.
    #
    # Explicit allowlist rather than a regex because individual emails
    # like "bennethm@miamioh.edu" (lastname+initial) would otherwise
    # match a permissive regex. Department inboxes are a small, known
    # set documented on the library website.
    _DEPT_INBOX_LOCALPARTS = frozenset({
        "archives", "speccoll", "specialcollections", "library",
        "libraries", "refdesk", "reference", "circulation", "circ",
        "ill", "interlibraryloan", "reserves", "askus", "ask",
        "info", "contact", "feedback", "webmaster",
        "music", "wertz", "arts", "art", "king", "best",
        "rentschler", "gardnerharvey", "hamilton", "middletown",
        "makerspace", "digital", "digitalcollections",
    })
    distinct_emails = {m.group(0).lower() for m in _EMAIL_RE.finditer(output.answer)}
    individual_emails = {
        e for e in distinct_emails
        if e.split("@", 1)[0] not in _DEPT_INBOX_LOCALPARTS
    }
    if len(individual_emails) >= 2:
        # REDACT BEFORE REFUSING (2026-08-25).
        #
        # The rule is "never volunteer a staff list", and the remedy used to
        # be throwing the whole answer away. That is right when the answer IS
        # the list, and wrong when the list is a footnote to something the
        # patron actually asked about.
        #
        # It cost us a real question, asked thirteen times: "where could I
        # find records of past event contracts Miami has executed" got back
        # "I don't share staff contact lists" -- a true sentence about a
        # question nobody asked, with the archives information the patron
        # wanted discarded on the way out.
        #
        # So drop the lines carrying individual contacts (the whole line, so
        # a name never survives its email) and keep the rest. If nothing of
        # substance is left, the answer really was a roster and the refusal
        # stands.
        kept, dropped = _strip_contact_lines(output.answer,
                                             individual_emails)
        if dropped and _carries_substance(kept):
            logger.info(
                "staff-privacy: redacted %d contact line(s) rather than "
                "discarding the answer", dropped)
            output = replace(output, answer=kept)
            individual_emails = set()

    if len(individual_emails) >= 2:
        failures.append(
            ValidationFailure(
                trigger=RefusalTrigger.STAFF_PRIVACY,
                detail=(
                    f"Answer exposes {len(individual_emails)} "
                    f"individual staff contacts "
                    f"({sorted(individual_emails)}) -- a roster "
                    f"dump. Bot must not volunteer staff lists; only "
                    f"a single specifically-requested person. "
                    f"(Total distinct emails: {len(distinct_emails)} "
                    f"of which {len(distinct_emails)-len(individual_emails)} "
                    f"are department inboxes, allowed.)"
                ),
            )
        )

    # --- 4. Cross-campus citation check ---
    # Only citations that actually have provenance metadata loaded are
    # checkable. If the caller forgot to join campus metadata on, we
    # log a failure rather than silently pass (the check is load-
    # bearing; "I didn't have the data" is not a safe default).
    for c in output.citations:
        if c.campus is None:
            failures.append(
                ValidationFailure(
                    trigger=RefusalTrigger.CROSS_CAMPUS_MISMATCH,
                    detail=(
                        f"Citation [{c.n}] has no campus metadata -- "
                        "post-processor cannot verify scope."
                    ),
                )
            )
            continue
        # A question that named TWO campuses may cite from both. Without
        # this the cross-campus guard rejected the other half by
        # construction: "is the laptop loan different at King and
        # Gardner-Harvey" resolved to Middletown, and every Oxford chunk --
        # the half we could actually answer -- was thrown out as a scope
        # violation.
        #
        # (An earlier version of this comment said the question was asked
        # seven times during the beta. That count was not checked and is
        # wrong -- one or two askings are organic, the rest predate the
        # beta window or are one burst of test traffic. The defect stands
        # on the before/after measurement, not on the count.)
        #
        # Only campuses the PATRON named are admitted. This is not a
        # loosening of the guard: a citation from a campus nobody mentioned
        # is still wrong, and that is the failure the guard exists for.
        if (c.campus == scope_campus or c.campus == "all"
                or c.campus in (also_campuses or ())):
            continue
        failures.append(
            ValidationFailure(
                trigger=RefusalTrigger.CROSS_CAMPUS_MISMATCH,
                detail=(
                    f"Citation [{c.n}] is from campus={c.campus!r} but "
                    f"scope.campus={scope_campus!r}."
                ),
            )
        )

    # --- Decide ---
    if not failures:
        return PostProcessorResult(answer=output)

    # Pick the highest-priority trigger for the user-facing message.
    # Order follows the logical severity: model self-flag first (the
    # model itself said no), then citation invalid (we caught a
    # fabrication), then cross-campus (scope violation). Further
    # failures are logged but the user sees one refusal paragraph.
    priority_order = [
        # Privacy first: a roster dump must surface as the privacy
        # refusal even if other failures co-occur (PII is the most
        # trust-damaging thing the bot can emit).
        RefusalTrigger.STAFF_PRIVACY,
        RefusalTrigger.MODEL_SELF_FLAGGED,
        RefusalTrigger.CITATION_INVALID,
        RefusalTrigger.CROSS_CAMPUS_MISMATCH,
    ]
    primary = next(
        (t for t in priority_order if any(f.trigger == t for f in failures)),
        failures[0].trigger,
    )

    context = _refusal_context_for(primary, scope_campus)
    return PostProcessorResult(
        refusal=Refusal(
            trigger=primary,
            message=_with_closest(render_refusal(primary, context),
                                  _closest_urls(primary, evidence)),
            failures=failures,
            closest_urls=_closest_urls(primary, evidence),
        )
    )


# --- Helpers ---------------------------------------------------------------


def _with_closest(message: str, urls: list) -> str:
    """Append the pages we did find, phrased as a place to look.

    Wording matters here. "The closest page I have" is not a claim about
    what the page says -- the bot is still declining to state the fact. It
    is the difference between an unhelpful dead end and a starting point.
    """
    if not urls:
        return message
    if len(urls) == 1:
        return f"{message}\n\nThe closest page I have is {urls[0]}"
    listed = "\n".join(f"- {u}" for u in urls)
    return f"{message}\n\nThe closest pages I have:\n{listed}"



# Triggers where handing over the retrieved page is right. Deliberately not
# all of them: a cross-campus mismatch means the evidence is for the WRONG
# campus, and a fabricated citation means the url itself is the problem --
# offering either would be handing over exactly what went wrong.
_URLS_STILL_USEFUL = frozenset({
    RefusalTrigger.MODEL_SELF_FLAGGED,
    RefusalTrigger.NO_RESULTS,
    RefusalTrigger.LOW_CONFIDENCE,
})


def _closest_urls(trigger: RefusalTrigger, evidence: Optional[list],
                  limit: int = 3) -> list:
    """Source urls from the evidence, for refusals where they still help."""
    if trigger not in _URLS_STILL_USEFUL or not evidence:
        return []
    out: list = []
    for chunk in evidence:
        url = (getattr(chunk, "source_url", "") or "").strip()
        if url and url not in out:
            out.append(url)
        if len(out) >= limit:
            break
    return out



def _refusal_context_for(
    trigger: RefusalTrigger, scope_campus: str
) -> Optional[RefusalContext]:
    """Build the minimal RefusalContext a given trigger needs.

    Cross-campus is the only post-processor-detected trigger that
    requires context (campus display + staff directory URL). The
    caller is expected to have a campus-display map; post_processor
    keeps its own tiny copy rather than importing from scope.aliases
    so the module has zero intra-package dependencies beyond
    refusal_templates (which is stateless).
    """
    if trigger != RefusalTrigger.CROSS_CAMPUS_MISMATCH:
        return None

    # Kept tiny here; the full map lives in scope/aliases.py. If this
    # ever drifts, the dup is fine because both derive from the same
    # source-of-truth: the six buildings in the plan §8 table.
    display = {
        "oxford": "Oxford",
        "hamilton": "Hamilton",
        "middletown": "Middletown",
    }.get(scope_campus, scope_campus.title())
    # THE REGIONAL CAMPUSES DO NOT GO TO THE LIAISONS PAGE.
    #
    # John Burke, Library Director at Gardner-Harvey (Middletown), 2026-08-13:
    # he asked whether laptop loan periods differ between King and GHL, was
    # told to "ask the Middletown library staff directly -- their directory is
    # at .../liaisons/", and reported that there are no Gardner-Harvey
    # librarians on that list. He is right: liaisons/ is the SUBJECT liaison
    # directory, and the regional campus staff are not subject liaisons.
    #
    # Sending someone to a directory that cannot contain the person they need
    # is the "referral that doesn't make sense" the Head of Advise & Instruct
    # raised on 2026-08-12 -- and it arrives with our name on it, so the
    # recovery lands on a service desk.
    #
    # organization/staff/ is the full staff directory and does list them
    # (verified 2026-08-13: all seven regional staff are in our own Librarian
    # table with campus set -- Krista McDonald, Mark Shores, Brea McQueen and
    # Samantha Young at Hamilton; John Burke, Jennifer Hicks and Leah Tabler
    # at Middletown).
    _LIAISONS = "https://www.lib.miamioh.edu/about/organization/liaisons/"
    _ALL_STAFF = "https://www.lib.miamioh.edu/about/organization/staff/"
    staff_url = {
        # Oxford keeps liaisons/: a subject question at Oxford genuinely does
        # want the subject liaison.
        "oxford": _LIAISONS,
        "hamilton": _ALL_STAFF,
        "middletown": _ALL_STAFF,
    }.get(scope_campus, "https://www.lib.miamioh.edu/")
    return RefusalContext(
        campus_display=display,
        staff_directory_url=staff_url,
    )


__all__ = [
    "Citation",
    "PostProcessorResult",
    "Refusal",
    "SynthesizerOutput",
    "ValidationFailure",
    "process_synthesizer_output",
]
