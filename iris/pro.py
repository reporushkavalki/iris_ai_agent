"""Iris Pro: the license, the plan limits and the hosted AI.

Iris is free and complete without Pro. A license key (saved in the key vault like any other key) adds:
  * no limit on connected accounts (the free plan has FREE_ACCOUNT_LIMIT),
  * Iris AI included: the chat works without your own Claude key, within a monthly allowance,
  * early access and the Inner Circle.

How it works: the license is checked on the Pro server (PRO_URL). The answer is remembered in data/pro.json for a few days,
so Pro keeps working while you are offline. The hosted AI is a thin relay on that same server: Iris sends the chat there with
the license key, the server adds the Claude key (which never leaves the server) and keeps count against the monthly allowance.

Honest limit: this program is open, so the account limit is a convenience, not a lock. What a license really buys is the server side
(the hosted AI and its allowance).
"""
import hashlib
import json
import os
import threading
import time

from iris import net, prefs, providers, vault
from iris.config import DATA_DIR, PRO_FILE, PRO_URL, UPGRADE_URL

FREE_ACCOUNT_LIMIT = 5

# The free plan is deliberately small. Four things are free (Wallets and Stocks & commodities are not "providers", they are always free):
#   1 Claude AI chat with your own key, 2 Kraken (the one free exchange: it serves the US, the EU and the UK), 3 wallets (public addresses), 4 stocks & commodities typed by hand.
# Every other connection is listed in Connections behind a lock and needs Iris Pro. Change the set here to move something.
FREE_PROVIDERS = frozenset({"pro", "anthropic", "kraken"})
CACHE_SECONDS = 600              # how long a good answer is reused before asking the server again
OFFLINE_DAYS = 7                 # how long Pro keeps working when the server cannot be reached

_lock = threading.RLock()
_mem: dict = {"t": 0.0, "fp": "", "v": None}


class ProError(Exception):
    """A message meant for the person using the chat (allowance used up, license not accepted ...)."""


def license_key() -> str:
    return str(vault.get("pro").get("license_key") or "").strip()


def _fp(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def free_status(reason: str = "") -> dict:
    return {"plan": "free", "active": False, "reason": reason, "expires": None, "ai": None, "offline": False,
            "account_limit": FREE_ACCOUNT_LIMIT, "upgrade_url": UPGRADE_URL or None}


def _read_file() -> dict:
    try:
        d = json.loads(PRO_FILE.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_file(d: dict) -> None:
    try:
        tmp = PRO_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(d), encoding="utf-8")
        os.replace(tmp, PRO_FILE)
    except OSError:
        pass


def _active_status(server: dict, offline: bool = False) -> dict:
    return {"plan": "pro", "active": True, "reason": "", "expires": server.get("expires"), "ai": server.get("ai"),
            "offline": offline, "account_limit": None, "upgrade_url": None, "name": server.get("name"), "devices": server.get("devices")}


# ---------- this device ----------
# A license works on a few devices (the server decides how many). Each install of Iris tells the server which device it is:
# on Windows an id made from the machine id, elsewhere a random id kept in the data folder. Only a hash ever leaves this computer.
DEVICE_FILE = DATA_DIR / "device.id"
_device: dict = {"id": ""}


def _machine_guid() -> str:
    if os.name != "nt":
        return ""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography", 0,
                            winreg.KEY_READ | getattr(winreg, "KEY_WOW64_64KEY", 0)) as k:
            return str(winreg.QueryValueEx(k, "MachineGuid")[0] or "")
    except OSError:
        return ""


def device_id() -> str:
    """A stable id for this computer (32 hex characters). Never contains anything personal."""
    if _device["id"]:
        return _device["id"]
    guid = _machine_guid()
    if guid:
        _device["id"] = hashlib.sha256(("iris-device:" + guid).encode()).hexdigest()[:32]
        return _device["id"]
    try:
        v = DEVICE_FILE.read_text(encoding="utf-8").strip()
        if len(v) == 32 and all(c in "0123456789abcdef" for c in v):
            _device["id"] = v
            return v
    except OSError:
        pass
    v = os.urandom(16).hex()
    try:
        DEVICE_FILE.write_text(v, encoding="utf-8")
    except OSError:
        pass
    _device["id"] = v
    return v


def _headers() -> dict:
    return {"x-iris-device": device_id()}


