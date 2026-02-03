# utils/inspect.py
import ebooklib
from bs4 import BeautifulSoup


def extract_chapter_title(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")

    for tag in ["h1", "h2", "title"]:
        el = soup.find(tag)
        if el and el.get_text(strip=True):
            return el.get_text(strip=True)

    return "(no title found)"


def print_chapter_list(book) -> int:
    """
    Print chapter list from an already-loaded EpubBook.
    IMPORTANT: Do NOT load EPUB again here.
    """

    print("\n📖 EPUB CHAPTER LIST\n")

    idx = 0
    for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
        html = item.get_content().decode("utf-8", errors="ignore")
        title = extract_chapter_title(html)

        print(f"[{idx:02d}] {item.get_name():40s} | {title}")
        idx += 1

    print()
    return idx
