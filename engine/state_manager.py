# engine/state_manager.py
import json
from pathlib import Path
from utils.logger import log

STATE_DIR = Path("state")
STATE_DIR.mkdir(exist_ok=True)

GLOSSARY_FILE = STATE_DIR / "glossary.json"
SUMMARY_FILE = STATE_DIR / "summary_context.json"
CHAR_FILE = STATE_DIR / "character_context.json"


# =====================================================
# LOW-LEVEL IO
# =====================================================
def _load_json(path: Path, default):
    if not path.exists():
        log(f"STATE INIT: {path.name}")
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _save_json(path: Path, data):
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    log(f"STATE SAVED: {path.name}")


# =====================================================
# LOADERS
# =====================================================
def load_glossary():
    return _load_json(
        GLOSSARY_FILE,
        {"meta": {"locked": True}, "entries": []},
    )


def load_summary():
    return _load_json(
        SUMMARY_FILE,
        {},  # FULL summary object
    )


def load_characters():
    return _load_json(
        CHAR_FILE,
        [],  # FULL character list
    )


# =====================================================
# COMMIT (ONCE PER CHAPTER)
# =====================================================
def commit_chapter(in_state):
    """
    Persist chapter-level state.
    Assumes in_state already contains FULL snapshots
    produced by SummaryEngine / CharacterEngine.
    """
    log("STATE COMMIT: chapter")

    # -------------------------
    # GLOSSARY (delta-merge)
    # -------------------------
    if in_state.glossary_delta:
        glossary = load_glossary()
        glossary["entries"].extend(in_state.glossary_delta)
        _save_json(GLOSSARY_FILE, glossary)
    else:
        log("STATE COMMIT: no glossary delta")

    # -------------------------
    # SUMMARY (FULL overwrite)
    # -------------------------
    if in_state.summary_snapshot is not None:
        if in_state.summary_snapshot:
            _save_json(SUMMARY_FILE, in_state.summary_snapshot)
        else:
            log("STATE COMMIT: summary snapshot EMPTY → skipped")
    else:
        log("STATE COMMIT: no summary snapshot")

    # -------------------------
    # CHARACTERS (FULL overwrite)
    # -------------------------
    if in_state.character_snapshot is not None:
        if in_state.character_snapshot:
            _save_json(CHAR_FILE, in_state.character_snapshot)
        else:
            log("STATE COMMIT: character snapshot EMPTY → skipped")
    else:
        log("STATE COMMIT: no character snapshot")
