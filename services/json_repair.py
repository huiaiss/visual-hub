"""JSON repair utilities for truncated or malformed AI outputs."""
import re


def repair_truncated_json(text: str) -> str:
    """Attempt to repair truncated JSON by closing unclosed brackets and braces.

    Handles the common case where an LLM response is cut off mid-generation,
    leaving incomplete JSON structures.
    """
    if not text or not isinstance(text, str):
        return text

    text = text.strip()

    # Remove trailing commas before closing brackets (JSON spec violation)
    text = re.sub(r",\s*([}\]])", r"\1", text)

    # Count and close unclosed structures
    open_braces = text.count("{") - text.count("}")
    open_brackets = text.count("[") - text.count("]")

    # Close any unclosed strings
    in_string = False
    fixed = []
    for ch in text:
        if ch == '"' and (not fixed or fixed[-1] != '\\'):
            in_string = not in_string
        fixed.append(ch)
    if in_string:
        fixed.append('"')
    text = "".join(fixed)

    # Close unclosed structures from inside out
    text += "]" * max(0, open_brackets)
    text += "}" * max(0, open_braces)

    return text
