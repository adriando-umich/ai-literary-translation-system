# engine/chapter_classifier.py
from enum import Enum

class ChapterType(str, Enum):
    NON_NARRATIVE = "NON_NARRATIVE"
    FIRST_NARRATIVE = "FIRST_NARRATIVE"
    NARRATIVE = "NARRATIVE"


def classify_chapter(chapter_text: str, has_seen_narrative: bool) -> ChapterType:
    """
    Rules:
    - Empty or whitespace-only chapter → NON_NARRATIVE
    - First chapter with content → FIRST_NARRATIVE
    - Any later content chapter → NARRATIVE
    """
    if not chapter_text.strip():
        return ChapterType.NON_NARRATIVE

    if not has_seen_narrative:
        return ChapterType.FIRST_NARRATIVE

    return ChapterType.NARRATIVE
