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

    # --- REBUILD --- (Đã kéo khối for ra ngoài lề, ngang hàng với lệnh IF phía trên)
    for idx, (en_tag, vi_text) in enumerate(
            zip(html_nodes, translated_blocks), start=1
    ):
        if not vi_text or not vi_text.strip():
            raise RuntimeError(
                f"HTML_REBUILDER ERROR: empty VI block at index {idx}"
            )

        soup = en_tag.soup
        if soup is None:
            raise RuntimeError(
                "HTML_REBUILDER ERROR: en_tag is detached from soup"
            )

        vi_div = soup.new_tag("div")
        vi_div["class"] = "bi-vi"
        vi_div.string = vi_text

        # ZERO-TOUCH: chỉ insert, KHÔNG đụng EN
        en_tag.insert_after(vi_div)


    log("HTML_REBUILDER: done")