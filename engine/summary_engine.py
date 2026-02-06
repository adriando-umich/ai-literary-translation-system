# engine/summary_engine.py
# Responsible for STORY SUMMARY memory (init + update)
# Chapter-level, deterministic, TEXT → PARSE → JSON
# Python 3.9 compatible
# Updated to use Google GenAI Native SDK

import os
import time
from typing import Dict, List
from utils.logger import log
from utils.openai_fallback import call_openai_fallback

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
        self.model = "gemini-2.0-flash"  # hoặc model bạn muốn dùng

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
    # LLM CALL (CUSTOM RETRY -> OPENAI -> SAFE MODE -> ERROR)
    # =====================================================
    def _call_llm(self, *, system_prompt: str, user_prompt: str) -> str:
        """
        Logic:
        1. Google (6 attempts, switch models, Block None)
        2. OpenAI Standard (High fidelity)
        3. OpenAI Safe Mode (Sanitized/Abstract instruction)
        4. Raise Error (If all fail -> Stop pipeline, do not return garbage)
        """

        # --- CẤU HÌNH ---
        OPENAI_MODEL_NAME = "gpt-5-nano-2025-08-07"
        OPENAI_RETRIES = 2
        MAX_GOOGLE_ATTEMPTS = 6
        # ----------------

        # 1. Cấu hình Google Safety (Mở hết cỡ)
        safety_settings = [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
        ]
        generate_config = types.GenerateContentConfig(
            safety_settings=safety_settings,
            temperature=0.2,
        )
        full_prompt = f"{system_prompt}\n\nUSER INPUT:\n{user_prompt}"

        # 2. Vòng lặp Google
        for attempt in range(1, MAX_GOOGLE_ATTEMPTS + 1):
            if attempt <= 2:
                current_model = "gemini-2.0-flash"
            elif attempt <= 4:
                current_model = "gemini-2.0-flash-lite"
            else:
                current_model = "gemini-3-flash-preview"

            try:
                log(f"SUMMARY_ENGINE: Google Attempt {attempt}/{MAX_GOOGLE_ATTEMPTS} using [{current_model}]")

                response = self.client.models.generate_content(
                    model=current_model,
                    contents=full_prompt,
                    config=generate_config
                )

                # Check lỗi Hard Block
                if hasattr(response, 'prompt_feedback') and response.prompt_feedback:
                    if "PROHIBITED_CONTENT" in str(response.prompt_feedback):
                        log(f"⚠️ Google Hard Block: {response.prompt_feedback}")
                        break  # Thoát ngay sang OpenAI

                if not response.text:
                    if hasattr(response, 'prompt_feedback'):
                        log(f"⚠️ Google Blocked Input: {response.prompt_feedback}")
                        break
                    raise RuntimeError("Google returned empty response.")

                return response.text.strip()

            except Exception as e:
                log(f"⚠️ Google Error (Attempt {attempt}): {e}")
                if attempt == MAX_GOOGLE_ATTEMPTS: break
                time.sleep(2 if "429" not in str(e) else 10)

        # 3. FALLBACK: OPENAI STANDARD
        log(f"🔄 SWITCHING TO OPENAI FALLBACK (Model: {OPENAI_MODEL_NAME})...")

        try:
            return call_openai_fallback(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model=OPENAI_MODEL_NAME,
                max_retries=OPENAI_RETRIES
            )
        except Exception as e:
            log(f"❌ OpenAI Standard Failed: {e}")
            log("🛡️ Attempting OPENAI SAFE MODE (Sanitized Summary)...")

            # 4. FALLBACK: OPENAI SAFE MODE (Nói giảm nói tránh)
            safe_system_prompt = (
                    system_prompt +
                    "\n\nCRITICAL INSTRUCTION: The previous summary was blocked by safety filters. "
                    "You MUST rewrite this summary using ABSTRACT, CLINICAL, and EUPHEMISTIC language. "
                    "Do NOT describe violence, gore, or sexual acts in detail. "
                    "Focus ONLY on the plot progression and character emotions. "
                    "Make it safe for work (SFW)."
            )

            try:
                # Dùng gpt-4o-mini cho "hiền" hơn
                return call_openai_fallback(
                    system_prompt=safe_system_prompt,
                    user_prompt=user_prompt,
                    model="gpt-4o-mini",
                    max_retries=1
                )
            except Exception as e2:
                # 5. CÙNG ĐƯỜNG -> BÁO LỖI (Raise Error)
                # Để chương trình dừng lại hoặc để hàm gọi xử lý, tuyệt đối không trả rác
                log(f"❌ OpenAI Safe Mode Also Failed: {e2}")
                raise RuntimeError(
                    f"CRITICAL: All AI models (Google & OpenAI) refused content due to Safety/Policy. Last Error: {e2}")

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