# engine/character_engine.py
# Responsibility:
# - Track Characters & Pronouns
# - Uses Google GenAI Native SDK (to bypass safety filters)

from typing import List, Dict
from utils.logger import log
import time
import os

# === THAY ĐỔI: Dùng thư viện Google GenAI gốc ===
from google import genai
from google.genai import types

# =========================================================
# RETRY CONFIG (UNIFIED TEMPLATE)
# =========================================================
CHARACTER_MAX_RETRIES = 4
CHARACTER_BASE_DELAY = 2.0  # seconds (linear backoff)

# =========================================================
# PROMPTS (GIỮ NGUYÊN 100%)
# =========================================================

COMMON_RULES = """
RULES:
- ONLY characters present in the text.
- NO speculation.
- Infer 'vi_pronoun' (Vietnamese 3rd-person pronoun) based on gender, age, and status (e.g., anh, cô, ông, bà, hắn, y, nàng, nó).
- Use 'anh' as default if gender is unknown but character is likely male.
"""

INIT_CHARACTER_PROMPT = f"""
You are initializing the CHARACTER CONTEXT for a novel.
This is the FIRST narrative chapter.

{COMMON_RULES}

OUTPUT FORMAT (STRICT, TEXT ONLY):
CHARACTERS:
- Name | role | description | vi_pronoun
"""

UPDATE_CHARACTER_PROMPT = f"""
You are updating an EXISTING CHARACTER CONTEXT.
{COMMON_RULES}
- DO NOT remove existing characters.
- For NEW characters, infer 'vi_pronoun'.

OUTPUT FORMAT (STRICT, TEXT ONLY):
CHARACTERS:
- Name | role | description | vi_pronoun
"""


# =========================================================
# ENGINE
# =========================================================

class CharacterEngine:
    def __init__(self, client=None):
        """
        Khởi tạo Client Google Native nội bộ để kiểm soát Safety Settings.
        """
        self.model = "gemini-2.5-flash-lite"

        # Tự lấy Key từ môi trường để đảm bảo tương thích
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            # Fallback nếu truyền client từ ngoài vào (ít khuyến khích hơn)
            self.client = client
        else:
            self.client = genai.Client(api_key=api_key)

    def init_characters(self, chapter_text: str) -> List[Dict]:
        log("CHARACTER_ENGINE: INIT (First Narrative + Pronoun Inference)")
        text = self._call_llm(
            system_prompt=INIT_CHARACTER_PROMPT,
            user_prompt=chapter_text,
        )
        return self._parse_character_text(text)

    def update_characters(self, current_characters: List[Dict], chapter_text: str) -> List[Dict]:
        log("CHARACTER_ENGINE: UPDATE")
        current_text = self._characters_to_text(current_characters)

        combined_input = (
            f"CURRENT CHARACTERS:\n{current_text}\n\n"
            f"NEW CHAPTER:\n{chapter_text}"
        )

        text = self._call_llm(
            system_prompt=UPDATE_CHARACTER_PROMPT,
            user_prompt=combined_input,
        )

        new_extracted = self._parse_character_text(text)

        # 🔒 CRITICAL INVARIANT: Bảo vệ các đại từ đã LOCK từ trước
        locked_data = {c["name"]: c["vi_pronoun"] for c in current_characters}

        final = []
        for c in new_extracted:
            if c["name"] in locked_data:
                # Nếu nhân vật đã có trong database, dùng lại đại từ cũ (LOCKED)
                # Kể cả AI chương này có gợi ý khác đi
                c["vi_pronoun"] = locked_data[c["name"]]
            else:
                log(f"CHARACTER_ENGINE: New character [{c['name']}] locked as [{c['vi_pronoun']['default']}]")
            final.append(c)

        return final

    # =====================================================
    # LLM CALL (ĐÃ SỬA SANG GOOGLE GENAI NATIVE)
    # =====================================================
    def _call_llm(self, *, system_prompt: str, user_prompt: str) -> str:

        # Cấu hình tắt bộ lọc (BLOCK_NONE) để tránh lỗi với nhân vật phản diện/bạo lực
        safety_settings = [
            types.SafetySetting(category="HARM_CATEGORY_HARASSMENT", threshold="BLOCK_NONE"),
            types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH", threshold="BLOCK_NONE"),
            types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="BLOCK_NONE"),
            types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="BLOCK_NONE"),
        ]

        generate_config = types.GenerateContentConfig(
            safety_settings=safety_settings,
            temperature=0.1,  # Giữ thấp để output ổn định
        )

        # Google API thích nhận prompt gộp
        full_prompt = f"{system_prompt}\n\nDATA:\n{user_prompt}"

        last_error = None

        for attempt in range(1, CHARACTER_MAX_RETRIES + 1):
            try:
                log(f"CHARACTER_ENGINE: API call attempt {attempt}")

                # Gọi API bằng thư viện mới
                response = self.client.models.generate_content(
                    model=self.model,
                    contents=full_prompt,
                    config=generate_config
                )

                if not response.text:
                    reason = "Unknown"
                    if response.candidates:
                        reason = response.candidates[0].finish_reason
                    raise RuntimeError(f"Empty LLM response. Reason: {reason}")

                return response.text.strip()

            except Exception as e:
                last_error = e
                log(f"⚠️ CHARACTER_ENGINE API ERROR attempt {attempt}: {e}")

                if attempt < CHARACTER_MAX_RETRIES:
                    delay = CHARACTER_BASE_DELAY * attempt
                    log(f"CHARACTER_ENGINE: retrying in {delay:.1f}s")
                    time.sleep(delay)

        raise RuntimeError("CHARACTER_ENGINE FAILED after retries") from last_error

    def _parse_character_text(self, text: str) -> List[Dict]:
        lines = [l.strip() for l in text.splitlines() if l.strip()]

        # Tìm dòng chứa Header để bắt đầu parse (tránh lỗi nếu AI nói nhảm ở đầu)
        start_idx = 0
        header_found = False
        for i, line in enumerate(lines):
            if "CHARACTERS" in line:
                start_idx = i
                header_found = True
                break

        if not header_found:
            # Nếu quá nghiêm ngặt có thể raise error, hoặc thử parse luôn
            raise RuntimeError("CHARACTER PARSE ERROR: missing header 'CHARACTERS:'")

        # Cắt bỏ phần rác ở trên header
        lines = lines[start_idx:]

        characters = []
        for line in lines:
            if not line.startswith("-"): continue

            # Giới hạn split=3 để tránh lỗi nếu description có dấu "|"
            parts = [p.strip() for p in line.lstrip("- ").split("|", 3)]

            if len(parts) < 3: continue

            name, role, desc = parts[0], parts[1], parts[2]
            # Lấy pronoun từ cột 4, nếu AI quên thì mặc định 'anh'
            p_val = parts[3].lower() if len(parts) >= 4 else "anh"

            characters.append({
                "name": name,
                "role": role,
                "description": desc,
                "vi_pronoun": {
                    "default": p_val,
                    "allowed": [p_val],
                    "locked": True
                },
                "relationships": []
            })
        return characters

    def _characters_to_text(self, characters: List[Dict]) -> str:
        lines = ["CHARACTERS:"]
        for c in characters:
            p = c["vi_pronoun"]["default"]
            lines.append(f"- {c['name']} | {c['role']} | {c['description']} | {p}")
        return "\n".join(lines)