# engine/checkpoint_manager.py
import json
import os
from utils.logger import log

CHECKPOINT_FILE = "state/checkpoint.json"


def load_checkpoint() -> set:
    if not os.path.exists(CHECKPOINT_FILE):
        log("CHECKPOINT: none found (fresh run)")
        return set()

    with open(CHECKPOINT_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    done = set(data.get("done_chapters", []))
    log(f"CHECKPOINT: loaded {len(done)} chapters")
    return done


def mark_done(idx: int):
    done = load_checkpoint()
    done.add(idx)

    os.makedirs(os.path.dirname(CHECKPOINT_FILE), exist_ok=True)
    with open(CHECKPOINT_FILE, "w", encoding="utf-8") as f:
        json.dump(
            {"done_chapters": sorted(done)},
            f,
            ensure_ascii=False,
            indent=2,
        )

    log(f"CHECKPOINT: marked chapter {idx} done")
