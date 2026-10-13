"""Local key vault: data/vault.json on the user's own computer.

* Values go in once and the provider is then LOCKED: it cannot be overwritten or removed until the user unlocks it.
* The browser never gets a secret back, only a masked hint such as "••••a1b2".
* The file is plain JSON (restricted to the current user where the OS allows it). It is git-ignored; never share it.
"""
import json
import os
import re
import threading

from iris.config import VAULT_FILE

_lock = threading.RLock()


def _load() -> dict:
    with _lock:
        try:
            d = json.loads(VAULT_FILE.read_text(encoding="utf-8"))
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}


def _save(d: dict) -> None:
    tmp = VAULT_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, indent=2), encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, VAULT_FILE)   # one step, so a crash cannot leave half a file


def get(pid: str) -> dict:
    return dict((_load().get(pid) or {}).get("values") or {})


def exists(pid: str) -> bool:
    return bool(get(pid))


def is_locked(pid: str) -> bool:
    return bool((_load().get(pid) or {}).get("locked", False))


def save(pid: str, values: dict, lock: bool = True) -> None:
    """Merge non-empty values into the provider's entry (blank = keep the old value)."""
    with _lock:
        d = _load()
        entry = d.setdefault(pid, {"values": {}, "locked": False})
        if entry.get("locked"):
            raise PermissionError("This connection is locked. Unlock it first to change it.")
        for k, v in values.items():
            v = (v or "").strip() if isinstance(v, str) else v
            if v not in (None, ""):
                entry["values"][k] = v
        entry["locked"] = bool(lock and entry["values"])
        _save(d)


def set_locked(pid: str, locked: bool) -> None:
    with _lock:
        d = _load()
        if pid not in d:
            raise KeyError("Nothing saved for this connection yet.")
        d[pid]["locked"] = bool(locked)
        _save(d)


def remove(pid: str) -> None:
    with _lock:
        d = _load()
        if pid not in d:
            return
        if d[pid].get("locked"):
            raise PermissionError("This connection is locked. Unlock it first to remove it.")
        del d[pid]
        _save(d)


def mask(value: str) -> str:
    value = str(value or "")
    return "••••" + value[-4:] if len(value) >= 10 else "••••"


def scrub(text) -> str:
    """Remove any stored secret (and common key-in-URL patterns) from a message before it is shown anywhere."""
    s = str(text)
    for entry in _load().values():
        for v in (entry.get("values") or {}).values():
            if isinstance(v, str) and len(v) >= 8:
                s = s.replace(v, "***")
    s = re.sub(r"(?i)(api[-_]?key|token|secret|signature)=([^&\s]+)", r"\1=***", s)
    s = re.sub(r"sk-ant-[A-Za-z0-9_\-]+", "sk-ant-***", s)
    return s
