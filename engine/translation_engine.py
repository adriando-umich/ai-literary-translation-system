# engine/translation_engine.py
# Responsibility:
# - Translate text blocks into Vietnamese
# - NO state mutation
# - Model selection explicit
# - Support rolling intra-chapter context (read-only)
# - Fail-loud, debug-first
# Python 3.9 compatible

import os
import time
import json
import re
import random  # <--- THÊM: Để tính thời gian chờ ngẫu nhiên (Jitter)
from typing import Optional, Dict, List
from utils.logger import log

# === THAY ĐỔI: Dùng thư viện Google GenAI gốc để chỉnh Safety Settings ===
from google import genai
from google.genai import types
from google.genai import errors  # <--- THÊM: Để bắt lỗi API chính xác


# =========================================================
# PRONOUN RULE BUILDER (HARD CONSTRAINT)
# =========================================================
def build_pronoun_rules(characters: list) -> str:
    """
    Build HARD CONSTRAINT rules for Vietnamese 3rd-person pronouns.
    characters: list of character objects with vi_pronoun
    """
    lines = []

    for c in characters:
        name = c.get("name")
        vi = c.get("vi_pronoun", {}).get("default")

        if name and vi:
            lines.append(f'- "{name}" MUST be referred to as "{vi}"')

    if not lines:
        return ""

    return (
            "CHARACTER PRONOUN RULES (ABSOLUTE):\n"
            "- When translating English third-person references "
            "(he / him / his), you MUST use the Vietnamese pronoun specified below.\n"
            "- You MUST NOT vary pronouns for style.\n"
            "- You MUST NOT replace pronouns with character names or descriptions.\n"
            "- You MUST NOT avoid pronouns by repeating names.\n"
            "- Any pronoun violation INVALIDATES the output.\n\n"
            "Pronoun mapping:\n"
            + "\n".join(lines)
            + "\n"
    )


