"""Iris: run `python app.py` and your browser opens the dashboard at http://127.0.0.1:8765

Everything runs on YOUR computer. The server only listens on 127.0.0.1 and rejects requests from other websites.
Don't expose it to the internet.
"""
import hmac
import os
import socket
import sys
import threading
import time
import webbrowser

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from iris import __version__, connections, donate, guide, inner, market, portfolio, pro, prefs, prices, providers, say, shortcut, socials, stocks_store, vault
from iris.chains import wallets_store
from iris.config import DATA_DIR, PACKAGED, ROOT, WEB_DIR, import_data, import_legacy_if_new
from iris.help_text import HELP


def _free_port(start: int = 8765) -> int:
    for port in range(start, start + 20):
        with socket.socket() as sk:
            sk.settimeout(0.4)
            if sk.connect_ex(("127.0.0.1", port)) != 0:
                return port
    return start


BOOT = int(time.time())          # changes at every start, so the welcome can play once per start
PORT = int(os.getenv("IRIS_PORT") or _free_port())
ALLOWED_HOSTS = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}
ALLOWED_ORIGINS = {f"http://{h}" for h in ALLOWED_HOSTS}
# Desktop app: the launcher gives the window a secret that other programs and other Windows users on this PC don't have.
TOKEN = os.getenv("IRIS_TOKEN", "").strip()
COOKIE = "iris_t"

app = FastAPI(title="Iris", version=__version__, docs_url=None, redoc_url=None, openapi_url=None)


@app.middleware("http")
async def local_only(request: Request, call_next):
    """The API exposes balances and chat. Refuse other websites (CSRF) and DNS-rebinding tricks."""
    if TOKEN and request.url.path == "/" and hmac.compare_digest(request.query_params.get("t", ""), TOKEN) \
            and request.headers.get("host") in ALLOWED_HOSTS:
        r = RedirectResponse("/", status_code=303)          # hand the window its cookie, then drop the token from the address
        r.set_cookie(COOKIE, TOKEN, httponly=True, samesite="strict", path="/")
        return r
    if request.url.path.startswith("/api/"):
        origin = request.headers.get("origin")
        if request.headers.get("host") not in ALLOWED_HOSTS or (origin and origin not in ALLOWED_ORIGINS):
            return JSONResponse({"detail": "forbidden"}, status_code=403)
        if TOKEN and not hmac.compare_digest(request.cookies.get(COOKIE, ""), TOKEN):
            return JSONResponse({"detail": "forbidden"}, status_code=403)
    resp = await call_next(request)
    resp.headers["Cache-Control"] = "no-store"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "no-referrer"
    return resp


def _bad(e: Exception, code: int = 400):
    raise HTTPException(status_code=code, detail=vault.scrub(str(e)))


# ---------------- pages ----------------
@app.get("/")
def index():
    return FileResponse(WEB_DIR / "index.html")


app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
app.mount("/docs", StaticFiles(directory=ROOT / "docs"), name="docs")


@app.get("/help")
def help_page():
    """The README, shown inside the app."""
    return FileResponse(WEB_DIR / "help.html")


@app.get("/readme.md")
def readme_md():
    return FileResponse(ROOT / "README.md", media_type="text/markdown; charset=utf-8")


# ---------------- dashboard data ----------------
@app.get("/api/status")
def status(force: bool = False):
    st = dict(portfolio.status(force=force))
    st["ai_ready"] = providers.is_configured("anthropic") or pro.ai_ready()
    st["ai_source"] = "own" if providers.is_configured("anthropic") else ("pro" if pro.ai_ready() else "none")     # which AI answers the chat
    st["pro"] = {k: v for k, v in pro.cached_status().items() if k in ("plan", "active", "offline")}
    st["has_socials"] = bool(socials.load()) or st.get("demo", False)
    st["can_shortcut"] = shortcut.supported()
    st["can_say"] = say.supported()
    st["say_error"] = say.LAST_ERROR
    st["boot"] = BOOT
    vault._load()
    st["vault_error"] = vault.PROBLEM["message"] or None
    st["donate"] = donate.ADDRESS if donate.available(st) else None
    st["inner"] = inner.info()
    st["shortcut_error"] = shortcut.LAST["message"] if shortcut.LAST and not shortcut.LAST["ok"] else None
    return st


