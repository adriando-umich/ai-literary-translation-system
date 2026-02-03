# utils/json_utils.py
import re

def extract_json(text: str) -> str:
    """
    Extract raw JSON from LLM output.
    Handles:
    - ```json ... ```
    - ``` ... ```
    - raw JSON
    """
    if not text:
        return text

    text = text.strip()

    # Remove fenced code blocks
    if text.startswith("```"):
        # remove opening ``` or ```json
        text = re.sub(r"^```(?:json)?", "", text.strip(), flags=re.IGNORECASE)
        # remove closing ```
        text = re.sub(r"```$", "", text.strip())
        return text.strip()

    return text
