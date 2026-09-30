"""
Tolerant JSON extraction for LLM responses.

Models wrap JSON in prose or markdown fences even when told not to. The old
approach - re.search(r'\\{.*\\}', text, re.DOTALL) - is greedy: it spans from
the first '{' to the *last* '}' in the whole response, so any trailing prose
containing a brace, or a second JSON block, produces invalid JSON.

This module instead scans for the first balanced object, respecting string
literals and escapes.
"""

import json
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


def extract_json(text: str) -> Optional[Any]:
    """
    Pull the first complete JSON object or array out of an LLM response.

    Returns the parsed value, or None if nothing valid was found.
    """
    if not text:
        return None

    candidate = _strip_code_fences(text.strip())

    # Fast path: the whole response is JSON, as instructed.
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass

    # Otherwise find the first balanced {...} or [...] block.
    for opener, closer in (("{", "}"), ("[", "]")):
        block = _first_balanced_block(candidate, opener, closer)
        if block:
            try:
                return json.loads(block)
            except json.JSONDecodeError:
                continue

    logger.warning("No valid JSON found in response (%d chars)", len(text))
    return None


def _strip_code_fences(text: str) -> str:
    """Remove a surrounding ```json ... ``` fence if present."""
    if not text.startswith("```"):
        return text

    lines = text.splitlines()
    # Drop the opening fence (with optional language tag).
    lines = lines[1:]
    # Drop the closing fence, wherever it is.
    for i, line in enumerate(lines):
        if line.strip().startswith("```"):
            lines = lines[:i]
            break

    return "\n".join(lines).strip()


def _first_balanced_block(text: str, opener: str, closer: str) -> Optional[str]:
    """
    Return the first substring that opens with `opener` and closes balanced.

    String contents are skipped so braces inside values don't affect depth.
    """
    start = text.find(opener)
    if start == -1:
        return None

    depth = 0
    in_string = False
    escaped = False

    for i in range(start, len(text)):
        char = text[i]

        if escaped:
            escaped = False
            continue

        if char == "\\":
            escaped = True
            continue

        if char == '"':
            in_string = not in_string
            continue

        if in_string:
            continue

        if char == opener:
            depth += 1
        elif char == closer:
            depth -= 1
            if depth == 0:
                return text[start:i + 1]

    return None
