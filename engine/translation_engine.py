# engine/translation_engine.py
# Responsibility:
# - Translate text blocks into Vietnamese
# - NO state mutation
# - Model selection explicit
# - Support rolling intra-chapter context (read-only)
# - Fail-loud, debug-first
# Python 3.9 compatible
import os
from typing import Optional, Dict, List
from utils.logger import log
from openai import OpenAI
import time
import json


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
    # Sửa trong file: engine/translation_engine.py
    def __init__(self):
        """
        Khởi tạo Engine Dịch Thô dùng Google Gemini 1.5 Flash
        """
        # 1. Cấu hình Model (Sửa tên biến thành model_translate cho khớp code cũ)
        self.model_translate = "gemini-2.5-flash-lite"  # <--- ĐÃ SỬA TÊN BIẾN NÀY
        self.model_glossary = "gemini-2.5-flash-lite"
        self.max_retries = 5
        self.timeout_sec = 120
        # 2. Lấy API Key Google từ file .env
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError("❌ LỖI: Thiếu dòng GOOGLE_API_KEY=... trong file .env")

        # 3. Tạo Client trỏ về Google (OpenAI-compatible mode)
        self.client = OpenAI(
            api_key=api_key,
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/"
        )

    # =========================================================
    # LOW-LEVEL OPENAI CALL
    # =========================================================
    def _call_openai(self, *, prompt: str, model: str) -> str:
        # Debug để bạn tự kiểm tra
        print(f"[DEBUG] Model ID gửi đi: {model}")

        for attempt in range(1, self.max_retries + 1):
            try:
                log(f"CALL API attempt {attempt} | model={model}")

                # SỬA LẠI ĐOẠN NÀY CHO ĐÚNG CHUẨN OPENAI SDK
                resp = self.client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],  # Cấu trúc bắt buộc
                    timeout=self.timeout_sec,
                )

                # THÊM ĐOẠN DEBUG NÀY:
                if resp.choices[0].message is None:
                    print(f"--- DEBUG ERROR ---")
                    print(f"Finish Reason: {resp.choices[0].finish_reason}")
                    print(f"Full Response: {resp}")
                    raise AttributeError("API trả về message là None. Có thể do bị filter nội dung.")

                # LẤY TEXT TRẢ VỀ THEO CHUẨN OPENAI SDK
                text = resp.choices[0].message.content.strip()

                if not text:
                    raise RuntimeError("EMPTY RESPONSE")

                return text

            except Exception as e:
                # In ra lỗi thật để debug
                print(f"[DEBUG] Lỗi thật sự: {e}")
                log(f"API ERROR: {e}")
                if attempt == self.max_retries:
                    raise
                time.sleep(2 * attempt)

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
        chunk_index: Optional[int] = None,  # 👈 NEW
        total_chunks: Optional[int] = None,  # 👈 NEW
    ) -> List[str]:
        """
        Translate a list of English blocks into Vietnamese.

        HARD CONTRACT:
        - Order preserved
        - len(output) == len(input)
        - Each output line MUST start with [i]
        """

        kind = "NARRATIVE" if is_narrative else "NON_NARRATIVE"
        model = self.model_translate
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

        # -----------------------------------------------------
        # NUMBER SOURCE BLOCKS (SOURCE OF TRUTH)
        # -----------------------------------------------------
        numbered_blocks: List[str] = []
        for i, block in enumerate(en_blocks, start=1):
            numbered_blocks.append(f"[{i}] {block}")

        numbered_text = "\n".join(numbered_blocks)

        # -----------------------------------------------------
        # INTRA-CHAPTER CONTEXT (READ-ONLY)
        # -----------------------------------------------------
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

        # -----------------------------------------------------
        # ROLE & MODE
        # -----------------------------------------------------
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

        # -----------------------------------------------------
        # PRONOUN RULES (NARRATIVE ONLY)
        # -----------------------------------------------------
        pronoun_rules = ""
        if is_narrative and characters:
            try:
                character_list = json.loads(characters)
                pronoun_rules = build_pronoun_rules(character_list)
            except Exception:
                raise RuntimeError(
                    "INVALID CHARACTER CONTEXT: cannot parse pronoun rules"
                )

        # -----------------------------------------------------
        # PROMPT
        # -----------------------------------------------------
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

        # -----------------------------------------------------
        # CALL OPENAI
        # -----------------------------------------------------
        vi_text = self._call_openai(prompt=prompt, model=model)

        # -----------------------------------------------------
        # PARSE + HARD VALIDATION (INDEX-BASED, FAIL-LOUD)
        # -----------------------------------------------------
        import re

        # Match: [i] content ... until next [j] or end of text
        pattern = re.compile(
            r"\[(\d+)\]\s*(.*?)\s*(?=\[\d+\]|$)",
            re.S
        )

        matches = pattern.findall(vi_text)

        if not matches:
            log("=== RAW MODEL OUTPUT BEGIN ===")
            log(vi_text)
            log("=== RAW MODEL OUTPUT END ===")
            raise RuntimeError(
                "INVALID OUTPUT: no indexed blocks found"
            )

        vi_blocks: List[str] = []

        for idx_str, content in matches:
            vi_blocks.append(content.strip())

        if len(vi_blocks) != len(en_blocks):
            log("=== RAW MODEL OUTPUT BEGIN ===")
            log(vi_text)
            log("=== RAW MODEL OUTPUT END ===")
            raise RuntimeError(
                f"BLOCK COUNT MISMATCH: "
                f"{len(en_blocks)} EN vs {len(vi_blocks)} VI"
            )


        log(
            f"AI TRANSLATE CHUNK | success | type={kind} | blocks={len(vi_blocks)}"
        )
        return vi_blocks
