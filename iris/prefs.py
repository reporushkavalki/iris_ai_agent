"""Small non-secret settings in data/prefs.json."""
import json
import os
import threading

from iris.config import PREFS_FILE

_lock = threading.RLock()
DEFAULTS = {"demo": False}


def load() -> dict:
    with _lock:
        try:
            d = json.loads(PREFS_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            d = {}
    return {**DEFAULTS, **(d if isinstance(d, dict) else {})}


def set_value(key: str, value) -> None:
    if key not in DEFAULTS:
        raise ValueError("unknown setting")
    with _lock:
        d = load()
        d[key] = value
        tmp = PREFS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, indent=2), encoding="utf-8")
        os.replace(tmp, PREFS_FILE)


def demo_on() -> bool:
    return bool(load().get("demo"))
