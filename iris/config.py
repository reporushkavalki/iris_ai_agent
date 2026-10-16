"""Paths. Everything a user enters (keys, wallets, history) lives in one data folder, which git ignores.

* Normal (zip / launcher) use: ./data next to the program, exactly as before.
* Installed desktop app (IRIS_PACKAGED=1): the per-user folder of the operating system
  (Windows %APPDATA%\\Iris, macOS ~/Library/Application Support/Iris, Linux ~/.local/share/iris),
  so installing or updating the program never touches your keys, wallets or history.
* IRIS_DATA_DIR overrides both.
"""
import os
import shutil
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGED = bool(os.getenv("IRIS_PACKAGED"))


def user_data_dir() -> Path:
    if sys.platform.startswith("win"):
        base = os.getenv("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / "Iris"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Iris"
    return Path(os.getenv("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "iris"


def _pick_data_dir() -> Path:
    env = os.getenv("IRIS_DATA_DIR")
    if env:
        return Path(env)
    return user_data_dir() if PACKAGED else ROOT / "data"


DATA_DIR = _pick_data_dir()
DATA_DIR.mkdir(parents=True, exist_ok=True)

VAULT_FILE = DATA_DIR / "vault.json"        # API keys / tokens (encrypted on Windows)
WALLETS_FILE = DATA_DIR / "wallets.json"    # public wallet addresses
SOCIALS_FILE = DATA_DIR / "socials.json"    # social accounts to track
PREFS_FILE = DATA_DIR / "prefs.json"        # small settings (demo mode, timezone)
PORTFOLIO_DB = DATA_DIR / "portfolio.db"    # balance snapshots
SOCIALS_DB = DATA_DIR / "socials.db"        # follower snapshots
WEB_DIR = ROOT / "web"

# What moving to a new data folder copies. Logs, the desktop-icon marker and temp files are left behind.
_SKIP_SUFFIX = (".log", ".tmp", ".bak", "-wal", "-shm", "-journal")
_SKIP_NAME = {".shortcut", ".gitkeep"}


def import_data(src, dest=None) -> dict:
    """Copy an older data folder (for example the `data` folder of the zip version) into the data folder.

    Never overwrites: a file that already exists in the destination is kept and reported as skipped.
    SQLite files are copied with SQLite's own backup, so a copy taken while Iris was running is consistent.
    """
    src = Path(src).expanduser()
    dest = Path(dest) if dest else DATA_DIR
    if not src.is_dir():
        raise FileNotFoundError("That folder does not exist.")
    if src.resolve() == dest.resolve():
        raise ValueError("That is already Iris's data folder.")
    dest.mkdir(parents=True, exist_ok=True)
    out = {"copied": [], "skipped": []}
    for p in sorted(src.iterdir()):
        if not p.is_file() or p.name in _SKIP_NAME or p.name.endswith(_SKIP_SUFFIX):
            continue
        target = dest / p.name
        if target.exists():
            out["skipped"].append(p.name)
            continue
        if p.suffix == ".db":
            a = sqlite3.connect(f"file:{p.as_posix()}?mode=ro", uri=True)
            b = sqlite3.connect(str(target))
            try:
                a.backup(b)
            finally:
                a.close()
                b.close()
        else:
            shutil.copy2(p, target)
        out["copied"].append(p.name)
    return out


def import_legacy_if_new() -> dict | None:
    """Installed app, first start: if the data folder is empty and an old ./data sits next to the program, import it."""
    if not PACKAGED or os.getenv("IRIS_DATA_DIR"):
        return None
    old = ROOT / "data"
    if not old.is_dir() or any(p.name in (VAULT_FILE.name, WALLETS_FILE.name, PORTFOLIO_DB.name) for p in DATA_DIR.iterdir()):
        return None
    if not any((old / n).exists() for n in (VAULT_FILE.name, WALLETS_FILE.name, PORTFOLIO_DB.name)):
        return None
    try:
        return import_data(old)
    except (OSError, ValueError, sqlite3.Error):
        return None
