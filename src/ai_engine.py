"""Gemini-powered helpers for clarifying and polishing resume entries."""

import json
import logging
import os
import time

from dotenv import load_dotenv
from google import genai
from google.genai import errors as genai_errors
from google.genai import types

load_dotenv()

logger = logging.getLogger(__name__)

MODEL_NAME = "gemini-flash-lite-latest"
MAX_RETRIES = 3
INITIAL_BACKOFF_SECONDS = 2

RATE_LIMIT_MESSAGE = (
    "The AI service is busy (rate limit reached). Please wait a minute and "
    "try again."
)
GENERIC_FAILURE_MESSAGE = (
    "The AI service could not complete this request right now. Please try "
    "again in a moment."
)

SYSTEM_INSTRUCTION = (
    "You are a resume-writing assistant. Follow these rules strictly:\n"
    "1. Never invent facts, numbers, employers, job titles, dates, or "
    "credentials that are not explicitly present in the user's input. If "
    "information is missing, leave it out rather than guessing or "
    "estimating.\n"
    "2. Avoid generic filler phrases such as 'team player', "
    "'results-driven', 'hard worker', 'go-getter', or 'detail-oriented' "
    "that carry no specific information.\n"
    "3. Prefer concise, specific, direct language over longer, softer, or "
    "flowery phrasing.\n"
    "Respond with valid JSON only, matching the requested schema, and "
    "nothing else."
)

ENHANCE_SYSTEM_INSTRUCTION = (
    "You are a resume-writing assistant that turns a user's rough "
    "description of their work into a polished, professional resume "
    "bullet point. Follow these rules strictly:\n"
    "1. Never invent NEW facts, numbers, employers, job titles, dates, or "
    "credentials that are not explicitly present in the user's input. If "
    "information is missing, leave it out rather than guessing or "
    "estimating. This rule forbids fabricating facts — it does NOT forbid "
    "professionally rewriting, restructuring, or elaborating on the facts "
    "that ARE given.\n"
    "2. You MAY and SHOULD rephrase and restructure the input using "
    "standard professional resume phrasing: start with a strong action "
    "verb, use natural resume-style elaboration, and present the same "
    "facts the way an experienced resume writer would. A bullet that is "
    "just the user's input restated near-verbatim, with only minor word "
    "swaps, is NOT acceptable — it must read as properly polished, not as "
    "a light edit of the original sentence.\n"
    "3. Target roughly 15-30 words per bullet point. This is the standard "
    "length for a professional resume bullet: long enough to sound "
    "elaborated and complete, but not a sprawling paragraph. A bullet that "
    "is only a few words longer than the raw input is under-elaborated; a "
    "bullet stretching well past 30 words is over-written.\n"
    "4. If clarifying details/answers are supplied alongside the original "
    "entry, you MUST weave the specific details from those answers into "
    "the final bullet point itself — do not ignore them or leave them "
    "as generic mentions.\n"
    "5. Avoid generic filler phrases such as 'team player', "
    "'results-driven', 'hard worker', 'go-getter', or 'detail-oriented' "
    "that carry no specific information. Every word should tie back to a "
    "concrete fact from the input, not be buzzword padding.\n"
    "6. Prefer concise, specific, direct language over vague or flowery "
    "phrasing — elaboration means fuller professional framing of the real "
    "facts, not adding fluff.\n\n"
    "Examples of turning an under-elaborated input into a properly "
    "polished bullet (these are illustrations of the transformation, not "
    "verbatim text to reuse):\n"
    '- Input: "handled 30 customer complaints per week" -> Bullet: '
    '"Resolved an average of 30 customer service complaints weekly, '
    'maintaining consistent quality and response standards."\n'
    '- Input: "wrote code for the checkout page" -> Bullet: "Developed '
    'and implemented the checkout page functionality, contributing '
    'directly to the site\'s core purchasing flow."\n'
    '- Input: "trained 5 new hires" (clarifying answer: "training covered '
    'POS system and safety procedures") -> Bullet: "Trained 5 new hires '
    'on point-of-sale operations and safety procedures, ensuring a '
    'smooth onboarding experience."\n\n'
    "Respond with valid JSON only, matching the requested schema, and "
    "nothing else."
)

_client = None


class AIEngineError(Exception):
    """Raised when the Gemini API cannot fulfill a request."""


def _get_client():
    global _client
    if _client is None:
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise AIEngineError(
                "GOOGLE_API_KEY is not set. Add it to your .env file."
            )
        _client = genai.Client(api_key=api_key)
    return _client


def _is_rate_limit_error(error):
    if isinstance(error, genai_errors.APIError):
        if error.code == 429:
            return True
        if error.status and "RESOURCE_EXHAUSTED" in error.status.upper():
            return True
    message = str(error).upper()
    return "429" in message or "RESOURCE_EXHAUSTED" in message or "QUOTA" in message


