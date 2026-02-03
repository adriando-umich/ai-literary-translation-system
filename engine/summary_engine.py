# engine/summary_engine.py
# Responsible for STORY SUMMARY memory (init + update)
# Chapter-level, deterministic, TEXT → PARSE → JSON
# Python 3.9 compatible

from utils.logger import log
from typing import Dict, List


# =========================================================
# PROMPTS (TEXT-ONLY, NO JSON)
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
    def __init__(self, client):
        self.client = client

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
    # LLM CALL (TEXT ONLY)
    # =====================================================
    def _call_llm(self, *, system_prompt: str, user_prompt: str) -> str:
        resp = self.client.chat.completions.create(
            model="gemini-2.5-flash",  # <--- SỬA THÀNH ĐÚNG MODEL BẠN ĐANG DÙNG
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
        )

        text = resp.choices[0].message.content.strip()
        if not text:
            raise RuntimeError("SUMMARY_ENGINE: empty AI response")

        return text

    # =====================================================
    # PARSER (DETERMINISTIC, FAIL-LOUD)
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
    # SERIALIZER (JSON → TEXT)
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
