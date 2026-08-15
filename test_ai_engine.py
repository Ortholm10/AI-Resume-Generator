"""Standalone smoke test for src/ai_engine.py against the live Gemini API.

Run with: python test_ai_engine.py
"""

import sys

from src.ai_engine import AIEngineError, enhance_resume_content, get_clarifying_questions

VAGUE_ENTRY = "handled customer complaints"
SPECIFIC_ENTRY = (
    "Resolved 45+ customer escalations weekly as lead support rep, cutting "
    "average resolution time from 3 days to 1 day over 6 months"
)
SAMPLE_ANSWERS = [
    "I handled billing and shipping complaints for an e-commerce team of 8",
    "I cut complaint backlog from 120 to 20 open tickets over 2 months",
]

results = []


def _divider(title):
    print()
    print("=" * 70)
    print(title)
    print("=" * 70)


def _record(case_name, passed, detail=""):
    status = "PASS" if passed else "FAIL"
    results.append((case_name, passed))
    print(f"[{status}] {case_name}")
    if detail:
        print(f"       {detail}")


def _is_list_of_strings(value):
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _is_bullet_dict(value):
    return (
        isinstance(value, dict)
        and isinstance(value.get("bullet_points"), list)
        and all(isinstance(item, str) for item in value["bullet_points"])
    )


# ---------------------------------------------------------------------------
# Case 1: vague entry -> get_clarifying_questions -> expect 1-2 questions
# ---------------------------------------------------------------------------
_divider("Case 1: Vague entry through get_clarifying_questions")
print(f"Input: {VAGUE_ENTRY!r}")
try:
    questions = get_clarifying_questions(VAGUE_ENTRY)
    print(f"Output: {questions}")
    passed = _is_list_of_strings(questions) and 1 <= len(questions) <= 2
    _record(
        "Case 1 - vague entry returns 1-2 questions",
        passed,
        f"got {len(questions) if isinstance(questions, list) else 'non-list'} question(s)",
    )
except Exception as error:  # noqa: BLE001 - test harness must not crash on any case
    print(f"Raised: {type(error).__name__}: {error}")
    _record("Case 1 - vague entry returns 1-2 questions", False, "unexpected exception")


# ---------------------------------------------------------------------------
# Case 2: already-specific entry -> get_clarifying_questions -> expect []
# ---------------------------------------------------------------------------
_divider("Case 2: Specific entry through get_clarifying_questions")
print(f"Input: {SPECIFIC_ENTRY!r}")
try:
    questions = get_clarifying_questions(SPECIFIC_ENTRY)
    print(f"Output: {questions}")
    passed = _is_list_of_strings(questions) and len(questions) == 0
    _record(
        "Case 2 - specific entry returns empty list",
        passed,
        f"got {questions!r}",
    )
except Exception as error:  # noqa: BLE001
    print(f"Raised: {type(error).__name__}: {error}")
    _record("Case 2 - specific entry returns empty list", False, "unexpected exception")


# ---------------------------------------------------------------------------
# Case 3: vague entry + sample answers -> enhance_resume_content -> polished bullet
# ---------------------------------------------------------------------------
_divider("Case 3: Vague entry + sample answers through enhance_resume_content")
print(f"Input entry: {VAGUE_ENTRY!r}")
print(f"Input answers: {SAMPLE_ANSWERS}")
try:
    result = enhance_resume_content(VAGUE_ENTRY, answers=SAMPLE_ANSWERS)
    print(f"Output: {result}")
    passed = _is_bullet_dict(result) and len(result["bullet_points"]) > 0
    _record(
        "Case 3 - vague entry + answers produces polished bullet(s)",
        passed,
        f"got {result!r}",
    )
except Exception as error:  # noqa: BLE001
    print(f"Raised: {type(error).__name__}: {error}")
    _record(
        "Case 3 - vague entry + answers produces polished bullet(s)",
        False,
        "unexpected exception",
    )


# ---------------------------------------------------------------------------
# Case 4: vague entry with no answers -> enhance_resume_content -> runs without crashing
# ---------------------------------------------------------------------------
_divider("Case 4: Vague entry with no answers through enhance_resume_content")
print(f"Input entry: {VAGUE_ENTRY!r}")
print("Input answers: None")
try:
    result = enhance_resume_content(VAGUE_ENTRY, answers=None)
    print(f"Output: {result}")
    passed = _is_bullet_dict(result) and len(result["bullet_points"]) > 0
    _record(
        "Case 4 - vague entry with no answers runs without crashing",
        passed,
        f"got {result!r}",
    )
except Exception as error:  # noqa: BLE001
    print(f"Raised: {type(error).__name__}: {error}")
    _record(
        "Case 4 - vague entry with no answers runs without crashing",
        False,
        "unexpected exception",
    )


# ---------------------------------------------------------------------------
# Case 5: blank/empty string through both functions -> graceful handling
# ---------------------------------------------------------------------------
_divider("Case 5a: Empty string through get_clarifying_questions")
try:
    questions = get_clarifying_questions("")
    print(f"Output: {questions}")
    passed = _is_list_of_strings(questions) and len(questions) == 0
    _record(
        "Case 5a - empty string to get_clarifying_questions returns empty list",
        passed,
        f"got {questions!r}",
    )
except Exception as error:  # noqa: BLE001
    print(f"Raised: {type(error).__name__}: {error}")
    _record(
        "Case 5a - empty string to get_clarifying_questions returns empty list",
        False,
        "unexpected exception (not graceful)",
    )

_divider("Case 5b: Empty string through enhance_resume_content")
try:
    result = enhance_resume_content("")
    print(f"Output: {result}")
    # No exception is also acceptable as long as the shape is sane.
    passed = _is_bullet_dict(result)
    _record(
        "Case 5b - empty string to enhance_resume_content handled gracefully",
        passed,
        f"got {result!r}",
    )
except AIEngineError as error:
    # A controlled, labeled error is graceful handling, not a crash.
    print(f"Raised (expected, controlled): AIEngineError: {error}")
    _record(
        "Case 5b - empty string to enhance_resume_content handled gracefully",
        True,
        "raised AIEngineError with a clear message instead of crashing",
    )
except Exception as error:  # noqa: BLE001
    print(f"Raised (unexpected): {type(error).__name__}: {error}")
    _record(
        "Case 5b - empty string to enhance_resume_content handled gracefully",
        False,
        "unexpected raw exception (not AIEngineError)",
    )


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
_divider("Summary")
total = len(results)
passed_count = sum(1 for _, ok in results if ok)
for name, ok in results:
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
print()
print(f"{passed_count}/{total} cases passed")

if passed_count != total:
    sys.exit(1)
