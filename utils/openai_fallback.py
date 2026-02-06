# utils/openai_fallback.py
import os
import time
from openai import OpenAI
from utils.logger import log


def call_openai_fallback(
        system_prompt: str,
        user_prompt: str,
        model: str = "gpt-4o-mini",
        max_retries: int = 2
) -> str:
    """
    Gọi OpenAI với cơ chế Retry & Tự động thích ứng tham số (Smart Params).
    Hỗ trợ cả GPT-4o (max_tokens) và GPT-5/o1 (max_completion_tokens).
    Có xử lý Safety Refusal để in log rõ ràng.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("CRITICAL: Google Failed AND OPENAI_API_KEY is missing.")

    client = OpenAI(api_key=api_key)
    total_attempts = max_retries + 1

    for attempt in range(1, total_attempts + 1):
        try:
            log(f"🛡️ OPENAI FALLBACK (Attempt {attempt}/{total_attempts}): Using [{model}]")

            # --- LOGIC CHỌN THAM SỐ THÔNG MINH (GIỮ NGUYÊN) ---
            is_new_gen = any(x in model for x in ["o1-", "o3-", "gpt-5", "reasoning"])

            params = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ]
            }

            if is_new_gen:
                # Model mới: Dùng max_completion_tokens
                params["max_completion_tokens"] = 3000
            else:
                # Model cũ: Dùng max_tokens và temperature
                params["max_tokens"] = 3000
                params["temperature"] = 0.2
            # --------------------------------------

            response = client.chat.completions.create(**params)
            message = response.choices[0].message

            # === [THÊM] KIỂM TRA TỪ CHỐI (SAFETY REFUSAL) ===
            # Nếu OpenAI từ chối trả lời vì lý do an toàn
            if hasattr(message, 'refusal') and message.refusal:
                refusal_msg = message.refusal
                log(f"❌ OPENAI REFUSED (Safety Policy): {refusal_msg}")
                # Raise lỗi ngay để thoát vòng lặp retry (Retry vô ích với lỗi Policy)
                raise ValueError(f"OpenAI Safety Refusal: {refusal_msg}")

            # Kiểm tra finish_reason (Content Filter)
            if response.choices[0].finish_reason == "content_filter":
                log("❌ OPENAI BLOCKED: Finish reason is 'content_filter'")
                raise ValueError("OpenAI Content Filter Blocked.")

            content = message.content
            if not content:
                raise ValueError("Empty content from OpenAI (Likely filtered but no refusal message)")

            return content.strip()

        except Exception as e:
            log(f"❌ OPENAI ERROR (Attempt {attempt}): {e}")

            # Nếu lỗi là do Safety Refusal hoặc Content Filter -> KHÔNG RETRY, ném lỗi luôn
            error_str = str(e)
            if "Safety Refusal" in error_str or "Content Filter" in error_str:
                raise e

            if attempt < total_attempts:
                time.sleep(2 * attempt)
            else:
                raise e