# =========================================================
# ENGINE
# =========================================================
class TranslationEngine:
    def __init__(self):
        """
        Khởi tạo Engine dùng Google GenAI SDK (Official)
        Lý do: Để tắt bộ lọc nội dung (BLOCK_NONE) tránh lỗi PROHIBITED_CONTENT
        """
        # 1. Cấu hình Model (Logic Fallback)
        # Model chính ưu tiên dùng (Rẻ/Nhanh)
        self.model_primary = "gemini-2.5-flash-lite"
        # Model fallback nếu model chính lỗi (Ổn định)
        self.model_fallback = "gemini-2.0-flash"

        # Cập nhật Glossary cũng ưu tiên Lite
        self.model_glossary = "gemini-2.5-flash-lite"
        self.max_retries = 5
        self.timeout_sec = 120  # Timeout xử lý logic retry

        # 2. Lấy API Key
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError("❌ LỖI: Thiếu dòng GOOGLE_API_KEY=... trong file .env")

        # 3. Tạo Client Google (Native)
        self.client = genai.Client(api_key=api_key)

    # =========================================================
    # LOW-LEVEL API CALL (REPLACED OPENAI WITH GEMINI NATIVE)
    # =========================================================
    def _call_gemini_native(self, *, prompt: str, model: str) -> str:
        """
        Gọi trực tiếp Google Gemini với cấu hình tắt toàn bộ Safety Filter.
        Tích hợp logic xử lý lỗi 429 (Quota) với Exponential Backoff.
        """
        # Debug để bạn tự kiểm tra
        print(f"[DEBUG] Model ID gửi đi: {model}")

        # --- CẤU HÌNH QUAN TRỌNG: TẮT BỘ LỌC ---
        safety_settings = [
            types.SafetySetting(
                category="HARM_CATEGORY_HARASSMENT",
                threshold="BLOCK_NONE",
            ),
            types.SafetySetting(
                category="HARM_CATEGORY_HATE_SPEECH",
                threshold="BLOCK_NONE",
            ),
            types.SafetySetting(
                category="HARM_CATEGORY_SEXUALLY_EXPLICIT",
                threshold="BLOCK_NONE",
            ),
            types.SafetySetting(
                category="HARM_CATEGORY_DANGEROUS_CONTENT",
                threshold="BLOCK_NONE",
            ),
        ]

        # Cấu hình sinh văn bản
        generate_config = types.GenerateContentConfig(
            safety_settings=safety_settings,
            temperature=0.3,  # Giữ mức thấp để dịch chính xác
        )

        base_delay = 5  # Giây chờ cơ bản

        for attempt in range(1, self.max_retries + 1):
            try:
                log(f"CALL API attempt {attempt}/{self.max_retries} | model={model}")

                # GỌI SDK CỦA GOOGLE
                response = self.client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=generate_config
                )

                # =========================================================
                # DEBUG LOGIC: LOG CHI TIẾT KHI API TRẢ VỀ RỖNG
                # =========================================================
                if not response.text:
                    print(f"\n❌ [DEBUG ERROR] Chunk gây lỗi (Attempt {attempt}):")
                    # In snippet để debug
                    print(f"--- INPUT SNIPPET ---\n...{prompt[-300:]}\n---------------------")

                    finish_reason = "Unknown"
                    if response.candidates:
                        c = response.candidates[0]
                        finish_reason = c.finish_reason
                        if hasattr(c, 'safety_ratings'):
                            print(f"⚠️ Safety Ratings: {c.safety_ratings}")

                    # Nếu hết lượt -> Báo lỗi để kích hoạt Fallback ở tầng trên
                    if attempt == self.max_retries:
                        raise RuntimeError(f"API trả về nội dung rỗng. Reason: {finish_reason}")

                    raise ValueError("Empty response (triggering retry)")
                # =========================================================

                # LẤY TEXT
                text = response.text.strip()
                return text

            # --- XỬ LÝ LỖI 429 (QUOTA EXHAUSTED) ---
            except errors.ClientError as e:
                if e.code == 429:
                    if attempt == self.max_retries:
                        log(f"❌ API ERROR: 429 Quota exhausted for model {model}.")
                        raise e  # Ném lỗi ra để trigger fallback

                    # Exponential Backoff: Chờ lâu hơn sau mỗi lần lỗi
                    wait_time = (base_delay * (2 ** (attempt - 1))) + random.uniform(1, 3)
                    print(f"⚠️ [429 Quota] Model {model} bị giới hạn. Đang chờ {wait_time:.1f}s... (Lần {attempt})")
                    time.sleep(wait_time)
                else:
                    log(f"API CLIENT ERROR: {e}")
                    if attempt == self.max_retries:
                        raise e
                    time.sleep(2)

            # --- XỬ LÝ LỖI KHÁC (Mạng, Server 500...) ---
            except Exception as e:
                print(f"[DEBUG] Lỗi thật sự: {e}")
                log(f"API ERROR: {e}")
                if attempt == self.max_retries:
                    raise e
                time.sleep(2 * attempt)

        raise RuntimeError("Max retries exceeded")

    # =========================================================
    # COMPATIBILITY LAYER (CẦU NỐI CHO MAIN.PY)
    # =========================================================
    def _call_openai(self, *, prompt: str, model: str) -> str:
        """
        Hàm tương thích ngược: main.py gọi hàm này để tạo Glossary.
        Logic: Thử Primary (Lite) trước -> Lỗi -> Fallback (Flash 2.0).
        """
        try:
            return self._call_gemini_native(prompt=prompt, model=self.model_primary)
        except Exception as e:
            log(f"⚠️ GLOSSARY PRIMARY FAILED: {e}")
            log(f"🔄 SWITCHING GLOSSARY TO FALLBACK: {self.model_fallback}")
            return self._call_gemini_native(prompt=prompt, model=self.model_fallback)

    # =========================================================
    # PUBLIC API — TRANSLATE CHUNK
    # =========================================================
    def translate_chunk(
            self,
            *,
            en_blocks: List[str],
            glossary_rules: str = "",
            summary: str = "",
            characters: Optional[str] = None,  # JSON STRING from main.py
            intra_chapter_context: Optional[List[str]] = None,
            is_narrative: bool = False,
            chunk_index: Optional[int] = None,
            total_chunks: Optional[int] = None,
    ) -> List[str]:
        """
        Translate a list of English blocks into Vietnamese.
        LOGIC: Thử Model Primary -> Lỗi -> Fallback sang Model Secondary.
        """

        kind = "NARRATIVE" if is_narrative else "NON_NARRATIVE"
        N = len(en_blocks)

        chunk_info = (
            f"{chunk_index}/{total_chunks}"
            if chunk_index and total_chunks
            else "?"
        )

        log(
            f"AI TRANSLATE CHUNK | type={kind} | "
            f"chunk={chunk_info} | blocks={N} | "
            f"intra_ctx_blocks={len(intra_chapter_context or [])}"
        )

        numbered_blocks: List[str] = []
        for i, block in enumerate(en_blocks, start=1):
            numbered_blocks.append(f"[{i}] {block}")

        numbered_text = "\n".join(numbered_blocks)

        intra_context_text = ""
        if intra_chapter_context:
            trimmed_ctx = intra_chapter_context[-200:]
            intra_context_text = (
                    "INTRA-CHAPTER CONTEXT (REFERENCE ONLY):\n"
                    "The following text is from PREVIOUS translated blocks.\n"
                    "Use ONLY for tone, terminology, pronouns, and flow.\n"
                    "DO NOT translate, repeat, or continue it.\n\n"
                    + "\n".join(trimmed_ctx)
                    + "\n\n"
            )

        if is_narrative:
            role = "You are a professional literary translator."
            extra_rules = ""
        else:
            role = "You are a translation engine."
            extra_rules = (
                "This is NON-NARRATIVE content.\n"
                "Translate literally.\n"
                "Do NOT embellish or interpret.\n"
            )

        pronoun_rules = ""
        if is_narrative and characters:
            try:
                character_list = json.loads(characters)
                pronoun_rules = build_pronoun_rules(character_list)
            except Exception:
                raise RuntimeError("INVALID CHARACTER CONTEXT: cannot parse pronoun rules")

        prompt = f"""
{role}

TARGET LANGUAGE:
Vietnamese.

You MUST translate ALL content into Vietnamese.

{extra_rules}

{glossary_rules}

{pronoun_rules}

GLOBAL CONTEXT (if provided):
Summary:
{summary}

{intra_context_text}

STRICT RULES (MANDATORY — VIOLATION = INVALID OUTPUT):

FORMAT RULES:
- Input text contains NUMBERED blocks.
- EACH numbered block MUST produce EXACTLY ONE output line.
- EVEN IF a block is very short, it MUST still have its own output line.
- DO NOT merge, combine, summarize, or infer across blocks.
- DO NOT split blocks.
- DO NOT add or remove lines.
- Output MUST contain EXACTLY {N} lines.
- Each output line MUST start with the SAME block number as input.

NO META OUTPUT (ABSOLUTE):
- You MUST output ONLY translation lines.
- You MUST NOT add notes, explanations, confirmations, or commentary.
- You MUST NOT include text such as:
  "Note:", "Explanation:", "Here is", "I have", "I followed", or similar.

- ANY line that does NOT start with a block number [i] is INVALID.


INPUT:
{numbered_text}

OUTPUT FORMAT (EXACT):
[1] <Vietnamese translation>
[2] <Vietnamese translation>
...
""".strip()

        vi_text = ""
        try:
            vi_text = self._call_gemini_native(prompt=prompt, model=self.model_primary)
        except Exception as e:
            log(f"⚠️ PRIMARY MODEL ({self.model_primary}) FAILED: {e}")
            log(f"🔄 SWITCHING TO FALLBACK MODEL: {self.model_fallback}")
            try:
                vi_text = self._call_gemini_native(prompt=prompt, model=self.model_fallback)
            except Exception as e_fallback:
                log(f"❌ FALLBACK MODEL FAILED: {e_fallback}")
                raise e_fallback

        pattern = re.compile(r"\[(\d+)\]\s*(.*?)\s*(?=\[\d+\]|$)", re.S)
        matches = pattern.findall(vi_text)

        if not matches:
            log("=== RAW MODEL OUTPUT BEGIN ===")
            log(vi_text)
            log("=== RAW MODEL OUTPUT END ===")
            raise RuntimeError("INVALID OUTPUT: no indexed blocks found")

        vi_blocks: List[str] = []
        for idx_str, content in matches:
            vi_blocks.append(content.strip())

        if len(vi_blocks) != len(en_blocks):
            log("=== RAW MODEL OUTPUT BEGIN ===")
            log(vi_text)
            log("=== RAW MODEL OUTPUT END ===")
            raise RuntimeError(f"BLOCK COUNT MISMATCH: {len(en_blocks)} EN vs {len(vi_blocks)} VI")

        log(f"AI TRANSLATE CHUNK | success | type={kind} | blocks={len(vi_blocks)}")
        return vi_blocks