def _ask_server(key: str) -> dict:
    try:
        return net.post(PRO_URL + "/license/status", json={"key": key}, headers=_headers(), retries=1)
    except net.ApiError as e:
        if str(e).startswith("HTTP 403"):            # e.g. the license is already used on its maximum number of devices: show the server's own words
            try:
                r = net._client.post(PRO_URL + "/license/status", json={"key": key}, headers=_headers())
                reason = (r.json() or {}).get("reason")
                if reason:
                    return {"valid": False, "reason": str(reason)}
            except Exception:  # noqa: BLE001
                pass
        raise


def release_device(key: str) -> None:
    """Frees this device's slot on the server when the license is removed here (best effort, in the background)."""
    if not key:
        return

    def run():
        try:
            net.post(PRO_URL + "/license/release", json={"key": key}, headers=_headers(), retries=1)
        except Exception:  # noqa: BLE001 - offline: the server frees unused slots by itself after a while
            pass
    threading.Thread(target=run, daemon=True).start()


def buy_pack_url() -> str:
    """The Stripe page where this license buys an extra AI pack."""
    key = license_key()
    if not key:
        raise ValueError("Paste your Iris Pro license key under Connections first.")
    try:
        ans = net.post(PRO_URL + "/stripe/pack", json={"key": key}, headers=_headers(), retries=1)
    except net.ApiError as e:
        raise ValueError("The AI pack page could not be opened: " + str(e).split(": ", 1)[-1]) from e
    url = str(ans.get("url") or "")
    if not url.startswith("https://"):
        raise ValueError("The AI pack page could not be opened. Try again in a minute.")
    return url


def refresh() -> dict:
    """Ask the Pro server now. Falls back to the last good answer (up to OFFLINE_DAYS) when it cannot be reached."""
    key = license_key()
    with _lock:
        if not key:
            _mem.update(t=time.time(), fp="", v=free_status())
            return _mem["v"]
        fp = _fp(key)
        try:
            ans = _ask_server(key)
        except net.ApiError as e:
            text = str(e)
            if text.startswith("HTTP 4") and not text.startswith("HTTP 429"):
                v = free_status("The Pro server did not accept this license key.")      # a clear "no": no grace period
                _write_file({"fp": fp, "valid": False})
            else:
                saved = _read_file()
                if saved.get("fp") == fp and saved.get("valid") and time.time() - float(saved.get("checked", 0)) < OFFLINE_DAYS * 86400:
                    v = _active_status(saved.get("server") or {}, offline=True)
                else:
                    v = free_status("Could not reach the Pro server to check the license.")
            _mem.update(t=time.time(), fp=fp, v=v)
            return v
        if ans.get("valid"):
            _write_file({"fp": fp, "valid": True, "checked": time.time(), "server": ans})
            v = _active_status(ans)
        else:
            _write_file({"fp": fp, "valid": False})
            v = free_status(str(ans.get("reason") or "This license is not valid."))
        _mem.update(t=time.time(), fp=fp, v=v)
        return v


def status(force: bool = False) -> dict:
    """Plan, limits and AI allowance. Reuses a recent answer; asks the server when it is stale or force=True."""
    key = license_key()
    if not key:
        return free_status()
    with _lock:
        if not force and _mem["v"] is not None and _mem["fp"] == _fp(key) and time.time() - _mem["t"] < CACHE_SECONDS:
            return _mem["v"]
    return refresh()


def cached_status() -> dict:
    """Never touches the network: what the last check said (used on every page load)."""
    key = license_key()
    if not key:
        return free_status()
    with _lock:
        if _mem["v"] is not None and _mem["fp"] == _fp(key):
            return _mem["v"]
    saved = _read_file()
    if saved.get("fp") == _fp(key) and saved.get("valid") and time.time() - float(saved.get("checked", 0)) < OFFLINE_DAYS * 86400:
        return _active_status(saved.get("server") or {}, offline=True)
    return free_status()


def is_pro() -> bool:
    return bool(cached_status()["active"])


def ai_ready() -> bool:
    """True when the chat can use the hosted AI: an active license whose allowance is not used up."""
    st = cached_status()
    ai = st.get("ai") or {}
    return bool(st["active"] and ai.get("enabled", True) and not ai.get("exhausted"))


def forget() -> None:
    with _lock:
        _mem.update(t=0.0, fp="", v=None)
    try:
        PRO_FILE.unlink()
    except OSError:
        pass


