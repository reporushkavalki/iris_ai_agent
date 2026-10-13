"""Join the inner circle: a one-time payment in SOL opens a private Telegram group.

Iris itself holds no secret for this. A small server run by the developer (see the Iris_innercircle_server folder) checks the payment
on the Solana chain and asks its Telegram bot for a join link that works only for the buyer's own @username.
What this app sends to that server: the buyer's Telegram username and a random payment code. Nothing else.
"""
import os
import re

from iris import net, prefs

# The address of the inner-circle server. The developer sets it here (or in the IRIS_INNER_API setting) before publishing Iris.
API = os.environ.get("IRIS_INNER_API", "https://iris-inner.whalesync-app.workers.dev").strip().rstrip("/")
PRICE_SOL = "0.2"
MAX_LAMPORTS = 5_000_000_000          # sanity limit: the app never asks a wallet for more than 5 SOL, whatever a server says
_B58 = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
_USER = re.compile(r"^[A-Za-z][A-Za-z0-9_]{4,31}$")


def configured() -> bool:
    return API.startswith("https://")


def saved() -> dict:
    d = prefs.load().get("inner")
    return d if isinstance(d, dict) else {}


def info() -> dict:
    s = saved()
    return {"configured": configured(), "price_sol": PRICE_SOL, "username": s.get("username"), "link": s.get("link"), "started": bool(s.get("nonce"))}


def _need() -> None:
    if not configured():
        raise net.ApiError("The inner circle is not open yet.")


def start(username: str) -> dict:
    """Asks the server for a payment code for this Telegram username. Returns what the wallet needs to pay."""
    _need()
    u = (username or "").strip().lstrip("@")
    if not _USER.match(u):
        raise net.ApiError("Type your Telegram username, like @yourname (5 to 32 letters, digits or _).")
    r = net.request("POST", API + "/start", json={"username": u})
    ref, rec, lam, nonce = r.get("reference"), r.get("recipient"), r.get("lamports"), r.get("nonce")
    if not (isinstance(ref, str) and _B58.match(ref) and isinstance(rec, str) and _B58.match(rec) and isinstance(lam, int)
            and 0 < lam <= MAX_LAMPORTS and isinstance(nonce, str) and nonce):
        raise net.ApiError("The inner circle server gave an unexpected answer.")
    prefs.set_value("inner", {"username": u, "nonce": nonce, "link": None})
    return {"username": u, "reference": ref, "recipient": rec, "lamports": lam, "sol": f"{lam / 1e9:.9f}".rstrip("0").rstrip(".")}


def check() -> dict:
    """Has the saved purchase been paid? Returns {paid, link, note}. The link is kept on this computer so it can be shown again."""
    _need()
    s = saved()
    if not s.get("nonce"):
        raise net.ApiError("Nothing to check yet. Start a payment first.")
    if s.get("link"):
        return {"paid": True, "link": s["link"], "username": s.get("username")}
    r = net.request("POST", API + "/check", json={"username": s["username"], "nonce": s["nonce"]})
    link = r.get("link")
    if r.get("paid") and isinstance(link, str) and link.startswith("https://t.me/"):
        prefs.set_value("inner", {**s, "link": link})
        return {"paid": True, "link": link, "username": s["username"]}
    return {"paid": bool(r.get("paid")), "link": None, "username": s.get("username"), "note": (r.get("note") or "")[:300]}


def reset() -> None:
    prefs.set_value("inner", None)
