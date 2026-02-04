# ============================================================
# EDITOR ENGINE — CHAPTER-LEVEL ONLY (STABLE)
#
# INVARIANTS:
# 1. Editor runs ONLY after a full chapter is translated.
# 2. Input = Vietnamese blocks only (List[str]).
# 3. Editor MUST NOT:
#    - change block count
#    - change block order
#    - change character pronouns
#    - add or remove content
# 4. Editor MAY read English blocks as reference ONLY to resolve ambiguity,
#    but MUST NOT translate from or rewrite based on English.
# 5. Editor does NOT update any narrative state.
#
# If any invariant is violated → FAIL CHAPTER.
# ============================================================
import os
from typing import List, Optional
from openai import AsyncOpenAI
from utils.logger import log
import asyncio



# ============================================================
# EDITOR ENGINE — CHAPTER-LEVEL ONLY (STABLE)
# ============================================================

class EditorEngine:
    def __init__(self, model: str = "gemini-3-flash-preview"):
        """
        Editor is async by design.
        Uses CHAT COMPLETIONS API (Google OpenAI-Compatible).
        """
        self.model = model

        # 1. Lấy Key Google
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError("❌ Missing GOOGLE_API_KEY environment variable for EditorEngine")

        # 2. Cấu hình Client trỏ về Google
        self.client = AsyncOpenAI(
            api_key=api_key,
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/"
        )

    # =========================================================
    # PUBLIC API
    # =========================================================
        async def edit_chapter(self, original_blocks: list[str], draft_vi_blocks: list[str], glossary: dict) -> list[
            str]:
            """
            Nhuận sắc chương với cơ chế SMART RETRY (Tự động nối tiếp khi bị ngắt).
            """
            import asyncio  # Import local để đảm bảo không lỗi nếu file gốc thiếu

            log(f"EDITOR: start chapter edit | blocks={len(original_blocks)}")

            # Danh sách chứa kết quả cuối cùng
            collected_blocks = []

            # Biến đếm vị trí hiện tại
            current_idx = 0
            total_blocks = len(original_blocks)

            # Giới hạn số lần thử vòng ngoài (tránh lặp vô tận do lỗi parse)
            max_outer_retries = 10
            outer_attempt_count = 0

            while current_idx < total_blocks and outer_attempt_count < max_outer_retries:
                outer_attempt_count += 1

                # 1. Cắt phần dữ liệu CÒN THIẾU để gửi đi
                batch_original = original_blocks[current_idx:]
                batch_draft = draft_vi_blocks[current_idx:]

                # Chuẩn bị Glossary text
                glossary_text = "\n".join([f"{k}: {v}" for k, v in glossary.items()])

                # Tạo Prompt cho Batch hiện tại
                start_block_num = current_idx + 1

                system_prompt = (
                    "You are a professional book editor. Your goal is to polish the Vietnamese translation (DRAFT) "
                    "to make it sound natural, literary, and fluent, while ensuring it matches the ORIGINAL meaning.\n\n"
                    "IMPORTANT RULES:\n"
                    "1. Content inside each block MUST ONLY be the refined Vietnamese text.\n"
                    "2. DO NOT include 'ORIGINAL:', 'DRAFT:', or any other labels inside the blocks.\n"
                    "3. DO NOT output explanations or notes.\n"
                    "4. Output format MUST strictly follow:\n"
                    f"   <<<BLOCK:N>>>\n"
                    "   [Your refined Vietnamese text here]\n"
                    "   <<<END>>>\n"
                    "5. Keep the exact block numbers provided."
                )

                # Ghép nội dung batch
                content_pairs = ""
                for i, (orig, draft) in enumerate(zip(batch_original, batch_draft)):
                    real_block_num = start_block_num + i
                    content_pairs += (
                        f"--- BLOCK {real_block_num} ---\n"
                        f"ORIGINAL: {orig}\n"
                        f"DRAFT: {draft}\n\n"
                    )

                user_prompt = (
                    f"GLOSSARY:\n{glossary_text}\n\n"
                    f"INPUT DATA (Starting from Block {start_block_num}):\n"
                    "You are given pairs of ORIGINAL English and DRAFT Vietnamese.\n"
                    "CRITICAL GUIDELINE:\n"
                    "- Use the ORIGINAL English ONLY AS A REFERENCE to ensure the DRAFT hasn't missed or misinterpreted any meaning.\n"
                    "- Your primary task is to POLISH and REWRITE the DRAFT Vietnamese into professional, literary prose.\n"
                    "- DO NOT translate directly from English if the DRAFT is already accurate; focus on style, flow, and Vietnamese word choice.\n\n"
                    f"{content_pairs}\n\n"
                    "Output ONLY the refined Vietnamese blocks now:"
                )

                # =========================================================
                # RETRY LOGIC (MỚI THÊM): Xử lý lỗi 503/429/Timeout
                # =========================================================
                response_text = None
                max_api_retries = 5  # Thử lại tối đa 5 lần cho mỗi batch

                for api_attempt in range(1, max_api_retries + 1):
                    try:
                        log(f"EDITOR: processing batch starting at {start_block_num} (Attempt {api_attempt}/{max_api_retries})...")

                        response = await self.client.chat.completions.create(
                            model=self.model,
                            messages=[
                                {"role": "system", "content": system_prompt},
                                {"role": "user", "content": user_prompt}
                            ],
                            temperature=0.3
                        )

                        response_text = response.choices[0].message.content.strip()
                        break  # Thành công -> Thoát vòng lặp retry

                    except Exception as e:
                        log(f"⚠️ Editor API Error (Attempt {api_attempt}): {e}")

                        # Nếu chưa hết lượt thử -> Chờ (Backoff) rồi thử lại
                        if api_attempt < max_api_retries:
                            wait_time = 5 * api_attempt + 2  # 7s, 12s, 17s...
                            log(f"⏳ Waiting {wait_time}s before retrying...")
                            await asyncio.sleep(wait_time)
                        else:
                            log("❌ Max API retries exceeded for this batch.")

                # Nếu sau 5 lần vẫn không có kết quả -> Break ra ngoài để dùng Draft bù vào
                if not response_text:
                    log("⚠️ Failed to get valid response from Editor API. Falling back to draft.")
                    break

                # =========================================================
                # LOGIC PARSE (GIỮ NGUYÊN)
                # =========================================================
                try:
                    # Parse cục bộ cho batch này
                    new_blocks = []
                    local_pos = 0

                    # Quét tìm các block trả về trong batch này
                    for i in range(len(batch_original)):
                        target_num = start_block_num + i
                        start_marker = f"<<<BLOCK:{target_num}>>>"
                        end_marker = "<<<END>>>"

                        s_idx = response_text.find(start_marker, local_pos)
                        if s_idx == -1:
                            break  # Hết dữ liệu trong response này

                        content_start = s_idx + len(start_marker)
                        e_idx = response_text.find(end_marker, content_start)

                        if e_idx == -1:
                            log(f"⚠️ Block {target_num} truncated. Stopping batch here.")
                            break  # Block bị cắt cụt, bỏ qua

                        content = response_text[content_start:e_idx].strip()
                        new_blocks.append(content)
                        local_pos = e_idx + len(end_marker)

                    # --- CẬP NHẬT TIẾN ĐỘ ---
                    if not new_blocks:
                        log("⚠️ Batch trả về 0 block hợp lệ (Format error). Dừng thử lại batch này.")
                        # Reset lại outer_attempt để không bị kẹt, hoặc break để dùng draft
                        break

                    collected_blocks.extend(new_blocks)
                    current_idx += len(new_blocks)

                    # Reset attempt vòng ngoài vì đã thành công 1 batch
                    outer_attempt_count = 0

                    log(f"EDITOR: Batch done. Got {len(new_blocks)} blocks. Progress: {current_idx}/{total_blocks}")

                except Exception as e:
                    log(f"⚠️ Editor Parsing Error in batch: {e}")
                    break  # Lỗi parse thì break ra, dùng draft bù vào phần còn lại

            # --- KẾT THÚC VÒNG LẶP ---

            # Kiểm tra nếu vẫn thiếu (do hết retries hoặc lỗi)
            if len(collected_blocks) < total_blocks:
                missing = total_blocks - len(collected_blocks)
                log(f"⚠️ Filling {missing} final missing blocks with DRAFT.")
                collected_blocks.extend(draft_vi_blocks[len(collected_blocks):])

            # Validate cuối cùng
            if len(collected_blocks) != len(original_blocks):
                raise RuntimeError(f"EDITOR ERROR: Block mismatch {len(collected_blocks)} vs {len(original_blocks)}")

            log("EDITOR DONE chapter")
            return collected_blocks

    # =========================================================
    # PROMPT BUILDER
    # =========================================================
    def _build_prompt(self, vi_blocks, en_blocks=None):

        if en_blocks and len(en_blocks) != len(vi_blocks):
            raise RuntimeError("EDITOR ERROR: EN/VI block count mismatch")

        total_blocks = len(vi_blocks)

        skeleton_blocks = []
        content_blocks = []

        for i in range(total_blocks):
            # skeleton KHÔNG CÓ TEXT
            skeleton_blocks.append(
                f"""<<<BLOCK:{i + 1}>>>
        <<<END>>>"""
            )

            # content dùng để tham chiếu
            ref = ""
            if en_blocks:
                ref = (
                        "\n[ENGLISH REFERENCE — DO NOT TRANSLATE]\n"
                        + en_blocks[i]
                        + "\n"
                )

            content_blocks.append(
                f"""<<<BLOCK:{i + 1}>>>
        {vi_blocks[i]}
        {ref}<<<END>>>"""
            )

        skeleton_text = "\n\n".join(skeleton_blocks)
        content_text = "\n\n".join(content_blocks)

        system_prompt = f"""
ROLE: Vietnamese Literary Editor

MISSION:
Edit Vietnamese novel text so that it reads as if written by a skilled Vietnamese novelist.
The prose must be natural, fluent, and literary, with strong rhythm and voice,
while preserving the original meaning exactly.


CRITICAL INSTRUCTION (NON-NEGOTIABLE):

You are given a FIXED OUTPUT SKELETON.
You MUST fill in the Vietnamese text INSIDE EACH BLOCK.

- You MUST NOT remove any block
- You MUST NOT add any block
- You MUST NOT change block numbers
- You MUST NOT change <<<BLOCK:N>>> or <<<END>>>
- You MUST fill EVERY block from 1 to {total_blocks}
- If a block needs no change, COPY the original Vietnamese text AS IS.

ENGLISH REFERENCE RULES (CRITICAL):

- English text is provided ONLY to resolve ambiguity.
- You MUST NOT translate from English.
- You MUST NOT rewrite based on English phrasing.
- You MUST NOT introduce any meaning not already present in Vietnamese.
- All output MUST be derivable from Vietnamese text alone.

OUTPUT RULES:
- Output ONLY the skeleton with filled Vietnamese text
- No explanations
If you output fewer than {total_blocks} blocks, the output is INVALID.

 """

        user_prompt = f"""
        OUTPUT SKELETON (DO NOT MODIFY STRUCTURE):
        {skeleton_text}

        -------------------------

        ORIGINAL VIETNAMESE CONTENT (REFERENCE ONLY):
        {content_text}

        -------------------------

        TASK:
        Fill the Vietnamese text into EACH block of the skeleton.
        """

        return system_prompt, user_prompt

    # =========================================================
    # PARSER (FAIL-LOUD)
    # =========================================================
    def _parse_blocks(self, text: str, expected_blocks: int):
        blocks = {}
        current_id = None
        current_lines = []

        for line in text.splitlines():
            line = line.rstrip()

            if line.startswith("<<<BLOCK:"):
                if current_id is not None:
                    raise RuntimeError("EDITOR PARSE ERROR: nested BLOCK")

                try:
                    current_id = int(line.replace("<<<BLOCK:", "").replace(">>>", ""))
                    current_lines = []
                except Exception:
                    raise RuntimeError(f"EDITOR PARSE ERROR: invalid block header {line}")

            elif line == "<<<END>>>":
                if current_id is None:
                    raise RuntimeError("EDITOR PARSE ERROR: END without BLOCK")

                blocks[current_id] = "\n".join(current_lines).strip()
                current_id = None
                current_lines = []

            else:
                if current_id is not None:
                    current_lines.append(line)

        if current_id is not None:
            raise RuntimeError("EDITOR PARSE ERROR: unterminated BLOCK")

        if not blocks:
            raise RuntimeError("EDITOR PARSE ERROR: no blocks parsed")

        # Reconstruct in order
        result = []

        for i in range(1, expected_blocks + 1):
            if i not in blocks:
                raise RuntimeError(f"EDITOR PARSE ERROR: missing block {i}")
            result.append(blocks[i])

        return result

    # =========================================================
    # INVARIANT VALIDATION
    # =========================================================
    def _validate_invariants(
        self,
        *,
        before: List[str],
        after: List[str],
    ):
        if len(before) != len(after):
            raise RuntimeError(
                f"EDITOR BLOCK COUNT MISMATCH: "
                f"in={len(before)} out={len(after)}"
            )

        for i, a in enumerate(after, start=1):
            if not a:
                raise RuntimeError(
                    f"EDITOR ERROR: empty block after edit | block={i}"
                )
