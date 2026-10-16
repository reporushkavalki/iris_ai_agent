"""Local key vault: data/vault.json on the user's own computer.

* Values go in once and the provider is then LOCKED: it cannot be overwritten or removed until the user unlocks it.
* The browser never gets a secret back, only a masked hint such as "••••a1b2".
* On Windows the file is encrypted with the Windows account (DPAPI): it only opens for the same user on the same PC.
  Elsewhere it is plain JSON restricted to the current user. Either way it is git-ignored; never share it.
* A vault that cannot be opened (for example copied from another PC) is never overwritten: it is moved aside first.
"""
import base64
import json
import os
import re
import threading
import time

from iris import secure
from iris.config import VAULT_FILE

_lock = threading.RLock()
PROBLEM = {"message": ""}        # shown in the app when the saved keys could not be opened


def _read_doc():
    """-> (dict, state) where state is 'none', 'plain', 'enc' or 'unreadable'."""
    try:
        raw = VAULT_FILE.read_bytes()
    except OSError:
        return {}, "none"
    try:
        doc = json.loads(raw.decode("utf-8"))
    except ValueError:
        return {}, "unreadable"
    if not isinstance(doc, dict):
        return {}, "unreadable"
    if doc.get("enc") == "dpapi" and isinstance(doc.get("data"), str):
        try:
            inner = json.loads(secure.unprotect(base64.b64decode(doc["data"])).decode("utf-8"))
        except Exception:                # any failure to open it counts as "cannot be opened here"
            return {}, "unreadable"
        return (inner if isinstance(inner, dict) else {}), "enc"
    return doc, "plain"


def _load() -> dict:
    with _lock:
        d, state = _read_doc()
        if state == "unreadable":
            PROBLEM["message"] = ("Your saved keys could not be opened. They were probably saved by another Windows account "
                                  "or another computer. Enter them again; the old file is kept next to it.")
        elif state == "plain" and d and secure.available():
            try:
                _save(d)         # upgrade an old plain-text vault to the encrypted form, once
            except OSError:
                pass
        return d


def _encode(d: dict) -> bytes:
    payload = json.dumps(d, indent=2).encode("utf-8")
    if secure.available():
        try:
            blob = secure.protect(payload)
            if secure.unprotect(blob) == payload:      # prove it opens again before replacing the old file
                return json.dumps({"v": 1, "enc": "dpapi", "data": base64.b64encode(blob).decode("ascii")}).encode("utf-8")
        except Exception:     # encryption trouble must never lose the keys: fall back to the private plain file
            pass
    return payload


def _save(d: dict) -> None:
    with _lock:
        _, state = _read_doc()
        if state == "unreadable" and VAULT_FILE.exists():
            VAULT_FILE.replace(VAULT_FILE.with_name(f"vault.unreadable-{int(time.time())}.json"))
            PROBLEM["message"] = ""
        tmp = VAULT_FILE.with_suffix(".tmp")
        tmp.write_bytes(_encode(d))
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
