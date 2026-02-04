# engine/summary_engine.py
# Responsible for STORY SUMMARY memory (init + update)
# Chapter-level, deterministic, TEXT → PARSE → JSON
# Python 3.9 compatible
# Updated to use Google GenAI Native SDK

import os
import time
from typing import Dict, List
from utils.logger import log

# === THAY ĐỔI: Dùng thư viện Google GenAI gốc ===
from google import genai
from google.genai import types

# =========================================================
# PROMPTS (TEXT-ONLY, NO JSON) - GIỮ NGUYÊN 100%
# =========================================================

INIT_SUMMARY_PROMPT = """
You are initializing the STORY SUMMARY for a novel.

This is the FIRST narrative chapter of the book.
There is NO existing summary.

GOAL
- Extract ONLY factual information explicitly stated in the chapter.

RULES (ABSOLUTE)
- NO speculation
- NO interpretation
- NO analysis
- NO guessing future events
- Neutral, encyclopedic tone

OUTPUT FORMAT (STRICT, TEXT ONLY):

SETTING:
<text>

CHARACTERS:
- Name: description
- Name: description

WORLD_STATE:
<text>

INITIAL_PREMISE:
<text>

OPEN_QUESTIONS:
- question
- question
"""

UPDATE_SUMMARY_PROMPT = """
You are updating an EXISTING STORY SUMMARY.

INPUTS
1) Current summary (TEXT FORMAT, see below)
2) New chapter text

GOAL
- Update the summary using ONLY new factual information.
- Preserve all existing correct information.
- Keep summary stable and reusable.

RULES (ABSOLUTE)
- NO speculation
- NO interpretation
- NO rewriting unchanged facts
- Only update if NEW FACTS appear

UPDATE GUIDELINES
- CHARACTERS:
  - Add new characters if introduced
  - Update descriptions ONLY if new facts appear
- SETTING / WORLD_STATE:
  - Update ONLY if new rules, places, or systems appear
- OPEN_QUESTIONS:
  - Remove questions clearly answered
  - Add new unresolved questions

CRITICAL FORMAT RULE (ABSOLUTE):
- You MUST output ALL sections below, even if there are NO changes.
- If a section has no updates, REPEAT the content from CURRENT SUMMARY verbatim.
- NEVER omit any section header.

OUTPUT FORMAT (STRICT, TEXT ONLY, SAME STRUCTURE):

SETTING:
...

CHARACTERS:
...

WORLD_STATE:
...

INITIAL_PREMISE:
...

OPEN_QUESTIONS:
...
"""


# =========================================================
# ENGINE
# =========================================================

