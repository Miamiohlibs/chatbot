"""
API endpoint for generating AI-powered chat summaries.
Used for LibChat handoff to provide librarians with quick context.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
import os

router = APIRouter(tags=["summarize"])

# Use o4-mini as specified in .env
from src.config.models import resolve_model, is_reasoning_model  # noqa: E402
OPENAI_MODEL = resolve_model("basic")  # env: LLM_MODEL_BASIC -> gpt-5.6-luna
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")


class ChatSummaryRequest(BaseModel):
    """Request model for chat summary generation."""
    chatHistory: str


class ChatSummaryResponse(BaseModel):
    """Response model for chat summary.

    TWO FIELDS, BECAUSE THE TICKET HAS TWO PLACES TO PUT THIS.

    `summary` is the ticket SUBJECT and is capped by LibAnswers at 150
    characters. `recap` is for the ticket BODY, where there is room to say
    what the conversation actually covered.

    They were one field until 2026-08-26, and that made one line do two
    jobs. A real staff test that evening ran eleven turns -- a film studies
    guide, a suicide-research topic, personal-vs-subject librarian, two
    course codes -- and arrived at the librarian as "Film studies research
    guide link". True, and the only thing a reader could see. The operator's
    word for it was that it takes a part for the whole.
    """
    summary: str
    recap: str = ""


# LibAnswers ticket QUESTION (subject) field caps at 150 chars; the ticket
# form prepends a short "[AI] " marker (5 chars), so the summary gets almost
# the whole budget. Cap a touch under 145 for a safety margin.
RECAP_PROMPT = """You are writing the opening of a library help-desk ticket BODY, for a librarian who has not read the chat.

Write a compact account of the WHOLE conversation, in at most 6 short lines. Cover every distinct thing the student raised, in the order they raised it, and say how each one ended.

Format each line as:
- <what they asked> -- <how it ended>

Rules:
- Every distinct topic gets a line, including the ones that went fine. The librarian is deciding where to start, and needs to know what NOT to repeat.
- Say plainly when the bot could not answer, refused, or answered something adjacent to what was asked.
- No preamble, no closing summary, no invented detail. If the chat is short, write fewer lines.

Example:
- Film studies research guide -- named the guide but never gave the link, asked twice
- Research on suicide -- pointed at Primo and the subject librarian
- Personal Librarian vs subject librarian -- bot said it could not tell them who theirs is
- Course codes CSE 485 and PSY 201 -- gave the right subject librarian for each"""


SUBJECT_CHAR_LIMIT = 140


def _fit_subject(text: str, limit: int = SUBJECT_CHAR_LIMIT) -> str:
    """Collapse whitespace and trim to <= limit chars at a WORD boundary
    (never mid-word), adding an ellipsis when truncated."""
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0].rstrip(" ,.;:—-")
    return (cut or text[:limit]).rstrip() + "…"


@router.post("/summarize-chat", response_model=ChatSummaryResponse)
async def summarize_chat(request: ChatSummaryRequest):
    """
    Generate an AI-powered summary of a chat conversation.
    
    This endpoint is used when users hand off to human librarians,
    providing a concise summary of:
    - Main question/topic
    - Key information discussed
    - Current status/outcome
    
    Args:
        request: ChatSummaryRequest containing the chat history
        
    Returns:
        ChatSummaryResponse with the generated summary
    """
    try:
        # Initialize OpenAI chat model using o4-mini pattern from system
        # o4-mini doesn't support temperature parameter
        llm_kwargs = {"model": OPENAI_MODEL, "api_key": OPENAI_API_KEY}
        if not is_reasoning_model(OPENAI_MODEL):  # reasoning models reject temperature
            llm_kwargs["temperature"] = 0.3  # Lower temperature for focused summaries
        
        llm = ChatOpenAI(**llm_kwargs)

        # The summary goes into the LibAnswers ticket QUESTION (subject)
        # field, which is capped at 150 chars; the ticket form prepends a
        # ~42-char "Summarized by AI" marker, so anything past ~108 chars
        # was cut mid-word in the subject (prod 2026-06-17). Ask for a
        # short one-line subject, not a multi-sentence paragraph.
        #
        # Rewritten 2026-08-10. The old prompt asked for "the user's main
        # question(s)" over the transcript and ended the user turn with
        # "Subject:", which reliably produced a summary of the LAST
        # exchange only -- students routinely open with something small,
        # get it answered, and only then ask the thing they actually came
        # for, and that was the part the librarian never saw. It also
        # listed everything discussed, so a ticket whose real content was
        # one stuck question arrived padded with three the bot had
        # already handled. A librarian reads this one line before
        # deciding what to do; anything already resolved is noise.
        system_prompt = """You are writing the SUBJECT LINE of a library help-desk ticket. A librarian reads this one line before deciding what to do with the ticket, so it must carry the thing they have to act on -- nothing else.

Read the WHOLE conversation before writing. Students often open with a small question, get it answered, and only then ask the thing they actually came for.

Write ONE line, at most ~130 characters (about 20 words):

- Lead with what the student STILL NEEDS: the question the bot did not resolve, or the point where its answer was wrong, partial, or a refusal.
- Keep the specifics a librarian needs to act -- subject, building, course, date, item, campus.
- LEAVE OUT anything the bot already handled. If the student asked four things and three were answered, name only the fourth.
- If MORE THAN ONE thing is unresolved, name them all, separated by "; ". Picking one and dropping the others is how a librarian ends up solving the smaller problem. Two or three is normal; if there are more than three, name the three that cost the student the most.
- If nothing went wrong and nothing is unresolved, just name what the student was working on. Do NOT invent a problem or a sticking point.

No preamble, no "the user asked", no full sentence, no trailing period.

Examples:
- Chat covers hours (answered), then fails to find a peer-reviewed article -> "Peer-reviewed articles on insomnia and academic performance"
- Chat books a room fine, then bot cannot say if the room has a projector -> "Whether King group study rooms have projectors"
- Chat where everything was answered -> "Renewing OhioLINK books"
- Bot gave a wrong loan period and the student pushed back -> "Reserve textbook loan period -- bot's answer contradicted by student"
- Two things left hanging in one chat -> "Film studies guide link; whether a Personal Librarian is assigned\""""



        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(
                content=(
                    "Full conversation, oldest message first:\n"
                    f"{request.chatHistory}\n\n"
                    "Subject line (what the librarian still has to deal with):"
                )
            ),
        ]

        # Both calls at once. They read the same transcript and neither
        # depends on the other, so serialising them would only make the
        # librarian wait twice.
        import asyncio

        recap_messages = [
            SystemMessage(content=RECAP_PROMPT),
            HumanMessage(
                content=(
                    "Full conversation, oldest message first:\n"
                    f"{request.chatHistory}\n\n"
                    "What the conversation covered, and how each part ended:"
                )
            ),
        ]
        subject_res, recap_res = await asyncio.gather(
            llm.ainvoke(messages),
            llm.ainvoke(recap_messages),
            return_exceptions=True,
        )

        if isinstance(subject_res, BaseException):
            raise subject_res
        summary = _fit_subject(subject_res.content.strip())

        # A recap that failed must not cost the subject. The subject is what
        # the ticket cannot be filed without; the recap is an improvement on
        # top of it, and an outage on one call should degrade to what we had
        # before rather than to nothing.
        recap = ""
        if not isinstance(recap_res, BaseException):
            recap = recap_res.content.strip()

        return ChatSummaryResponse(summary=summary, recap=recap)
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate summary: {str(e)}"
        )