@app.get("/api/history")
def history(range: str = "1d"):
    try:
        return portfolio.history(range)
    except ValueError as e:
        _bad(e)


@app.get("/api/calendar")
def calendar(month: str = ""):
    return portfolio.calendar(month or None)


@app.get("/api/markets")
def markets():
    if prefs.demo_on():
        from iris import demo
        return {"markets": demo.markets()}
    rows = prices.markets(portfolio.watch_symbols(portfolio.status()))
    return {"markets": rows or prices.markets(portfolio.TOP_COINS)}      # holdings with no public market -> show the top coins instead


@app.get("/api/socials")
def socials_list(force: bool = False):
    return {"accounts": socials.read_all(force=force)}


_market_cache = {"t": 0.0, "v": None}
_market_lock = threading.Lock()


@app.get("/api/market")
def market_pulse():
    """News, data releases, calendar and mood from free public sources. Kept for 20 seconds so several tabs do not hammer the feeds."""
    with _market_lock:
        if _market_cache["v"] is None or time.time() - _market_cache["t"] > 20:
            try:
                _market_cache["v"] = market.pulse()
            except Exception as e:  # noqa: BLE001 - the dashboard must keep working without it
                return {"error": vault.scrub(f"{type(e).__name__}: {e}")[:160]}
            _market_cache["t"] = time.time()
        return _market_cache["v"]


class Reset(BaseModel):
    confirm: bool = False


@app.post("/api/reset")
def reset(body: Reset):
    if not body.confirm:
        _bad(ValueError("confirm required"))
    portfolio.reset()
    return {"ok": True}


# ---------------- connections (keys) ----------------
def _connections_payload() -> dict:
    return {
        "providers": [{**providers.public_view(p["id"]), "pro_only": not pro.is_free_provider(p["id"]), "needs_pro": pro.needs_pro(p["id"])}
                      for p in providers.PROVIDERS],
        "wallets": wallets_store.load(), "chains": wallets_store.CHAINS, "evm_networks": wallets_store.EVM_NETWORKS,
        "default_evm": wallets_store.DEFAULT_EVM,
        "social_accounts": socials.load(), "platforms": {k: {"label": v["label"], "handle": v["handle"], "needs_key": v["needs_key"],
                                                            "key_ready": socials.configured(k)} for k, v in socials.PLATFORMS.items()},
        "stock_accounts": [{**a, "text": stocks_store.as_text(a)} for a in stocks_store.load()],
        "pro": pro.public_view(),
        "demo": prefs.demo_on(), "help": {"wallets": HELP["wallets"], "social_accounts": HELP["social_accounts"]},
    }


@app.get("/api/connections")
def connections_list():
    return _connections_payload()


class Values(BaseModel):
    values: dict[str, str] = Field(default_factory=dict)


@app.post("/api/connections/{pid}")
def connection_save(pid: str, body: Values):
    if pid not in providers.BY_ID:
        _bad(KeyError("unknown connection"), 404)
    allowed = {f["key"] for f in providers.BY_ID[pid]["fields"]}
    clean = {k: v for k, v in body.values.items() if k in allowed and isinstance(v, str) and len(v) <= 2000}
    if providers.BY_ID[pid]["group"] == "exchange" and not providers.is_configured(pid):
        try:
            pro.check_provider(pid)       # only Binance and Bybit are free
            pro.check_can_add()           # the free plan connects up to 5 accounts
        except ValueError as e:
            _bad(e, 402)
    if providers.BY_ID[pid]["group"] != "exchange":
        try:
            pro.check_provider(pid)       # socials and advanced keys are Pro
        except ValueError as e:
            _bad(e, 402)
    merged = {**vault.get(pid), **{k: v.strip() for k, v in clean.items() if v.strip()}}
    missing = [f["label"] for f in providers.BY_ID[pid]["fields"] if f["required"] and not merged.get(f["key"])]
    if missing and not vault.is_locked(pid):
        _bad(ValueError("Please fill in: " + ", ".join(missing)))
    try:
        vault.save(pid, clean, lock=True)
    except PermissionError as e:
        _bad(e, 409)
    portfolio._status_cache["t"] = 0
    if pid == "pro":
        pro.refresh()                     # check the license right away, so the card shows the result
    return _connections_payload()


