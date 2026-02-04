# utils/json_utils.py
import re
import json
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


def rescue_incomplete_json(text: str) -> list:
    """
    Tìm tất cả các object {...} hợp lệ trong một chuỗi JSON dở dang.
    """
    # Regex tìm các block có cấu trúc {"source":..., "target":...}
    pattern = r'\{[^{}]*"source"[^{}]*"target"[^{}]*\}'
    matches = re.findall(pattern, text, re.DOTALL)

    results = []
    for m in matches:
        try:
            # Làm sạch các ký tự điều khiển nếu có
            clean_m = re.sub(r'[\x00-\x1F\x7F]', '', m)
            results.append(json.loads(clean_m))
        except:
            continue
    return results