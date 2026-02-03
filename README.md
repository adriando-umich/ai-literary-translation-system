AI LITERARY TRANSLATION SYSTEM (EN ↔ VI)
======================================

WHAT IS THIS?
-------------
- An AI application that translates English novels into Vietnamese
- Designed for full-length books, not short text or chat
- Outputs clean, readable, bilingual EPUB files
- Target quality: reads like a professionally edited book


WHY THIS PROBLEM IS HARD
-----------------------
Naive AI translation fails because:
- Characters drift across chapters
- Key terms change over time
- Retries change previous output
- Long books exceed model context limits
- Output is correct but unpleasant to read

This system solves these issues structurally.


CORE IDEA (PLAIN LANGUAGE)
-------------------------
- Work chapter-by-chapter, not sentence-by-sentence
- Each chapter is processed atomically:
  * fully succeeds
  * or fully fails
- Nothing is partially saved

Per chapter:
1. Translate faithfully
2. Apply story memory for consistency
3. Edit Vietnamese for natural flow
4. Lock results before moving on


EXAMPLE OUTPUT (EN ↔ VI)
-----------------------
EN:
  Winston stared at the telescreen.
  The voice continued to drone on.

VI:
  Winston nhìn chằm chằm vào màn hình vô tuyến.
  Giọng nói vẫn đều đều vang lên không dứt.

Target:
- faithful meaning
- smooth rhythm
- consistent character reference


HIGH-LEVEL FLOW
---------------
EPUB Book
  -> Chapter detection
  -> Chapter translation
  -> Chapter editing
  -> Bilingual EPUB output


TWO AI PASSES (IMPORTANT)
------------------------

1) TRANSLATION PASS
- English -> Vietnamese
- Focus: correctness and consistency
- Uses:
  * glossary (fixed terms)
  * character references
  * rolling story summary
- Output:
  * correct but unpolished draft

2) EDITOR PASS
- Vietnamese-only
- Runs after full chapter translation
- Improves:
  * flow
  * rhythm
  * readability
- Must NOT:
  * change meaning
  * change structure
  * change block count


STORY MEMORY (EXTERNAL TO AI)
----------------------------

Glossary:
- Fixed translations for key terms
- Append-only, never modified

Character context:
- Controls Vietnamese third-person references
- Prevents pronoun drift

Story summary:
- Rolling English summary of the story
- Maintains long-range coherence


RELIABILITY BY DESIGN
--------------------
Hard rules enforced by the system:
- One English block -> one Vietnamese block
- Chapter commit is all-or-nothing
- Partial failures are rolled back
- Safe retries without corrupting state
- Same input + same state = same output


OUTPUT
------
- Original English text preserved
- Vietnamese text inserted adjacent
- Clean bilingual EPUB
- Deterministic, reproducible results