class Lock(BaseModel):
    locked: bool


@app.post("/api/connections/{pid}/lock")
def connection_lock(pid: str, body: Lock):
    try:
        vault.set_locked(pid, body.locked)
    except KeyError as e:
        _bad(e, 404)
    return _connections_payload()


@app.post("/api/connections/{pid}/remove")
def connection_remove(pid: str):
    try:
        vault.remove(pid)
    except PermissionError as e:
        _bad(e, 409)
    portfolio._status_cache["t"] = 0
    if pid == "pro":
        pro.forget()
    return _connections_payload()


@app.post("/api/connections/{pid}/test")
def connection_test(pid: str):
    try:
        return connections.test(pid)
    except KeyError as e:
        _bad(e, 404)


# ---------------- wallets ----------------
class WalletIn(BaseModel):
    name: str
    address: str
    chain: str
    networks: list[str] = Field(default_factory=list)


class Named(BaseModel):
    name: str


class NamedLock(BaseModel):
    name: str
    locked: bool


def _change(fn):
    try:
        fn()
    except ValueError as e:
        _bad(e)
    portfolio._status_cache["t"] = 0
    return _connections_payload()


def _change_capped(fn):
    """Like _change, but a new account must fit the plan (the free plan connects up to 5)."""
    try:
        pro.check_can_add()
    except ValueError as e:
        _bad(e, 402)
    return _change(fn)


@app.post("/api/wallets")
def wallet_add(b: WalletIn):
    return _change_capped(lambda: wallets_store.add(b.name, b.address, b.chain, b.networks))


@app.post("/api/wallets/lock")
def wallet_lock(b: NamedLock):
    return _change(lambda: wallets_store.set_locked(b.name, b.locked))


@app.post("/api/wallets/remove")
def wallet_remove(b: Named):
    return _change(lambda: wallets_store.remove(b.name))


# ---------------- social accounts ----------------
class SocialIn(BaseModel):
    name: str
    platform: str
    handle: str


@app.post("/api/social-accounts")
def social_add(b: SocialIn):
    def go():
        pro.check_feature("Tracking social accounts")
        socials.add(b.name, b.platform, b.handle)
    return _change(go)


@app.post("/api/social-accounts/lock")
def social_lock(b: NamedLock):
    return _change(lambda: socials.set_locked(b.name, b.locked))


@app.post("/api/social-accounts/remove")
def social_remove(b: Named):
    def go():
        socials.remove(b.name)
        socials.forget(b.name)
    return _change(go)


# ---------------- stocks and commodities (typed in by hand) ----------------
class StockIn(BaseModel):
    name: str
    text: str = Field(max_length=4000)


@app.post("/api/stocks")
def stock_add(b: StockIn):
    return _change_capped(lambda: stocks_store.add(b.name, b.text))


@app.post("/api/stocks/update")
def stock_update(b: StockIn):
    return _change(lambda: stocks_store.update_items(b.name, b.text))


@app.post("/api/stocks/lock")
def stock_lock(b: NamedLock):
    return _change(lambda: stocks_store.set_locked(b.name, b.locked))


@app.post("/api/stocks/remove")
def stock_remove(b: Named):
    return _change(lambda: stocks_store.remove(b.name))


# ---------------- Iris Pro ----------------
@app.get("/api/pro")
def pro_status():
    return pro.public_view()


@app.post("/api/pro/refresh")
def pro_refresh():
    pro.refresh()
    return pro.public_view()


# ---------------- demo + chat ----------------
class Demo(BaseModel):
    on: bool


@app.post("/api/demo")
def demo_toggle(b: Demo):
    prefs.set_value("demo", b.on)
    portfolio._status_cache["t"] = 0
    return {"demo": b.on}


class Chat(BaseModel):
    text: str


_agent = None
_chat_lock = threading.Lock()


