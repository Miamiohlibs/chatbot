"""Multi-turn scenarios, run against the real production socket.

WHY A SECOND SUITE
    The golden set is 234 SINGLE-turn questions. Every case starts a fresh
    conversation, so nothing in it can catch a failure that only exists
    across turns -- and those are the ones patrons actually hit.

    The proof: on 2026-08-25 the operator asked "subject guide for film
    studies", got a good answer, then asked "where is the link". That was
    classified on its own, landed on interlibrary_loan because of the word
    "link", and handed over the ILL url. The golden set scored 76.9% that
    same night and could not have seen it.

WHAT MAKES A SCENARIO WORTH ADDING
    It has to fail for a reason that needs MORE THAN ONE TURN to exist:

      anaphora     a later turn refers back ("the link", "that one", "it")
      flow state   a process spanning turns, with an interruption in it
      carry-over   scope or subject set early and relied on later
      correction   the patron pushes back on an answer

    A scenario that would behave identically as one turn belongs in the
    golden set instead, where it is cheaper to run.

WHAT `expect` IS FOR
    Plain English, read by the judge alongside the transcript. It describes
    the MULTI-TURN obligation -- what the last turn has to get right GIVEN
    the earlier ones -- not whether individual facts are correct. Fact
    checking is the golden set's job.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Scenario:
    id: str
    kind: str
    """anaphora | flow_state | carry_over | correction"""
    turns: "list[str]"
    expect: str
    """What the FINAL answer must do, given everything before it."""
    also_check: "list[str]" = field(default_factory=list)
    """Turn indexes (0-based) whose answers the judge should also read.
    Empty means only the last turn is judged."""


SCENARIOS: "tuple[Scenario, ...]" = (

    # --- anaphora: a later turn refers back --------------------------------
    Scenario(
        id="anaphora_guide_link",
        kind="anaphora",
        turns=["subject guide for film studies", "where is the link"],
        expect=(
            "The second answer must give the link(s) the first answer was "
            "talking about -- the research guides page and/or the subject "
            "librarian page. Handing over an Interlibrary Loan url, or any "
            "url unrelated to research guides, is the failure this scenario "
            "exists for."
        ),
    ),
    Scenario(
        id="anaphora_hours_that_one",
        kind="anaphora",
        turns=["what time does King close today", "what about tomorrow"],
        expect=(
            "The second answer must be about KING's hours tomorrow. Asking "
            "which library, or answering for a different building, means "
            "the subject set in turn one was lost."
        ),
    ),
    Scenario(
        id="anaphora_librarian_pronoun",
        kind="anaphora",
        turns=["who is the psychology librarian",
               "what is their email"],
        expect=(
            "The second answer must give the email of the person named in "
            "the first answer. Naming a different person, or asking who "
            "they mean, means the referent was lost."
        ),
    ),
    Scenario(
        id="anaphora_book_it",
        kind="anaphora",
        turns=["do you have study rooms at King",
               "how do I book one"],
        expect=(
            "The second answer must be about booking a King study room "
            "specifically -- the reservation page or the steps. A generic "
            "answer about a different library is a carry-over failure."
        ),
    ),

    # --- flow state: a process, with an interruption ------------------------
    Scenario(
        id="flow_booking_interrupted",
        kind="flow_state",
        turns=["I want to book a study room",
               "wait, what time does King close today",
               "ok, tomorrow 2pm to 4pm"],
        expect=(
            "The third turn must be understood as continuing the room "
            "booking -- asking for the remaining details, or confirming the "
            "slot. Treating 'tomorrow 2pm to 4pm' as a new unrelated "
            "question, or refusing it as out of scope, is the failure. A "
            "patron interrupting their own booking with one question is "
            "normal, not an edge case."
        ),
        also_check=[1],
    ),
    Scenario(
        id="flow_booking_then_cancel",
        kind="flow_state",
        turns=["book me a study room at King tomorrow at 3pm",
               "actually never mind"],
        expect=(
            "The second answer must acknowledge the withdrawal and stop "
            "asking for booking details. Continuing to collect name and "
            "email after the patron backed out is the failure."
        ),
    ),
    Scenario(
        id="flow_subject_then_answer",
        kind="flow_state",
        turns=["I need help with research",
               "nursing"],
        expect=(
            "The bare word 'nursing' after a research question must be read "
            "as naming the SUBJECT, and get the nursing subject librarian or "
            "nursing guide. Refusing it as out of scope is the failure -- a "
            "one-word reply to our own question must not be treated as a "
            "new topic."
        ),
    ),

    # --- carry-over: scope set early, relied on later ----------------------
    Scenario(
        id="carry_campus_switch",
        kind="carry_over",
        turns=["what are the hours at Rentschler",
               "and the Oxford one"],
        expect=(
            "The second answer must be about an OXFORD library's hours "
            "(King, or asking which Oxford library). Repeating Hamilton's "
            "hours means the campus switch in turn two was ignored."
        ),
    ),
    Scenario(
        id="carry_scope_sticky",
        kind="carry_over",
        turns=["I'm at the Hamilton campus library",
               "how late are you open"],
        expect=(
            "The second answer must be about Rentschler / Hamilton, because "
            "the patron said where they are. Defaulting to King's Oxford "
            "hours is the failure."
        ),
    ),
    Scenario(
        id="carry_topic_then_narrow",
        kind="carry_over",
        turns=["I want to research suicide prevention",
               "who can help me with that"],
        expect=(
            "The second answer must connect 'that' to the topic named in "
            "turn one and name a relevant subject librarian, or ask for the "
            "subject if it genuinely cannot infer one. Answering with a "
            "generic 'librarians are assigned by subject, tell me yours' "
            "when the subject was just stated is the failure."
        ),
    ),

    # --- correction: the patron pushes back --------------------------------
    Scenario(
        id="correction_pushback",
        kind="correction",
        turns=["how long can I keep a laptop from the library",
               "that doesn't sound right, I was told it was different"],
        expect=(
            "The second answer must not simply repeat the first as though "
            "the pushback did not happen, and must not invent a new figure "
            "to please the patron. Acknowledging the uncertainty and "
            "pointing at the circulation policy page or a human is correct."
        ),
    ),
    Scenario(
        id="correction_wrong_building",
        kind="correction",
        turns=["is there a makerspace at Rentschler",
               "no I meant the one in Oxford"],
        expect=(
            "The second answer must be about the Oxford MakerSpace at King "
            "Library. Repeating the Rentschler answer means the correction "
            "was not taken."
        ),
    ),
)


__all__ = ["Scenario", "SCENARIOS"]
