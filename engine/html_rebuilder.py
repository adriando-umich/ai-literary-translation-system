# engine/html_rebuilder.py
from bs4 import BeautifulSoup
from utils.logger import log


def rebuild_html_blocks(html_nodes: list, translated_blocks: list[str]) -> None:
    """
    Rebuild HTML song ngữ theo BLOCK LEVEL (deterministic).
    """

    log("HTML_REBUILDER: start (block-level, no sentence split)")

    # --- HARD VALIDATION ---
    if len(html_nodes) != len(translated_blocks):
        raise RuntimeError(
            "HTML_REBUILDER ERROR: node/block mismatch — "
            f"{len(html_nodes)} nodes vs {len(translated_blocks)} blocks"
        )

    # --- REBUILD --- (Đã kéo khối for ra ngoài lề, ngang hàng với lệnh IF phía trên)
    for idx, (tag, vi_text) in enumerate(
            zip(html_nodes, translated_blocks), start=1
    ):
        if not vi_text or not vi_text.strip():
            raise RuntimeError(f"HTML_REBUILDER ERROR: empty VI block at index {idx}")

        en_text = tag.get_text(strip=True)

        # CHỈNH SỬA TẠI ĐÂY:
        tag.name = "div"
        tag.clear()

        # Cấu trúc mới
        html_fragment = f"""
<div class="bi-en">{en_text}</div>
<div class="bi-vi">{vi_text}</div>
"""
        fragment = BeautifulSoup(html_fragment, "html.parser")
        tag.append(fragment)
        # (Đã xóa bỏ đoạn code lặp dư thừa ở đây)

    log("HTML_REBUILDER: done")