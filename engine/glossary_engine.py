# engine/glossary_engine.py
# Responsible for GLOSSARY DELTA extraction (NO STATE MUTATION)
from utils.json_utils import extract_json # Đảm bảo đã import hàm này
from utils.logger import log
import json


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
- Ensure long-term translation consistency
- Append NEW entries only to an existing glossary
- Avoid polluting the glossary with noise

YOU ARE GIVEN:
- The CURRENT glossary (append-only, authoritative)
- The NEW narrative chapter text

### EXTRACTION RULES:
1. **Include ONLY**:
   - Proper Nouns: Character names, specific locations, and organizations.
   - Fictional Technology & Sci-Fi concepts (e.g., "Mechanical Hound", "Seashells").
   - Symbolic or world-specific objects unique to this book's setting.

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

    def parse_delta(self, ai_text: str) -> list[dict]:
        log("GLOSSARY_ENGINE: parse delta")

        try:
            # 1. Làm sạch text bằng cách loại bỏ dấu ```json và ```
            clean_text = extract_json(ai_text)

            # 2. Sau đó mới nạp vào json.loads
            data = json.loads(clean_text)
        except Exception:
            raise RuntimeError(
                "GLOSSARY DELTA PARSE ERROR — invalid JSON:\n" + ai_text
            )

        if not isinstance(data, list):
            raise RuntimeError(
                "GLOSSARY DELTA ERROR — expected JSON array"
            )

        for e in data:
            if "source" not in e or "target" not in e:
                raise RuntimeError(
                    f"GLOSSARY DELTA INVALID ENTRY: {e}"
                )

        log(f"GLOSSARY_ENGINE: new terms={len(data)}")
        return data
