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

import uuid
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

def sanitize_book_structure(book):
    """
    Hàm này rà soát toàn bộ sách và gán ID giả cho bất kỳ thành phần nào bị thiếu ID.
    Giúp tránh lỗi 'NoneType' khi ghi file.
    """
    log("🧹 BẮT ĐẦU RÀ SOÁT CẤU TRÚC SÁCH (SANITIZING)...")
    count_fixed = 0

    # 1. Rà soát danh sách file (Items)
    for item in book.get_items():
        if not item.id:  # Nếu ID bị None hoặc rỗng
            new_id = f"fixed_item_{uuid.uuid4().hex[:8]}"
            item.set_id(new_id)
            log(f"   🔧 Đã sửa Item thiếu ID: {item.file_name} -> {new_id}")
            count_fixed += 1

    # 2. Rà soát Mục lục (TOC) - Đệ quy
    def fix_toc_node(node):
        nonlocal count_fixed
        # Nếu node là một list/tuple (Section con), duyệt đệ quy
        if isinstance(node, (list, tuple)):
            for child in node:
                fix_toc_node(child)
        # Nếu node là một Link object (thường gặp trong ebooklib)
        elif hasattr(node, 'uid'):
            if not node.uid:
                new_uid = f"fixed_toc_{uuid.uuid4().hex[:8]}"
                node.uid = new_uid
                title = getattr(node, 'title', 'No Title')
                log(f"   🔧 Đã sửa TOC Node thiếu UID: '{title}' -> {new_uid}")
                count_fixed += 1

    fix_toc_node(book.toc)

    if count_fixed > 0:
        log(f"✅ ĐÃ SỬA XONG {count_fixed} LỖI CẤU TRÚC.")
    else:
        log("✅ CẤU TRÚC SÁCH ỔN ĐỊNH. KHÔNG CÓ LỖI ID.")

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
            # SỬA TẠI ĐÂY: Thay vì chỉ continue, hãy nạp lại bản dịch cũ
            log(f"CHECKPOINT: skip translation for chapter {idx}, loading previous version")

            # Giả sử state_manager của bạn lưu file HTML tại 'state/chapters/chapter_{idx}.html'
            # (Bạn cần kiểm tra đường dẫn chính xác trong state_manager.py của bạn)
            cached_html = state_manager.get_chapter_html(idx)

            if cached_html:
                item.set_content(cached_html.encode("utf-8"))
            else:
                log(f"⚠️ Warning: Chapter {idx} marked done but no cache found. Keeping original.")
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
            # --- PHẦN SỬA ĐỔI: RETRY & FALLBACK CHO GLOSSARY ---
            ai_text = ""
            glossary_max_retries = 3
            last_glossary_error = None

            for g_attempt in range(1, glossary_max_retries + 1):
                # Lần cuối cùng (lần 3) sẽ dùng fallback model
                current_glossary_model = engine.model_glossary
                if g_attempt == glossary_max_retries:
                    current_glossary_model = "gemini-3-flash-preview"
                    log(f"⚠️ GLOSSARY: Switching to FALLBACK MODEL: {current_glossary_model}")

                try:
                    log(f"GLOSSARY: API call attempt {g_attempt} using [{current_glossary_model}]")
                    ai_text = engine._call_openai(
                        prompt=glossary_engine.build_delta_prompt(
                            current_glossary=glossary,
                            chapter_text=chapter_text,
                        ),
                        model=current_glossary_model,  # Sử dụng model đã chọn
                    )
                    if ai_text: break  # Thành công thì thoát vòng lặp
                except Exception as e:
                    last_glossary_error = e
                    log(f"⚠️ GLOSSARY API ERROR (Attempt {g_attempt}): {e}")
                    if g_attempt < glossary_max_retries:
                        await asyncio.sleep(2 * g_attempt)

            if not ai_text:
                log(f"❌ GLOSSARY FAILED sau {glossary_max_retries} lần thử. Bỏ qua delta chương này.")
                # Nếu glossary lỗi hoàn toàn, ta để ai_text là mảng rỗng để không làm sập pipeline
                ai_text = "[]"

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
                summary=f"CHARACTER PRONOUNS:\n{char_rules_str}\n\nSTORY SUMMARY:\n{summary_json_str}",
                characters=chars_json_str,
                intra_chapter_context=in_state.get_last_chunks(INTRA_CONTEXT_BLOCKS),
                is_narrative=is_narrative,
                chunk_index=chunk_counter,
                total_chunks=0,  # <--- Sửa thành 0 để hiển thị log là '1/?', '2/?'...
                total_chapter_blocks=total_blocks_count,
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

            # Flat dict source -> target only (Editor expects this format)
            full_glossary_for_editor = {}
            for e in glossary.get("entries", []):
                full_glossary_for_editor[e["source"]] = e["target"]
            for term in in_state.glossary_delta:
                src = term.get("source")
                tgt = term.get("target")
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
        state_manager.commit_chapter(idx, in_state, str(soup))
        if is_narrative:

            glossary = state_manager.load_glossary()
            summary = state_manager.load_summary()
            characters = state_manager.load_characters()

        mark_done(idx)

    # === DEBUG: Kiểm tra book & TOC một lần sau khi xử lý xong tất cả chương ===
    print("\n[DEBUG] --- KIỂM TRA BOOK & TOC TRƯỚC KHI GHI ---")
    for item in book.get_items():
        if item.get_id() is None:
            print(f"❌ ITEM LỖI (No ID): Type={type(item)} Name={item.get_name()}")
            new_id = f"fixed_{uuid.uuid4().hex[:8]}"
            item.set_id(new_id)
            print(f"   -> Đã auto-fix gán ID mới: {new_id}")

    def check_toc(toc_list):
        for node in toc_list:
            if isinstance(node, (list, tuple)):
                check_toc(node)
            elif hasattr(node, 'uid'):
                if node.uid is None:
                    print(f"❌ TOC NODE LỖI (No UID): Title={getattr(node, 'title', 'N/A')}")
                    if hasattr(node, 'set_id'):
                        node.set_id(f"toc_fixed_{uuid.uuid4().hex[:8]}")
                        print(f"   -> Đã auto-fix gán UID cho TOC node.")
            else:
                print(f"⚠️ Cảnh báo: Node trong TOC không phải Link/Item chuẩn: {type(node)}")

    check_toc(book.toc)
    print("[DEBUG] --- KẾT THÚC KIỂM TRA ---\n")

    sanitize_book_structure(book)
    log(f"WRITING TO: {OUTPUT_EPUB}")
    write_epub(OUTPUT_EPUB, book)
    log("PIPELINE DONE")


if __name__ == "__main__":
    asyncio.run(run())