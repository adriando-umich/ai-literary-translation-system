# epub/epub_loader.py
from pathlib import Path
from ebooklib import epub

def load_epub(path):
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"EPUB not found: {path}. Place your input file at the path or set INPUT_EPUB.")
    if not path.is_file():
        raise ValueError(f"Not a file: {path}")
    return epub.read_epub(str(path))
