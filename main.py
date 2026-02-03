# main.py
# Entry point for the translation pipeline
# Architecture: Chapter-atomic, deterministic, debug-first
# BRD v1.5 compliant (Translator + State + Editor)

from engine.chapter_classifier import ChapterType
from engine.translation_engine import TranslationEngine
from engine.glossary_engine import GlossaryEngine
from engine.summary_engine import SummaryEngine
from engine.character_engine import CharacterEngine
from engine.in_chapter_state import InChapterState
from engine.html_block_extractor import extract_html_blocks
from engine.html_rebuilder import rebuild_html_blocks
from engine import state_manager
from engine.checkpoint_manager import load_checkpoint, mark_done
from engine.editor_engine import EditorEngine

from epub.epub_loader import load_epub
from epub.epub_writer import write_epub

from utils.logger import log
from utils.inspect import print_chapter_list

import ebooklib
from bs4 import BeautifulSoup
from typing import List
import json

INPUT_EPUB = "input.epub"
OUTPUT_EPUB = "output_bilingual.epub"

MAX_BLOCKS_PER_CHUNK = 8
INTRA_CONTEXT_CHUNKS = 2


def split_into_chunks(blocks: List[str], max_blocks: int) -> List[List[str]]:
    return [blocks[i:i + max_blocks] for i in range(0, len(blocks), max_blocks)]


def build_glossary_rules(*, base_glossary: dict, delta_terms: list) -> str:
    entries = []
    for e in base_glossary.get("entries", []):
        entries.append(f'- "{e["source"]}" → "{e["target"]}"')
    for e in delta_terms:
        entries.append(f'- "{e["source"]}" → "{e["target"]}"')

    if not entries:
        return ""

    return (
        "GLOSSARY RULES (HARD CONSTRAINT):\n"
        "- Every source term MUST be translated EXACTLY as specified.\n"
        "- Do NOT paraphrase or localize glossary terms.\n\n"
        "Glossary:\n" + "\n".join(entries)
    )