def public_view() -> dict:
    """For the browser. Never contains the key."""
    st = dict(cached_status())
    st["has_key"] = bool(license_key())
    st["free_account_limit"] = FREE_ACCOUNT_LIMIT
    st["accounts_used"] = count_accounts()
    return st


# ---------- the account limit ----------
def count_accounts() -> int:
    """Exchanges and brokers with saved keys, tracked wallets and hand-typed stock accounts."""
    from iris.chains import wallets_store
    from iris import stocks_store
    n = sum(1 for p in providers.PROVIDERS if p["group"] == "exchange" and providers.is_configured(p["id"]))
    return n + len(wallets_store.load()) + len(stocks_store.load())


def is_free_provider(pid: str) -> bool:
    return pid in FREE_PROVIDERS


def needs_pro(pid: str) -> bool:
    """True when this connection is behind the lock for the current user. A connection that was already saved keeps working."""
    if is_free_provider(pid) or is_pro():
        return False
    return not providers.is_configured(pid)


def check_provider(pid: str) -> None:
    """Raises ValueError (a message for the user) when a Pro-only connection is saved on the free plan."""
    if needs_pro(pid):
        title = providers.BY_ID[pid]["title"]
        link = f" Get Iris Pro: {UPGRADE_URL}" if UPGRADE_URL else ""
        raise ValueError(f"{title} is part of Iris Pro. The free plan includes Claude AI (Haiku 5.5) with your own key, Kraken, wallets and stocks & commodities. "
                         f"Paste your Pro license key under Connections to unlock the rest.{link}")


def check_feature(what: str) -> None:
    if not is_pro():
        link = f" Get Iris Pro: {UPGRADE_URL}" if UPGRADE_URL else ""
        raise ValueError(f"{what} is part of Iris Pro. Paste your Pro license key under Connections to unlock it.{link}")


def check_can_add() -> None:
    """Raises ValueError (a message for the user) when the free plan is full. Accounts already there are never removed."""
    if prefs.demo_on():
        return
    if is_pro():
        return
    if count_accounts() >= FREE_ACCOUNT_LIMIT:
        link = f" Get Iris Pro: {UPGRADE_URL}" if UPGRADE_URL else ""
        raise ValueError(f"The free plan connects up to {FREE_ACCOUNT_LIMIT} accounts (exchanges, wallets and stock accounts together). "
                         f"Iris Pro has no limit. Paste your Pro license key under Connections to unlock more.{link}")


# ---------- the hosted AI ----------
def hosted_client():
    """An Anthropic client that talks to the Pro server instead of Anthropic. The 'api key' is the license key."""
    import anthropic
    return anthropic.Anthropic(api_key=license_key(), base_url=PRO_URL + "/ai", max_retries=1, timeout=60.0, default_headers=_headers())


FREE_MODEL = "claude-haiku-5-5"      # the free plan chats with this fast, cheap model; Pro adds the advanced one
PRO_DEFAULT_MODEL = "claude-sonnet-5-5"


def own_key_model() -> str:
    """The model used with the person's own Claude key. Free plan: Haiku 5.5. Pro: their choice (default Sonnet 5.5)."""
    if not is_pro():
        return FREE_MODEL
    return providers.values("anthropic").get("model") or PRO_DEFAULT_MODEL


HOSTED_MODEL = "iris-pro"          # the server decides the real model


def explain_error(e: Exception) -> str | None:
    """Turn an error from the hosted AI into a sentence for the chat; None if it is not one of ours."""
    import anthropic
    if not isinstance(e, anthropic.APIStatusError):
        return None
    body = e.body if isinstance(e.body, dict) else {}
    msg = ""
    err = body.get("error")
    if isinstance(err, dict):
        msg = str(err.get("message") or "")
    code = getattr(e, "status_code", 0)
    if code in (401, 403):
        forget_cache_only()
        return msg or "Your Iris Pro license was not accepted. Check it under Connections."
    if code in (402, 429):
        forget_cache_only()                        # so the Connections card shows the new allowance (and the BUY MORE AI button)
        return msg or "The Iris AI allowance is used up for now. Buy more AI under Connections, or add your own Claude key to keep chatting."
    if code >= 500:
        return "The Iris AI service is not answering right now. Try again in a minute."
    return msg or None


def forget_cache_only() -> None:
    with _lock:
        _mem.update(t=0.0, fp="", v=None)
