# engine/glossary_engine.py
# Responsible for GLOSSARY DELTA extraction (NO STATE MUTATION)
from utils.json_utils import extract_json # Đảm bảo đã import hàm này
from utils.logger import log
import json
import re


GLOSSARY_DELTA_PROMPT = """
ROLE: Narrative Glossary Analyst (Translation Consistency)

EXPERTISE:
- Literary translation (English → Vietnamese)
- Narrative terminology management
- Glossary construction for long-form fiction
- Consistency control across chapters

VOICE:
- Precise
- Minimal
- Terminology-focused

MISSION:
- Analyze a NARRATIVE CHAPTER to identify NEW glossary terms
- Dịch sang tiếng Việt. Ensure long-term translation consistency
- Append NEW entries only to an existing glossary
- Avoid polluting the glossary with noise

YOU ARE GIVEN:
- The CURRENT glossary (append-only, authoritative)
- The NEW narrative chapter text

### EXTRACTION RULES:
1. **Include ONLY**:
   - Proper Nouns: Character names, specific locations, and organizations.
   - Nếu phát hiện mình đang lặp lại cùng một nội dung, hãy DỪNG LẠI ngay lập tức và đóng mảng JSON bằng dấu `]`.
   - Fictional Technology & Sci-Fi concepts
   - Symbolic or world-specific objects unique to this book's setting.
   - Ưu tiên chất lượng hơn số lượng.

2. **Strictly EXCLUDE**:
   - Common nouns (e.g., "man", "house", "table", "family", "wife", "police", "street").
   - Basic English vocabulary that any translator already knows.
   - Descriptive phrases or common actions.
   - Generic titles (e.g., "the captain", "the neighbor") unless they function as a specific character name.

GOAL:
- Identify ONLY NEW terms that REQUIRE consistent translation
- Return ONLY the delta (new entries)

BOUNDARIES (ABSOLUTE, NON-NEGOTIABLE):
- DO NOT repeat existing glossary entries
- DO NOT modify, correct, or reinterpret existing entries
- DO NOT return the full glossary
- DO NOT infer future importance
- DO NOT guess meanings beyond the chapter context
- DO NOT include explanations INSIDE the translation

TRANSLATION RULE (CRITICAL):
- The "target" field MUST contain ONLY the Vietnamese term
- NO explanations, parentheses, or descriptive phrases inside "target"

❌ INVALID:
  "target": "Anh Cả (lãnh tụ tối cao của chế độ)"

✅ VALID:
  "target": "Anh Cả"
  "note": "Biểu tượng quyền lực giám sát toàn trị"

INCLUDE ONLY:
- Proper names with non-trivial or non-obvious translation
- Organizations, institutions, slogans, systems
- Core abstract concepts likely to recur across chapters

EXCLUDE:
- Common nouns
- One-off phrases
- Stylistic or descriptive wording
- Context-specific metaphors unlikely to recur

OUTPUT FORMAT (STRICT JSON ARRAY ONLY):
[
  {
    "source": "English term",
    "target": "Vietnamese translation ONLY",
    "type": "person | organization | concept | system",
    "note": "optional clarification (OUTSIDE the translation)"
  }
]

FAILURE CONDITION:
If ANY rule above is violated, the output is INVALID.
"""


class GlossaryEngine:
    """
    Stateless glossary delta extractor.

    - Does NOT call OpenAI
    - Does NOT read/write disk
    - Does NOT mutate persistent state
    """

    def build_delta_prompt(
        self,
        *,
        current_glossary: dict,
        chapter_text: str,
    ) -> str:
        log("GLOSSARY_ENGINE: build delta prompt")

        payload = {
            "existing_terms": [
                e["source"] for e in current_glossary.get("entries", [])
            ],
            "chapter_text": chapter_text,
        }

        return (
            GLOSSARY_DELTA_PROMPT
            + "\n\nINPUT:\n"
            + json.dumps(payload, ensure_ascii=False, indent=2)
        )

    def _rescue_incomplete_json(self, text: str) -> list:
        """
        Hàm cứu hộ: Tìm các object { "source":... } hợp lệ trong chuỗi bị cắt ngang.
        """
        # Tìm các khối {...} có chứa source và target
        pattern = r'\{[^{}]*"source"[^{}]*"target"[^{}]*\}'
        matches = re.findall(pattern, text, re.DOTALL)

        rescued = []
        for m in matches:
            try:
                # Làm sạch ký tự lạ và parse thử từng object
                clean_obj = re.sub(r'[\x00-\x1F\x7F]', '', m)
                rescued.append(json.loads(clean_obj))
            except:
                continue
        return rescued

    def parse_delta(self, ai_text: str) -> list[dict]:
        log("GLOSSARY_ENGINE: parse delta")

        # 1. Làm sạch text
        clean_text = extract_json(ai_text)
        data = []

        # 2. Thử parse bình thường
        try:
            data = json.loads(clean_text)
        except Exception:
            # Nếu JSON lỗi, thực hiện cứu hộ
            log("⚠️ JSON dở dang (do lặp từ hoặc tràn window). Đang cứu dữ liệu...")
            data = self._rescue_incomplete_json(clean_text)

            if not data:
                log("❌ Không thể cứu được glossary từ AI output này.")
                return []

        # 3. Kiểm tra định dạng (Dòng này phải thẳng hàng với 'clean_text' ở trên)
        if not isinstance(data, list):
            log("⚠️ Expected JSON array nhưng nhận được định dạng khác. Trả về rỗng.")
            return []

        # 4. Lọc các entry hợp lệ và chống trùng lặp tại chỗ
        final_data = []
        seen = set()
        for e in data:
            if isinstance(e, dict) and "source" in e and "target" in e:
                source_val = e["source"].strip()
                if source_val and source_val not in seen:
                    final_data.append(e)
                    seen.add(source_val)

        log(f"GLOSSARY_ENGINE: rescued/parsed terms={len(final_data)}")
        return final_data