async def run():
    log("START TRANSLATION PIPELINE")

    book = load_epub(INPUT_EPUB)

    total_chapters = print_chapter_list(book)
    first_narrative_index = int(input("👉 Enter FIRST_NARRATIVE_INDEX: "))
    last_chapter_index = int(input("👉 Enter LAST_CHAPTER_INDEX: "))

    engine = TranslationEngine()
    editor_engine = EditorEngine()
    glossary_engine = GlossaryEngine()
    summary_engine = SummaryEngine(engine.client)
    character_engine = CharacterEngine(engine.client)

    glossary = state_manager.load_glossary()
    summary = state_manager.load_summary()
    characters = state_manager.load_characters()

    done_chapters = load_checkpoint()

    for idx, item in enumerate(book.get_items_of_type(ebooklib.ITEM_DOCUMENT)):

        if idx > last_chapter_index:
            break
        if idx in done_chapters:
            continue

        soup = BeautifulSoup(
            item.get_content().decode("utf-8", errors="ignore"),
            "html.parser"
        )

        if idx < first_narrative_index:
            chapter_type = ChapterType.NON_NARRATIVE
        elif idx == first_narrative_index:
            chapter_type = ChapterType.FIRST_NARRATIVE
        else:
            chapter_type = ChapterType.NARRATIVE

        is_narrative = chapter_type != ChapterType.NON_NARRATIVE
        log(f"CHAPTER {idx} TYPE = {chapter_type}")

        en_blocks, html_nodes = extract_html_blocks(soup)
        if not en_blocks:
            mark_done(idx)
            continue

        chapter_text = "\n".join(en_blocks)
        in_state = InChapterState()

        # ---------- GLOSSARY DELTA ----------
        if is_narrative:
            ai_text = engine._call_openai(
                prompt=glossary_engine.build_delta_prompt(
                    current_glossary=glossary,
                    chapter_text=chapter_text,
                ),
                model=engine.model_glossary,
            )
            in_state.add_glossary_terms(
                glossary_engine.parse_delta(ai_text)
            )

        glossary_rules = (
            build_glossary_rules(
                base_glossary=glossary,
                delta_terms=in_state.glossary_delta,
            ) if is_narrative else ""
        )

        # ---------- TRANSLATION ----------
        vi_blocks: List[str] = []
        chunks = split_into_chunks(en_blocks, MAX_BLOCKS_PER_CHUNK)
        total_chunks = len(chunks)  # 👈 BẮT BUỘC

        # Tạo nhanh chuỗi quy tắc đại từ từ list characters đang có
        char_rules = "\n".join([f"- {c['name']}: {c['vi_pronoun']['default']}" for c in characters])

        for i, chunk in enumerate(chunks, start=1):  # 👈 BẮT BUỘC
            vi_chunk = engine.translate_chunk(
                en_blocks=chunk,
                glossary_rules=glossary_rules,
                # Nhét char_rules vào đầu summary để AI dịch ưu tiên đọc trước
                summary=f"CHARACTER PRONOUNS:\n{char_rules}\n\nSTORY SUMMARY:\n{json.dumps(summary, ensure_ascii=False)}",
                characters=json.dumps(characters, ensure_ascii=False) if characters else "",
                intra_chapter_context=in_state.get_last_chunks(
                    INTRA_CONTEXT_CHUNKS * MAX_BLOCKS_PER_CHUNK
                ),
                is_narrative=is_narrative,
                chunk_index=i,  # ✅ 1-based
                total_chunks=total_chunks,  # ✅
            )
            vi_blocks.extend(vi_chunk)
            in_state.add_translated_chunk(vi_chunk)

        if len(vi_blocks) != len(en_blocks):
            raise RuntimeError("BLOCK COUNT MISMATCH")

        # ---------- SUMMARY + CHARACTER UPDATE ----------
        if is_narrative:
            if chapter_type == ChapterType.FIRST_NARRATIVE:
                in_state.summary_snapshot = summary_engine.init_summary(chapter_text)
                in_state.character_snapshot = character_engine.init_characters(chapter_text)
            else:
                in_state.summary_snapshot = summary_engine.update_summary(summary, chapter_text)
                in_state.character_snapshot = character_engine.update_characters(characters, chapter_text)

        # ---------- EDITOR (CHAPTER LEVEL) ----------
        if is_narrative:
            log(f"EDITOR START chapter {idx}")

            # Merge từ mới của chương này vào bản copy của glossary tổng
            full_glossary_for_editor = glossary.copy()
            for term in in_state.glossary_delta:
                # Giả sử cấu trúc delta là [{'source': 'A', 'target': 'B'}, ...]
                full_glossary_for_editor[term['source']] = term['target']

            vi_blocks = await editor_engine.edit_chapter(
                original_blocks=en_blocks,
                draft_vi_blocks=vi_blocks,
                glossary=full_glossary_for_editor  # Nên truyền glossary mới của chương này hoặc glossary tổng
            )
            log(f"EDITOR DONE chapter {idx}")

        # ---------- HTML REBUILD ----------
        rebuild_html_blocks(html_nodes, vi_blocks)
        item.set_content(str(soup).encode("utf-8"))

        # ---------- COMMIT ----------
        if is_narrative:
            state_manager.commit_chapter(in_state)

            # Cập nhật lại biến local cho vòng lặp sau
            glossary = state_manager.load_glossary()
            summary = state_manager.load_summary()
            characters = state_manager.load_characters()

        mark_done(idx)

    write_epub(OUTPUT_EPUB, book)  # ĐƯỜNG DẪN TRƯỚC, BOOK SAU  # Đưa đường dẫn file lên trước, đối tượng book ra sau
    log("PIPELINE DONE")


if __name__ == "__main__":
    import asyncio
    asyncio.run(run())
