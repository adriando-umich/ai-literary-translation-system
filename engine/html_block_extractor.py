# engine/html_block_extractor.py
# Extract block-level *translatable* text units from HTML
#
# CRITICAL DESIGN:
# - soup is CREATED OUTSIDE and PASSED IN
# - nodes returned MUST belong to that soup
# - extractor NEVER creates or clones soup

from bs4 import BeautifulSoup, Tag
from utils.logger import log


BLOCK_TAGS = {
    "p", "h1", "h2", "h3", "h4", "h5", "h6",
    "li", "blockquote"
}


def is_translatable_block(text: str, tag_name: str) -> bool:
    lowered = text.lower()

    blacklist = [
        "svg", "path d=", "base64",
        "<style", "viewbox", "xmlns",
        "{", "}", "fill=", "stroke=",
    ]

    if any(b in lowered for b in blacklist):
        return False

    letter_count = sum(c.isalpha() for c in text)

    # Headings
    if tag_name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
        return letter_count >= 3

    # ALL CAPS slogans (WAR IS PEACE, FREEDOM IS SLAVERY)
    if text.isupper() and letter_count >= 3:
        return True

    # Narrative paragraphs (allow short sentences)
    return letter_count >= 5

def extract_html_blocks(soup: BeautifulSoup):
    """
    INPUT:
      soup: BeautifulSoup — OWNED by caller (main.py)

    OUTPUT:
      blocks: list[str] — text to translate
      nodes:  list[Tag] — nodes to be mutated IN-PLACE

    INVARIANTS:
      - len(blocks) == len(nodes)
      - nodes belong to EXACTLY this soup
    """

    blocks = []
    nodes = []

    for tag in soup.find_all(BLOCK_TAGS):
        if not isinstance(tag, Tag):
            continue

        text = tag.get_text(strip=True)

        if not text:
            continue

        if not is_translatable_block(text, tag.name):
            log(f"HTML_BLOCK_EXTRACTOR: skip tag={tag.name} text={text[:50]}")
            continue

        blocks.append(text)
        nodes.append(tag)
    log(f"HTML_BLOCK_EXTRACTOR: {len(blocks)} blocks extracted")
    return blocks, nodes
