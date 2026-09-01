"""
Single source of truth for OpenAI model identifiers.

Every LLM call in the codebase imports from here. Updating a model name
(or call-shape) happens in exactly one place after consulting the latest
OpenAI docs.

================================================================================
MODEL & API FRESHNESS RULE
================================================================================

Whenever an AI assistant (Claude Code, Copilot, etc.) is helping with code
changes that touch the OpenAI client -- model parameters, structured outputs,
prompt caching headers, tool/function calling, streaming, or the Python `openai`
SDK call shape -- it MUST first fetch the latest OpenAI API docs
(https://platform.openai.com/docs) for the model IDs below to confirm:

    1. The exact model identifier string
    2. Supported parameters (some models drop `temperature`, change
       `max_tokens` semantics, etc.)
    3. Current structured-output / response-format syntax
    4. Prompt-cache prefix length and headers
    5. Tool/function-calling schema shape

DO NOT rely on training-data memory of older OpenAI APIs -- model families
change call shapes frequently. If the docs cannot be reached, STOP and ask
before writing code.

================================================================================
MODEL ROUTING POLICY (see plan: Layer 4 -- Prompts and synthesis)
================================================================================

- BASIC_MODEL: agent loop default, LLM-as-judge in eval, light extraction.
- REASONING_MODEL: synthesis when retrieval is ambiguous, tool-calling on
  multi-step queries, clarification generation. Promote from BASIC_MODEL when:
    (a) retrieval returned >5 chunks across multiple `topic` tags (multi-hop)
    (b) classifier confidence was in the clarification band but user opted to
        proceed anyway
    (c) the question contains comparative / multi-step phrasing
- EMBEDDING_MODEL: intent kNN classifier exemplars + document chunks. Single
  embedding model across all use cases so the vector spaces align.

================================================================================
PROMPT CACHE NOTES
================================================================================

OpenAI automatic prompt caching kicks in at >=1024 identical prefix tokens
(verify against current docs at code-change time). Different model IDs have
SEPARATE caches -- switching from BASIC_MODEL to REASONING_MODEL mid-conversation
forfeits the cache for that turn. Factor this into the model-routing decision.
"""

import os
from typing import Literal


# --- Model identifiers (env-driven; one place; .env-managed) -----------------
#
# Three tiers, switchable in .env without code edits. **GPT-5.6 only.**
# Operator ruling 2026-09-01: no model below 5.6 is to appear anywhere in this
# codebase -- not as a tier, not as a fallback, not as a signature default.
#
# Rates read off OpenAI's pricing pages on 2026-09-01, $/1M in / cached / out:
#
#   id              reasoning  ctx      in   / cached / out
#   gpt-5.6-sol     5/5        1.05M    4.00 / 0.40 / 20.00   priced, not wired
#   gpt-5.6-terra   4/5        1.05M    2.00 / 0.20 / 12.00   <- REASONING
#   gpt-5.6-luna    3/5        1.05M    0.20 / 0.02 /  1.20   <- BASIC and CHEAP
#
# SOL sits ABOVE Terra, so our REASONING tier points at the middle model of
# the line, not the top. Whether it should move up is a quality-per-dollar
# decision for the operator and is deliberately not taken here -- but Sol is
# now PRICED in cost_rollup so that switching cannot silently bill $0.
#
# Sol got cheaper on 2026-08-21 (was 5.00 / 0.50 / 30.00). OpenAI calls the
# new rate promotional through at least 2026-11-21.
#
# BASIC and CHEAP are the SAME model today. The tiers stay separate so CHEAP
# can be moved down later without dragging the agent loop with it.
#
# All three are REASONING models (reasoning-token support), expose both
# /v1/chat/completions and /v1/responses, 128K max output, cutoff
# 2025-08-31. Responses API: `input` (user), `instructions` (system),
# `max_output_tokens` (NOT max_tokens), structured output via
# `text.format`:{type:json_schema}, effort via `reasoning.effort`.

BASIC_MODEL: str = os.getenv("LLM_MODEL_BASIC", "gpt-5.6-luna").strip()
"""Easy / surface questions: agent loop default, light extraction.
Env: LLM_MODEL_BASIC."""

REASONING_MODEL: str = os.getenv("LLM_MODEL_REASONING", "gpt-5.6-terra").strip()
"""Hard / sophisticated questions: ambiguous synthesis, multi-step
tool calls, clarification. Env: LLM_MODEL_REASONING."""

CHEAP_MODEL: str = os.getenv("LLM_MODEL_CHEAP", "gpt-5.6-luna").strip()
"""High-volume MECHANICAL calls where weak instruction-following is
low-risk: LLM-as-judge in eval, classifier-fallback, light
extraction/normalization. Currently the SAME model as BASIC (both
luna), so there is no cost gap between them today -- the tiers are kept
separate so CHEAP can be moved down without dragging the agent loop with
it. ~10x cheaper than REASONING.
NEVER route the grounded synthesizer or the tool-calling agent here --
that reintroduces the hallucination/citation failures the rebuild
exists to kill. Env: LLM_MODEL_CHEAP."""

