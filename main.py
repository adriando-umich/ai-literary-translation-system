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
import asyncio  # Import asyncio rõ ràng

INPUT_EPUB = "input.epub"
OUTPUT_EPUB = "output_bilingual.epub"

# Lưu ý: MAX_BLOCKS_PER_CHUNK cũ không còn dùng để chia chunk,
# nhưng giữ lại hằng số INTRA_CONTEXT_BLOCKS để lấy ngữ cảnh.
INTRA_CONTEXT_BLOCKS = 200


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
            # 1. Gọi API
            ai_text = engine._call_openai(
                prompt=glossary_engine.build_delta_prompt(
                    current_glossary=glossary,
                    chapter_text=chapter_text,
                ),
                model=engine.model_glossary,
            )

            # 2. Parse kết quả
            raw_terms = glossary_engine.parse_delta(ai_text)

            # 3. KHỬ TRÙNG HỆ THỐNG
            existing_sources = {e["source"].lower() for e in glossary.get("entries", [])}
            unique_terms = []
            for term in raw_terms:
                if term["source"].lower() not in existing_sources:
                    unique_terms.append(term)

            if len(raw_terms) > len(unique_terms):
                log(f"⚠️ GLOSSARY: Đã lọc bỏ {len(raw_terms) - len(unique_terms)} từ trùng lặp.")

            # 4. Nạp vào state
            in_state.add_glossary_terms(unique_terms)

        glossary_rules = (
            build_glossary_rules(
                base_glossary=glossary,
                delta_terms=in_state.glossary_delta,
            ) if is_narrative else ""
        )

        # ---------- TRANSLATION (DYNAMIC CHUNKING UPDATE) ----------
        vi_blocks: List[str] = []

        # 1. Chuẩn bị Context String để tính token nền (Static Context)
        # Tạo chuỗi rules đại từ
        char_rules_str = "\n".join([f"- {c['name']}: {c['vi_pronoun']['default']}" for c in characters])
        summary_json_str = json.dumps(summary, ensure_ascii=False)
        chars_json_str = json.dumps(characters, ensure_ascii=False) if characters else ""

        # Ước lượng tổng độ dài của phần Prompt cố định (System prompt + Glossary + Summary...)
        # Engine sẽ dùng con số này để biết "còn bao nhiêu chỗ trống" cho text cần dịch.
        static_context_str = (
                glossary_rules +
                f"\n{char_rules_str}\n" +
                summary_json_str +
                chars_json_str +
                "You are a professional literary translator..."  # System Prompt Buffer
        )
        static_len = len(static_context_str)

        # 2. Vòng lặp cắt chunk động (Dynamic Loop)
        current_idx = 0
        chunk_counter = 1
        total_blocks_count = len(en_blocks)

        while current_idx < total_blocks_count:
            remaining_blocks = en_blocks[current_idx:]

            # -> GỌI ENGINE: Tính toán xem nên lấy bao nhiêu block dựa trên token limit
            num_blocks_to_take = engine.calculate_optimal_chunk_size(
                remaining_blocks=remaining_blocks,
                static_context_len=static_len
            )

            current_chunk = remaining_blocks[:num_blocks_to_take]

            # GỌI ENGINE: Dịch chunk
            vi_chunk = engine.translate_chunk(
                en_blocks=current_chunk,
                glossary_rules=glossary_rules,
                # Ghép char_rules vào summary để AI chú ý hơn
                summary=f"CHARACTER PRONOUNS:\n{char_rules_str}\n\nSTORY SUMMARY:\n{summary_json_str}",
                characters=chars_json_str,
                intra_chapter_context=in_state.get_last_chunks(INTRA_CONTEXT_BLOCKS),
                is_narrative=is_narrative,
                chunk_index=chunk_counter,
                total_chunks=999,  # Dynamic chunking nên không biết chính xác tổng số chunk, để 999
            )

            vi_blocks.extend(vi_chunk)
            in_state.add_translated_chunk(vi_chunk)

            # Cập nhật index
            current_idx += num_blocks_to_take
            chunk_counter += 1

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

            full_glossary_for_editor = glossary.copy()
            if in_state.glossary_delta:
                for term in in_state.glossary_delta:
                    src = term.get('source')
                    tgt = term.get('target')
                    if src and tgt:
                        full_glossary_for_editor[src] = tgt

            vi_blocks = await editor_engine.edit_chapter(
                original_blocks=en_blocks,
                draft_vi_blocks=vi_blocks,
                glossary=full_glossary_for_editor
            )
            log(f"EDITOR DONE chapter {idx}")

        # ---------- HTML REBUILD ----------
        rebuild_html_blocks(html_nodes, vi_blocks)
        item.set_content(str(soup).encode("utf-8"))

        # ---------- COMMIT ----------
        if is_narrative:
            state_manager.commit_chapter(in_state)
            glossary = state_manager.load_glossary()
            summary = state_manager.load_summary()
            characters = state_manager.load_characters()

        mark_done(idx)

    write_epub(OUTPUT_EPUB, book)
    log("PIPELINE DONE")


if __name__ == "__main__":
    asyncio.run(run())