class SummaryEngine:
    def __init__(self, client=None):
        """
        Modified init:
        - client arg is kept for compatibility with main.py calls,
          BUT we will prefer creating our own Google GenAI client internally
          to ensure we can set BLOCK_NONE safety settings.
        """
        self.model = "gemini-2.5-flash-lite"  # hoặc model bạn muốn dùng

        # Tự lấy Key và tạo Client Google Native để kiểm soát Safety Settings
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            # Fallback nếu main truyền client vào (dù ít an toàn hơn về mặt type check)
            self.client = client
        else:
            self.client = genai.Client(api_key=api_key)

    # -----------------------------------------------------
    # INIT — FIRST NARRATIVE CHAPTER
    # -----------------------------------------------------
    def init_summary(self, chapter_text: str) -> Dict:
        log("SUMMARY_ENGINE: INIT")

        text = self._call_llm(
            system_prompt=INIT_SUMMARY_PROMPT,
            user_prompt=chapter_text,
        )

        return self._parse_summary_text(text)

    # -----------------------------------------------------
    # UPDATE — SUBSEQUENT NARRATIVE CHAPTERS
    # -----------------------------------------------------
    def update_summary(
            self,
            current_summary: Dict,
            chapter_text: str,
    ) -> Dict:
        log("SUMMARY_ENGINE: UPDATE")

        current_text = self._summary_dict_to_text(current_summary)

        combined_input = (
            "CURRENT SUMMARY:\n"
            f"{current_text}\n\n"
            "NEW CHAPTER:\n"
            f"{chapter_text}"
        )

        text = self._call_llm(
            system_prompt=UPDATE_SUMMARY_PROMPT,
            user_prompt=combined_input,
        )

        return self._parse_summary_text(text)

    # =====================================================
    # LLM CALL (UPDATED FOR GOOGLE GENAI NATIVE)
    # =====================================================
    def _call_llm(self, *, system_prompt: str, user_prompt: str) -> str:

        # Cấu hình tắt bộ lọc (BLOCK_NONE) để tránh lỗi 503/400 khi nội dung nhạy cảm
        safety_settings = [
            types.SafetySetting(category="HARM_CATEGORY_HARASSMENT", threshold="BLOCK_NONE"),
            types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH", threshold="BLOCK_NONE"),
            types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="BLOCK_NONE"),
            types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="BLOCK_NONE"),
        ]

        generate_config = types.GenerateContentConfig(
            safety_settings=safety_settings,
            temperature=0.2,  # Giữ thấp như cũ
        )

        # Kết hợp System Prompt và User Prompt vì Google API ưu tiên content liền mạch
        full_prompt = f"{system_prompt}\n\nUSER INPUT:\n{user_prompt}"

        # Logic Retry
        max_retries = 3
        for attempt in range(1, max_retries + 1):
            try:
                response = self.client.models.generate_content(
                    model=self.model,
                    contents=full_prompt,
                    config=generate_config
                )

                if not response.text:
                    reason = "Unknown"
                    if response.candidates:
                        reason = response.candidates[0].finish_reason
                    print(f"--- SUMMARY ERROR: Empty response. Reason: {reason} ---")
                    raise RuntimeError(f"SUMMARY_ENGINE: empty AI response. Reason: {reason}")

                return response.text.strip()

            except Exception as e:
                log(f"SUMMARY API ERROR (Attempt {attempt}): {e}")
                if attempt == max_retries:
                    raise
                time.sleep(2 * attempt)

        raise RuntimeError("SUMMARY_ENGINE: Failed after retries")

    # =====================================================
    # PARSER (DETERMINISTIC, FAIL-LOUD) - GIỮ NGUYÊN
    # =====================================================
    def _parse_summary_text(self, text: str) -> Dict:
        sections = {
            "SETTING": "",
            "CHARACTERS": [],
            "WORLD_STATE": "",
            "INITIAL_PREMISE": "",
            "OPEN_QUESTIONS": [],
        }

        current = None

        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue

            if line.endswith(":") and line[:-1] in sections:
                current = line[:-1]
                continue

            if current is None:
                continue

            if current == "CHARACTERS":
                if line.startswith("-"):
                    sections["CHARACTERS"].append(
                        line.lstrip("- ").strip()
                    )
            elif current == "OPEN_QUESTIONS":
                if line.startswith("-"):
                    sections["OPEN_QUESTIONS"].append(
                        line.lstrip("- ").strip()
                    )
            else:
                if sections[current]:
                    sections[current] += " " + line
                else:
                    sections[current] = line

        # ---------------------------
        # HARD VALIDATION
        # ---------------------------
        if not sections["SETTING"]:
            # Fallback nhẹ nếu AI quên output SETTING nhưng có nội dung khác
            # (Tùy chọn, ở đây giữ nguyên logic fail-loud của bạn)
            raise RuntimeError("SUMMARY PARSE ERROR: missing SETTING")

        if not sections["INITIAL_PREMISE"]:
            raise RuntimeError("SUMMARY PARSE ERROR: missing INITIAL_PREMISE")

        return {
            "setting": sections["SETTING"],
            "characters": sections["CHARACTERS"],
            "world_state": sections["WORLD_STATE"],
            "initial_premise": sections["INITIAL_PREMISE"],
            "open_questions": sections["OPEN_QUESTIONS"],
        }

    # =====================================================
    # SERIALIZER (JSON → TEXT) - GIỮ NGUYÊN
    # =====================================================
    def _summary_dict_to_text(self, summary: Dict) -> str:
        lines: List[str] = []

        lines.append("SETTING:")
        lines.append(summary.get("setting", ""))
        lines.append("")

        lines.append("CHARACTERS:")
        for c in summary.get("characters", []):
            lines.append(f"- {c}")
        lines.append("")

        lines.append("WORLD_STATE:")
        lines.append(summary.get("world_state", ""))
        lines.append("")

        lines.append("INITIAL_PREMISE:")
        lines.append(summary.get("initial_premise", ""))
        lines.append("")

        lines.append("OPEN_QUESTIONS:")
        for q in summary.get("open_questions", []):
            lines.append(f"- {q}")

        return "\n".join(lines)