"""Paths. Everything a user enters (keys, wallets, history) lives in ./data, which git ignores."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("IRIS_DATA_DIR") or ROOT / "data")
DATA_DIR.mkdir(parents=True, exist_ok=True)

VAULT_FILE = DATA_DIR / "vault.json"        # API keys / tokens
WALLETS_FILE = DATA_DIR / "wallets.json"    # public wallet addresses
SOCIALS_FILE = DATA_DIR / "socials.json"    # social accounts to track
PREFS_FILE = DATA_DIR / "prefs.json"        # small settings (demo mode, timezone)
PORTFOLIO_DB = DATA_DIR / "portfolio.db"    # balance snapshots
SOCIALS_DB = DATA_DIR / "socials.db"        # follower snapshots
WEB_DIR = ROOT / "web"
