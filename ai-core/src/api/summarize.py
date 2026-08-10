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
OPENAI_MODEL = resolve_model("basic")  # env: LLM_MODEL_BASIC (default gpt-5.4-mini)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")


class ChatSummaryRequest(BaseModel):
    """Request model for chat summary generation."""
    chatHistory: str


class ChatSummaryResponse(BaseModel):
    """Response model for chat summary."""
    summary: str


# LibAnswers ticket QUESTION (subject) field caps at 150 chars; the ticket
# form prepends a short "[AI] " marker (5 chars), so the summary gets almost
# the whole budget. Cap a touch under 145 for a safety margin.
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
- If nothing went wrong and nothing is unresolved, just name what the student was working on. Do NOT invent a problem or a sticking point.

No preamble, no "the user asked", no full sentence, no trailing period.

Examples:
- Chat covers hours (answered), then fails to find a peer-reviewed article -> "Peer-reviewed articles on insomnia and academic performance"
- Chat books a room fine, then bot cannot say if the room has a projector -> "Whether King group study rooms have projectors"
- Chat where everything was answered -> "Renewing OhioLINK books"
- Bot gave a wrong loan period and the student pushed back -> "Reserve textbook loan period -- bot's answer contradicted by student\""""

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

        # Generate summary using async invoke (matching system pattern)
        response = await llm.ainvoke(messages)
        summary = _fit_subject(response.content.strip())

        return ChatSummaryResponse(summary=summary)
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate summary: {str(e)}"
        )
