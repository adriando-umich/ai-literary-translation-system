import json
from pathlib import Path
from utils.logger import log

STATE_DIR = Path("state")
STATE_DIR.mkdir(exist_ok=True)

# Thư mục lưu HTML đã dịch để Resume
CHAPTERS_DIR = STATE_DIR / "chapters"
CHAPTERS_DIR.mkdir(exist_ok=True)

GLOSSARY_FILE = STATE_DIR / "glossary.json"
SUMMARY_FILE = STATE_DIR / "summary_context.json"
CHAR_FILE = STATE_DIR / "character_context.json"

# =====================================================
# LOW-LEVEL IO & CACHE
# =====================================================
def _load_json(path: Path, default):
    if not path.exists():
        log(f"STATE INIT: {path.name}")
        return default
    return json.loads(path.read_text(encoding="utf-8"))

def _save_json(path: Path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"STATE SAVED: {path.name}")

def save_chapter_html(idx: int, html_content: str):
    path = CHAPTERS_DIR / f"chapter_{idx}.html"
    path.write_text(html_content, encoding="utf-8")

def get_chapter_html(idx: int):
    path = CHAPTERS_DIR / f"chapter_{idx}.html"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return None

# =====================================================
# LOADERS
# =====================================================
def load_glossary():
    return _load_json(GLOSSARY_FILE, {"meta": {"locked": True}, "entries": []})

def load_summary():
    return _load_json(SUMMARY_FILE, {})

def load_characters():
    return _load_json(CHAR_FILE, [])

# =====================================================
# COMMIT (ONCE PER CHAPTER)
# =====================================================
def commit_chapter(idx, in_state, html_content):
    """
    Nâng cấp: Nhận thêm idx và html_content để lưu cache.
    """
    log(f"STATE COMMIT: chapter {idx}")

    # 1. Lưu HTML Cache ngay lập tức
    save_chapter_html(idx, html_content)

    # 2. GLOSSARY (delta-merge)
    if in_state.glossary_delta:
        glossary = load_glossary()
        glossary["entries"].extend(in_state.glossary_delta)
        _save_json(GLOSSARY_FILE, glossary)

    # 3. SUMMARY & CHARACTERS (giữ nguyên logic cũ)
    if in_state.summary_snapshot:
        _save_json(SUMMARY_FILE, in_state.summary_snapshot)
    if in_state.character_snapshot:
        _save_json(CHAR_FILE, in_state.character_snapshot)