def _generate_with_retry(contents, response_schema, system_instruction=SYSTEM_INSTRUCTION):
    client = _get_client()
    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        response_mime_type="application/json",
        response_schema=response_schema,
        temperature=0.4,
    )

    delay = INITIAL_BACKOFF_SECONDS
    last_error = None

    for attempt in range(MAX_RETRIES + 1):
        try:
            return client.models.generate_content(
                model=MODEL_NAME,
                contents=contents,
                config=config,
            )
        except Exception as error:  # noqa: BLE001 - broad by design, re-raised as AIEngineError
            last_error = error
            if _is_rate_limit_error(error) and attempt < MAX_RETRIES:
                logger.warning(
                    "Gemini rate limit hit (attempt %s/%s); retrying in %ss",
                    attempt + 1,
                    MAX_RETRIES,
                    delay,
                )
                time.sleep(delay)
                delay *= 2
                continue
            break

    if _is_rate_limit_error(last_error):
        raise AIEngineError(RATE_LIMIT_MESSAGE) from last_error
    raise AIEngineError(GENERIC_FAILURE_MESSAGE) from last_error


def _parse_json(raw_text, fallback):
    try:
        return json.loads(raw_text)
    except (json.JSONDecodeError, TypeError):
        logger.warning("Gemini returned malformed JSON: %r", raw_text)
        return fallback


def get_clarifying_questions(entry_text):
    """Return up to 2 short follow-up questions if entry_text is vague on
    scope, measurable outcome, or individual vs. team contribution.

    Returns an empty list if the entry is already specific, or if the entry
    is empty.
    """
    if not entry_text or not entry_text.strip():
        return []

    prompt = (
        "Review the following resume entry. If it is vague about "
        "(a) the scope of the work, (b) a measurable outcome or result, or "
        "(c) whether the contribution was individual or part of a team, "
        "write up to 2 short, specific follow-up questions that would help "
        "clarify it. If the entry already covers these clearly, return an "
        "empty list.\n\n"
        f'Resume entry:\n"""\n{entry_text}\n"""\n\n'
        'Respond as JSON: {"questions": ["...", "..."]} with at most 2 '
        "items. Use an empty array if no clarification is needed."
    )

    schema = types.Schema(
        type=types.Type.OBJECT,
        properties={
            "questions": types.Schema(
                type=types.Type.ARRAY,
                items=types.Schema(type=types.Type.STRING),
                max_items=2,
            )
        },
        required=["questions"],
    )

    response = _generate_with_retry(prompt, schema)
    data = _parse_json(response.text, fallback={"questions": []})

    questions = data.get("questions", []) if isinstance(data, dict) else []
    return [q.strip() for q in questions if isinstance(q, str) and q.strip()][:2]


def enhance_resume_content(entry_text, answers=None, tone=None, target_role=None):
    """Turn entry_text (plus optional clarifying answers) into polished
    resume bullet points.

    Works directly from entry_text alone if no answers are supplied, so it
    can run even when get_clarifying_questions failed or was skipped.

    Returns a dict: {"bullet_points": [str, ...]}.
    """
    if not entry_text or not entry_text.strip():
        raise AIEngineError("No resume entry text was provided to enhance.")

    answers = answers or []
    answer_lines = "\n".join(f"- {a}" for a in answers if a and str(a).strip())

    context_parts = [f'Original resume entry:\n"""\n{entry_text}\n"""']
    if answer_lines:
        context_parts.append(f"Additional clarifying details:\n{answer_lines}")
    if tone:
        context_parts.append(f"Desired tone: {tone}")
    if target_role:
        context_parts.append(f"Target role: {target_role}")

    prompt = (
        "Rewrite the resume entry below into polished, professional resume "
        "bullet points, using only the information given. Do not just "
        "restate the entry near-verbatim — rephrase it with strong resume "
        "phrasing and natural elaboration, aiming for roughly 15-30 words "
        "per bullet. If clarifying details are provided, weave those "
        "specific details into the bullet itself.\n\n"
        + "\n\n".join(context_parts)
        + '\n\nRespond as JSON: {"bullet_points": ["...", "..."]}'
    )

    schema = types.Schema(
        type=types.Type.OBJECT,
        properties={
            "bullet_points": types.Schema(
                type=types.Type.ARRAY,
                items=types.Schema(type=types.Type.STRING),
            )
        },
        required=["bullet_points"],
    )

    response = _generate_with_retry(
        prompt, schema, system_instruction=ENHANCE_SYSTEM_INSTRUCTION
    )

    fallback = {"bullet_points": [entry_text.strip()]}
    data = _parse_json(response.text, fallback=fallback)
    if not isinstance(data, dict) or not data.get("bullet_points"):
        data = fallback

    bullet_points = [
        b.strip()
        for b in data.get("bullet_points", [])
        if isinstance(b, str) and b.strip()
    ]
    return {"bullet_points": bullet_points or [entry_text.strip()]}
