# engine/html_rebuilder.py
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

    # --- REBUILD ---
    for idx, (en_tag, vi_text) in enumerate(
            zip(html_nodes, translated_blocks), start=1
    ):
        if not vi_text or not vi_text.strip():
            raise RuntimeError(
                f"HTML_REBUILDER ERROR: empty VI block at index {idx}"
            )

        # --- FIX QUAN TRỌNG: TÌM ROOT SOUP ---
        # Thay vì dùng en_tag.soup (có thể bị None), ta leo ngược lên cây DOM
        soup_root = en_tag
        while soup_root.parent is not None:
            soup_root = soup_root.parent

        # Kiểm tra xem cái gốc tìm được có chức năng tạo thẻ không
        if not hasattr(soup_root, 'new_tag'):
            raise RuntimeError(
                f"HTML_REBUILDER ERROR: en_tag at index {idx} is detached from Soup tree."
            )

        # Tạo thẻ div tiếng Việt
        vi_div = soup_root.new_tag("div")
        vi_div["class"] = "bi-vi"
        vi_div.string = vi_text

        # ZERO-TOUCH: chỉ insert, KHÔNG đụng EN
        if en_tag.parent is None:
            raise RuntimeError(
                f"HTML_REBUILDER ERROR: en_tag at index {idx} has no parent (cannot insert)."
            )

        en_tag.insert_after(vi_div)

    log("HTML_REBUILDER: done")