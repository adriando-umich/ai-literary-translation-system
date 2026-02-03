# engine/in_chapter_state.py
# Ephemeral per-chapter state (RAM only)
# Responsibility:
# - Hold FINAL snapshot for ONE chapter
# - No disk IO
# - No cross-chapter memory
# - Support rolling intra-chapter translation context

from utils.logger import log
from typing import List, Dict, Optional


class InChapterState:
    def __init__(self, *, max_context_chunks: int = 2):
        # -------------------------
        # CHAPTER RESULTS (FINAL SNAPSHOT)
        # -------------------------
        self.glossary_delta: List[Dict] = []      # append-only
        self.summary_snapshot: Optional[Dict] = None
        self.character_snapshot: Optional[List[Dict]] = None

        # -------------------------
        # ROLLING TRANSLATION CONTEXT
        # -------------------------
        # Each entry = ONE translated chunk (list[str])
        self._translated_chunks: List[List[str]] = []
        self.max_context_chunks = max_context_chunks

        log("IN-CHAPTER STATE: init")

    # =====================================================
    # GLOSSARY (DELTA)
    # =====================================================
    def add_glossary_terms(self, terms: List[Dict]):
        if not terms:
            return
        self.glossary_delta.extend(terms)
        log(f"IN-CHAPTER STATE: glossary +{len(terms)}")

    # =====================================================
    # SUMMARY (SNAPSHOT)
    # =====================================================
    def set_summary(self, summary: Dict):
        if not summary:
            return
        self.summary_snapshot = summary
        log("IN-CHAPTER STATE: summary snapshot set")

    # =====================================================
    # CHARACTERS (SNAPSHOT)
    # =====================================================
    def set_characters(self, characters: List[Dict]):
        if not characters:
            return
        self.character_snapshot = characters
        log(f"IN-CHAPTER STATE: characters snapshot set | count={len(characters)}")

    # =====================================================
    # TRANSLATION CONTEXT (ROLLING)
    # =====================================================
    def add_translated_chunk(self, vi_chunk: List[str]):
        for b in vi_chunk:
            if "ORIGINAL:" in b or "DRAFT:" in b:
                raise RuntimeError(
                    "FORMAT CONTAMINATION DETECTED BEFORE STATE STORE"
                )
        """
        Store ONE translated chunk for rolling intra-chapter context.
        vi_chunk: list[str] (Vietnamese blocks)
        """
        if not vi_chunk:
            return

        self._translated_chunks.append(vi_chunk)

        # enforce rolling window
        if len(self._translated_chunks) > self.max_context_chunks:
            self._translated_chunks = self._translated_chunks[-self.max_context_chunks :]

        log(
            f"IN-CHAPTER STATE: stored translated chunk | "
            f"ctx_chunks={len(self._translated_chunks)}"
        )

    # =====================================================
    # CONTEXT ACCESSORS
    # =====================================================
    def get_last_chunks(self, max_blocks: int) -> List[str]:
        """
        Return up to `max_blocks` most recent translated blocks.
        Flattened list[str], chronological order preserved.
        """
        if max_blocks <= 0 or not self._translated_chunks:
            return []

        flat: List[str] = []

        # newest chunks first
        for chunk in reversed(self._translated_chunks):
            for block in reversed(chunk):
                flat.append(block)
                if len(flat) >= max_blocks:
                    return list(reversed(flat))

        return list(reversed(flat))

    def context_size(self) -> int:
        return len(self._translated_chunks)
