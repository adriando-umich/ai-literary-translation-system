# epub/epub_loader.py
from ebooklib import epub

def load_epub(path):
    return epub.read_epub(path)