@app.post("/api/chat")
def chat(body: Chat):
    global _agent
    text = body.text.strip()[:2000]
    if not text:
        _bad(ValueError("empty"))
    from iris.agent import Iris
    with _chat_lock:
        try:
            _agent = _agent or Iris()
            return {"reply": _agent.ask(text)}
        except pro.ProError as e:
            return {"reply": str(e), "error": True}
        except PermissionError:
            # no Claude key yet: the built-in guide explains the app and answers simple questions (free, offline)
            reply, focus = guide.answer_focus(text, portfolio.status())
            return {"reply": reply, "guide": True, "note": guide.NOTE, "focus": focus}
        except Exception as e:  # noqa: BLE001 - show the problem in the page instead of a blank screen
            msg = vault.scrub(str(e))
            hint = " Check your Claude API key under Connections." if any(w in msg.lower() for w in ("auth", "api_key", "401", "invalid x-api-key")) else ""
            return {"reply": f"I hit a problem ({type(e).__name__}).{hint}", "error": True}


class SayIn(BaseModel):
    text: str = Field(max_length=1500)


@app.post("/api/say")
def say_text(b: SayIn):
    return {"ok": say.speak(b.text)}


@app.post("/api/say/stop")
def say_stop():
    say.stop()
    return {"ok": True}


@app.post("/api/shortcut")
def make_shortcut():
    return shortcut.create()


@app.get("/api/donate/blockhash")
def donate_blockhash():
    try:
        return donate.blockhash()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=vault.scrub(str(e)) or "could not reach the Solana network")


class InnerStart(BaseModel):
    username: str = Field(max_length=64)


@app.get("/api/inner")
def inner_info():
    return inner.info()


@app.post("/api/inner/start")
def inner_start(b: InnerStart):
    try:
        return inner.start(b.username)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=vault.scrub(str(e)) or "could not start")


@app.post("/api/inner/check")
def inner_check():
    try:
        return inner.check()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=vault.scrub(str(e)) or "could not check the payment")


@app.post("/api/inner/reset")
def inner_reset():
    inner.reset()
    return {"ok": True}


@app.get("/api/health")
def health():
    return {"ok": True, "version": __version__}


def _cli() -> bool:
    """`python app.py --import-data "<old data folder>"` copies an older data folder in, then exits."""
    if "--import-data" not in sys.argv:
        return False
    i = sys.argv.index("--import-data")
    if i + 1 >= len(sys.argv):
        print('Usage: python app.py --import-data "<folder>"')
        return True
    try:
        res = import_data(sys.argv[i + 1])
    except (OSError, ValueError) as e:
        print(f"Could not import: {e}")
        return True
    print(f"Copied into {DATA_DIR}: {', '.join(res['copied']) or 'nothing'}")
    if res["skipped"]:
        print(f"Kept what was already there (not overwritten): {', '.join(res['skipped'])}")
    return True


def _quit_when_window_closes() -> None:
    """Desktop app: the window keeps our stdin open. When it closes (or crashes) stdin ends and Iris stops with it."""
    def watch():
        try:
            while sys.stdin.buffer.read(4096):
                pass
        except Exception:
            pass
        os._exit(0)
    threading.Thread(target=watch, daemon=True).start()


if __name__ == "__main__":
    for _s in ("stdout", "stderr"):
        if getattr(sys, _s) is None:         # a windowed build has no console; printing must not crash
            setattr(sys, _s, open(os.devnull, "w"))
    if _cli():
        sys.exit(0)
    if os.getenv("IRIS_WATCH_STDIN"):
        _quit_when_window_closes()
    moved = import_legacy_if_new()
    if moved and moved["copied"]:
        print(f"Brought your earlier data into {DATA_DIR}")
    if PORT != 8765 and not os.getenv("IRIS_PORT"):
        print(f"Note: port 8765 is in use, so Iris is using port {PORT}.")
    if not os.getenv("NO_BROWSER") and not PACKAGED:
        threading.Timer(1.5, lambda: webbrowser.open(f"http://127.0.0.1:{PORT}")).start()
    sc = None if PACKAGED else shortcut.ensure()     # Windows: put a "Iris" icon on the Desktop (once); the installer does that itself
    if sc:
        print(sc["message"])
    print(f"Iris is running: http://127.0.0.1:{PORT}   (press Ctrl+C to stop)")
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