EMBEDDING_MODEL: str = os.getenv(
    "LLM_MODEL_EMBEDDING", "text-embedding-3-large"
).strip()
"""Embedding model for kNN classifier exemplars AND document chunks.
ONE embedding model across all use cases so the vector spaces align
(changing it invalidates the whole index -- re-embed required).
Env: LLM_MODEL_EMBEDDING."""


# --- Call-shape gate (the load-bearing correctness helper) -------------------

def is_reasoning_model(model_id: str) -> bool:
    """True if `model_id` is a REASONING model -> the OpenAI client must
    NOT send `temperature` (reasoning models reject/ignore it; control
    is via `reasoning.effort`). Sending temperature to a reasoning model
    risks a 400.

    All three GPT-5.6 tiers (sol, terra, luna) are reasoning models, so
    in practice this returns True for everything we run. Omitting
    temperature is superset-safe: correct for reasoning models AND
    harmless for non-reasoning ones (they use their default), so the
    match stays deliberately broad -- a prefix, not a list.

    Kept broad ON PURPOSE even though only 5.6 is allowed here now: the
    cost of matching something we never call is nothing, and the cost of
    NOT matching a model somebody wires in later is a 400 on the live
    bot. That is the direction to be wrong in.
    """
    m = (model_id or "").strip().lower()
    return m.startswith("o") or m.startswith("gpt-5")


# --- Budget-driven downgrade -------------------------------------------------


def _budget_forces_cheap() -> bool:
    """True when the budget ladder has downgraded the reasoning tier.

    Imported lazily and swallowed defensively on purpose. This module is
    deliberately dependency-light (os + typing only) because it sits near
    the bottom of the import graph, and resolving a model must never be
    able to fail: any problem reading the budget state means "no
    downgrade", never an exception on a live turn.

    Not logged per call -- it would fire on every reasoning turn. The
    transition is already emailed by scripts/budget_guard.py, and the
    concrete model is recorded per turn as `modelUsed`, so a downgrade is
    visible in the data rather than only in a log line.
    """
    # The EVAL must never be degraded. It exists to measure the system as
    # configured, and run_eval drives this same orchestrator -- so a level-2
    # state during a run would silently score gpt-5.6-luna and report it as
    # the system's quality, which reads as a large regression and is simply
    # a different system. Same class of mistake as editing code mid-run.
    # run_eval sets this for its own process; serving never does.
    if (os.getenv("BUDGET_IGNORE_DEGRADE") or "").strip().lower() in (
            "1", "true", "yes", "on"):
        return False
    try:
        from src.config.budget import current_state
        return current_state().force_cheap_model
    except Exception:  # noqa: BLE001 -- model resolution must never raise
        return False


# --- Type aliases for routing decisions --------------------------------------

ModelTier = Literal["basic", "reasoning", "cheap"]
"""Logical tier consumers pass when they don't care about the exact
model ID -- lets us swap underlying models via .env without touching
call sites."""


def resolve_model(tier: ModelTier) -> str:
    """Resolve a logical tier to the current concrete model ID.

    Always prefer this over hard-coding the constants at call sites.

    Args:
        tier: "basic" (easy/surface), "reasoning" (hard/sophisticated),
            or "cheap" (high-volume mechanical: judge / classifier
            fallback / extraction).

    Returns:
        The current concrete model identifier string.

    Raises:
        ValueError: If `tier` is not a recognized tier.

    Reads the env var at CALL time (module constants are only the
    fallback). The constants are snapshotted at import, and in
    production this module gets imported through main.py's import
    chain BEFORE main.py runs load_dotenv() -- so the snapshot never
    saw the .env values and production silently ran the hardcoded
    defaults regardless of configuration (found 2026-07-17 when a
    .env model upgrade didn't change `model_used` in live turns).
    """
    if tier == "basic":
        return os.getenv("LLM_MODEL_BASIC", "").strip() or BASIC_MODEL
    if tier == "reasoning":
        # Budget level 2 downgrades this tier to the cheap one. Measured
        # 2026-08-04: the reasoning model is 21x the cheap one per call
        # ($0.01379 vs $0.00066 over 1,054 calls) and accounts for 83% of
        # spend on 15% of calls -- so this single substitution removes most
        # of the cost while every feature keeps working. It sits two rungs
        # below refusing students for exactly that reason.
        if _budget_forces_cheap():
            return os.getenv("LLM_MODEL_CHEAP", "").strip() or CHEAP_MODEL
        return os.getenv("LLM_MODEL_REASONING", "").strip() or REASONING_MODEL
    if tier == "cheap":
        return os.getenv("LLM_MODEL_CHEAP", "").strip() or CHEAP_MODEL
    raise ValueError(
        f"Unknown model tier: {tier!r}. Expected 'basic', 'reasoning', "
        f"or 'cheap'."
    )


# --- Cache threshold constant -----------------------------------------------

PROMPT_CACHE_PREFIX_THRESHOLD_TOKENS: int = 1024
"""Minimum identical prefix length (tokens) for OpenAI's automatic prompt
cache to engage. Used by `prompts/builder.py` to assert stable prefixes
clear the threshold. VERIFY against live OpenAI docs at code-change time
-- this constant has changed across model generations."""
