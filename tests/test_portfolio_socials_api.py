import json
import sqlite3
import time
from contextlib import closing
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

import app as appmod
from iris import net, portfolio, socials, vault
from iris.config import PORTFOLIO_DB

client = TestClient(appmod.app, base_url="http://127.0.0.1:8765")


def put_snaps(rows):
    with closing(sqlite3.connect(PORTFOLIO_DB)) as c:
        c.execute("CREATE TABLE IF NOT EXISTS snaps(ts REAL PRIMARY KEY, accounts TEXT)")
        c.execute("CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT)")
        for ts, a in rows:
            c.execute("INSERT OR REPLACE INTO snaps VALUES (?,?)", (ts, json.dumps(a)))
        c.commit()


def test_pnl_new_account_counts_only_from_first_sighting():
    now = time.time()
    put_snaps([(now - 2 * 86400, {"ex:binance": 1000.0}), (now - 3600, {"ex:binance": 1100.0, "wallet:new": 500.0})])
    p = portfolio.compute_pnl({"ex:binance": 1200.0, "wallet:new": 600.0})
    # Binance 1000 -> 1200 (+200). The wallet's starting 500 is NOT profit; only its move 500 -> 600 (+100) counts.
    assert p["d7"]["usd"] == pytest.approx(300.0, abs=0.01) and p["d7"]["partial"] is True


def test_history_forward_fills_failed_account(monkeypatch):
    now = time.time()
    monkeypatch.setattr(portfolio, "sources", lambda: [("ex:a", "A", "exchange", "a", None), ("ex:b", "B", "exchange", "b", None)])
    put_snaps([(now - 3000, {"ex:a": 100.0, "ex:b": 50.0}), (now - 2000, {"ex:a": 110.0}), (now - 1000, {"ex:a": 120.0, "ex:b": 60.0})])
    pts = portfolio.history("1d")["points"]
    assert [p[1] for p in pts] == [150.0, 160.0, 180.0]          # B keeps its last known value instead of dipping to 0


def test_calendar_day_change():
    today = datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)
    y = today.timestamp() - 86400
    put_snaps([(y - 3600, {"ex:a": 100.0}), (y, {"ex:a": 110.0}), (today.timestamp() - 600, {"ex:a": 121.0}), (today.timestamp(), {"ex:a": 125.0})])
    cal = portfolio.calendar()
    assert cal["days"][today.strftime("%Y-%m-%d")]["usd"] == pytest.approx(15.0)    # 125 - 110 (end of yesterday)


def test_status_with_one_failing_account(monkeypatch, fake_prices):
    from iris import model
    ok = model.make_account("ex:ok", "OK", "exchange", "x", [model.holding("BTC", 1, "spot")])

    def boom():
        raise net.ApiError("HTTP 401: bad key SECRETKEYVALUE123")
    vault.save("zzz", {"k": "SECRETKEYVALUE123"})
    monkeypatch.setattr(portfolio, "sources", lambda: [("ex:ok", "OK", "exchange", "x", lambda: ok), ("ex:bad", "Bad", "exchange", "y", boom)])
    st = portfolio.status(force=True)
    assert st["total_usd"] == 60000 and st["incomplete"] is True
    bad = [a for a in st["accounts"] if a["id"] == "ex:bad"][0]
    assert bad["total_usd"] is None and "SECRETKEYVALUE123" not in bad["error"]


# ---------- API ----------
def test_api_never_returns_a_saved_secret():
    r = client.post("/api/connections/binance", json={"values": {"api_key": "PUBLICKEY1234567", "api_secret": "VERYSECRET7654321"}})
    assert r.status_code == 200
    text = json.dumps(client.get("/api/connections").json(), ensure_ascii=False)
    assert "VERYSECRET7654321" not in text and "PUBLICKEY1234567" not in text and "••••4321" in text
    b = [p for p in r.json()["providers"] if p["id"] == "binance"][0]
    assert b["locked"] and b["configured"]
    assert client.post("/api/connections/binance", json={"values": {"api_key": "x" * 12}}).status_code == 409   # locked
    assert client.post("/api/connections/binance/remove").status_code == 409
    assert client.post("/api/connections/binance/lock", json={"locked": False}).status_code == 200
    assert client.post("/api/connections/binance/remove").status_code == 200


def test_api_requires_all_required_fields():
    r = client.post("/api/connections/okx", json={"values": {"api_key": "onlykey123456"}})
    assert r.status_code == 400 and "Passphrase" in r.json()["detail"]


def test_api_rejects_foreign_origin_and_host():
    assert client.get("/api/status", headers={"origin": "https://evil.example"}).status_code == 403
    assert client.get("/api/status", headers={"host": "evil.example"}).status_code == 403


def test_wallet_api_rejects_private_key():
    r = client.post("/api/wallets", json={"name": "x", "address": "0x" + "ab" * 32, "chain": "evm"})
    assert r.status_code == 400 and "PRIVATE KEY" in r.json()["detail"]


def test_chat_without_key_uses_builtin_guide():
    r = client.post("/api/chat", json={"text": "how do I get started?"}).json()
    assert r["guide"] is True and "Try Demo Data" in r["reply"] and "Claude key" in r["note"]
    assert "Claude API key" in client.post("/api/chat", json={"text": "how do I add my claude key"}).json()["reply"]
    assert "Nothing is connected" in client.post("/api/chat", json={"text": "what's my total balance?"}).json()["reply"]
    assert "read-only" in client.post("/api/chat", json={"text": "is it safe, can it trade?"}).json()["reply"].lower()


def test_guide_reads_demo_numbers():
    client.post("/api/demo", json={"on": True})
    try:
        r = client.post("/api/chat", json={"text": "What's my total balance?"}).json()
        assert r["guide"] and "total balance is $" in r["reply"] and "demo data" in r["reply"].lower()
        assert "7 days" in client.post("/api/chat", json={"text": "How did I do this week?"}).json()["reply"]
    finally:
        client.post("/api/demo", json={"on": False})


def test_demo_mode_never_touches_snapshots():
    client.post("/api/demo", json={"on": True})
    try:
        st = client.get("/api/status").json()
        assert st["demo"] and st["total_usd"] > 0 and st["positions"]
        assert client.get("/api/history?range=1w").json()["points"]
        assert len(client.get("/api/socials").json()["accounts"]) == 5
    finally:
        client.post("/api/demo", json={"on": False})
    assert not PORTFOLIO_DB.exists()


# ---------- socials ----------
def test_social_handle_validation_and_lock():
    assert socials.add("Chan", "youtube", "mychannel")["handle"] == "@mychannel"
    assert socials.add("Disc", "discord", "https://discord.gg/abcDEF")["handle"] == "abcDEF"
    with pytest.raises(ValueError):
        socials.add("Bad", "instagram", "not-a-number")
    with pytest.raises(ValueError):
        socials.remove("Chan")


def test_youtube_reader_and_growth(monkeypatch):
    vault.save("youtube", {"api_key": "YTKEY123456789"})

    def fake_get(url, params=None, **kw):
        assert params["key"] == "YTKEY123456789"
        if url.endswith("/channels"):
            return {"items": [{"snippet": {"title": "Chan"}, "statistics": {"subscriberCount": "1500", "viewCount": "99999", "videoCount": "12"},
                               "contentDetails": {"relatedPlaylists": {"uploads": "UU1"}}}]}
        if url.endswith("/playlistItems"):
            return {"items": [{"contentDetails": {"videoId": "v1"}}]}
        return {"items": [{"id": "v1", "snippet": {"title": "<b>Hello</b>", "publishedAt": "2026-01-01T00:00:00Z"}, "statistics": {"viewCount": "10", "likeCount": "3", "commentCount": "1"}}]}
    monkeypatch.setattr(net, "get", fake_get)
    socials.add("Chan", "youtube", "@chan")
    # an old snapshot of 1400 followers 2 days ago -> +100 over 7 days
    import sqlite3 as s3
    from iris.config import SOCIALS_DB
    with closing(s3.connect(SOCIALS_DB)) as c:
        c.execute("CREATE TABLE IF NOT EXISTS snaps(ts REAL, acct TEXT, followers INTEGER, PRIMARY KEY(ts, acct))")
        c.execute("INSERT INTO snaps VALUES (?,?,?)", (time.time() - 2 * 86400, "Chan", 1400))
        c.commit()
    out = socials.read_all(force=True)[0]
    assert out["followers"] == 1500 and out["posts"][0]["likes"] == 3 and out["growth"]["d7"]["change"] == 100
    assert out["posts"][0]["title"] == "<b>Hello</b>"        # stored raw; the page escapes it when drawing


def test_social_error_is_scrubbed(monkeypatch):
    vault.save("telegram", {"bot_token": "123456:SECRETBOTTOKEN"})
    monkeypatch.setattr(net, "get", lambda *a, **k: (_ for _ in ()).throw(net.ApiError("HTTP 401 for bot123456:SECRETBOTTOKEN")))
    socials.add("Tg", "telegram", "@mychannel")
    out = socials.read_all(force=True)[0]
    assert out["followers"] is None and "SECRETBOTTOKEN" not in out["error"]


# ---------- AI loop (fake Anthropic client) ----------
def test_agent_tool_loop_and_no_key(monkeypatch, fake_prices):
    from types import SimpleNamespace as NS
    from iris import agent, model
    ok = model.make_account("ex:ok", "OK", "exchange", "x", [model.holding("BTC", 1, "spot")])
    monkeypatch.setattr(portfolio, "sources", lambda: [("ex:ok", "OK", "exchange", "x", lambda: ok)])

    calls = []

    class FakeMessages:
        def create(self, **kw):
            calls.append(kw)
            if len(calls) == 1:
                return NS(stop_reason="tool_use", content=[NS(type="tool_use", id="t1", name="get_portfolio", input={})])
            result = json.loads(kw["messages"][-1]["content"][0]["content"])
            return NS(stop_reason="end_turn", content=[NS(type="text", text=f"You have ${result['total_usd']:,.0f}.")])

    class FakeClient:
        def __init__(self, api_key):
            assert api_key == "sk-ant-test-0123456789"
            self.messages = FakeMessages()

    monkeypatch.setattr(agent.anthropic, "Anthropic", FakeClient)
    with pytest.raises(PermissionError):
        agent.Iris().ask("hi")                                  # no key saved yet
    vault.save("anthropic", {"api_key": "sk-ant-test-0123456789"})
    reply = agent.Iris().ask("what do I have?")
    assert reply == "You have $60,000." and calls[0]["model"] == "claude-sonnet-5-5"
    assert {t["name"] for t in calls[0]["tools"]} == {"get_portfolio", "get_holdings", "get_positions", "get_prices", "get_pnl_calendar", "get_socials", "get_market_pulse"}


def test_no_tool_can_move_money():
    from iris import tools
    forbidden = ("trade", "order", "transfer", "withdraw", "send", "swap", "buy", "sell")
    assert not [t["name"] for t in tools.SCHEMAS if any(w in t["name"] for w in forbidden)]


# ---------- help / readme / (i) windows ----------
def test_every_provider_has_help_with_steps():
    from iris import providers
    from iris.help_text import HELP
    for p in providers.PROVIDERS:
        h = HELP.get(p["id"])
        assert h and h["what"] and len(h["steps"]) >= 3, p["id"]
    assert HELP["wallets"]["steps"] and HELP["social_accounts"]["steps"]
    pub = client.get("/api/connections").json()
    assert all(x["help"] for x in pub["providers"]) and pub["help"]["wallets"]


def test_help_page_readme_and_docs_routes():
    page = client.get("/help")
    assert page.status_code == 200 and "readme.md" in page.text
    md = client.get("/readme.md")
    assert md.status_code == 200 and md.text.startswith("# IRIS")
    assert client.get("/docs/dashboard.png").status_code == 200


def test_sponsor_links_are_present():
    html = client.get("/").text
    for url in ("https://promo.chartinginteractive.io", "https://solanasniper.ai", "https://wicksync.io"):
        assert url in html
    assert "/help" in html


def test_launcher_has_no_fragile_shortcut_code_and_icon_exists():
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    bat = next(root.glob("LAUNCH IRIS*.bat")).read_bytes()
    assert b"\r\n" in bat and b"app.py" in bat and b"powershell" not in bat.lower()
    assert (root / "web" / "iris.ico").read_bytes()[:4] == b"\x00\x00\x01\x00"


def test_desktop_shortcut_creation_logic(monkeypatch, tmp_path):
    from iris import shortcut
    monkeypatch.setattr(shortcut, "desktop_dir", lambda: tmp_path / "no-desktop")
    monkeypatch.setattr(shortcut.sys, "platform", "linux")
    assert shortcut.create()["ok"] is False and shortcut.ensure() is None            # no Desktop folder: politely does nothing
    seen = {}
    monkeypatch.setattr(shortcut, "_win", lambda: True)
    monkeypatch.setattr(shortcut, "supported", lambda: True)
    monkeypatch.setattr(shortcut, "desktop_dir", lambda: tmp_path)
    monkeypatch.setattr(shortcut, "_via_vbscript", lambda *a: (False, "no cscript"))
    monkeypatch.setattr(shortcut, "_run", lambda script: (seen.setdefault("script", script), (True, ""))[1])
    r = shortcut.ensure()
    assert r and r["ok"] and "LAUNCH IRIS" in seen["script"] and "iris.ico" in seen["script"] and shortcut.MARK.exists()
    seen.clear()
    assert shortcut.ensure() is None and not seen                                      # only once per folder
    shortcut.MARK.unlink()


def test_shortcut_falls_back_to_plain_link_file(monkeypatch, tmp_path):
    from iris import shortcut
    monkeypatch.setattr(shortcut, "_win", lambda: True)
    monkeypatch.setattr(shortcut, "supported", lambda: True)
    monkeypatch.setattr(shortcut, "desktop_dir", lambda: tmp_path)
    monkeypatch.setattr(shortcut, "_run", lambda script: (False, "blocked by policy"))
    monkeypatch.setattr(shortcut, "_via_vbscript", lambda *a: (False, "no cscript"))
    r = shortcut.create()
    assert r["ok"] and "Iris.url" in r["message"]
    text = (tmp_path / "Iris.url").read_text(encoding="utf-8")
    assert text.startswith("[InternetShortcut]") and "URL=file:///" in text and "iris.ico" in text
    shortcut.MARK.unlink(missing_ok=True)
    # when everything fails the message lists every reason
    monkeypatch.setattr(shortcut, "_via_url_file", lambda *a: (False, "read-only desktop"))
    r = shortcut.create()
    assert not r["ok"] and "blocked by policy" in r["message"] and "read-only desktop" in r["message"]
    assert client.get("/api/status").json()["shortcut_error"].startswith("Could not add the desktop icon")
    assert client.post("/api/shortcut").json()["ok"] is False
    shortcut.LOG.unlink(missing_ok=True); shortcut.LAST = None


def test_clixml_noise_is_cleaned():
    from iris import shortcut
    raw = '#< CLIXML <Objs Version="1.1.0.1"><Obj S="progress"><AV>Preparing modules for first use.</AV></Obj><S S="Error">Access is denied._x000D__x000A_</S></Objs>'
    assert shortcut._clean(raw) == "Access is denied."
    assert shortcut._clean('#< CLIXML <Objs><Obj S="progress"><AV>Preparing modules</AV></Obj></Objs>') == ""


def test_guide_returns_focus_for_highlighting():
    from iris import guide
    assert guide.answer_focus("how do I get started?", {})[1] == "start"
    assert guide.answer_focus("is it safe?", {})[1] is None
    assert client.post("/api/chat", json={"text": "which exchanges can I connect?"}).json()["focus"] == "connect"



def test_markets_follow_holdings_else_top_coins(fake_prices):
    st = {"holdings": [{"symbol": "USDT"}, {"symbol": "BTC"}, {"symbol": "SOL"}, {"symbol": "ETH"}]}
    assert portfolio.watch_symbols(st) == ["BTC", "SOL", "ETH"]           # stablecoins skipped, order = biggest first
    assert portfolio.watch_symbols({"holdings": []}) == portfolio.TOP_COINS and len(portfolio.TOP_COINS) == 8
    assert portfolio.watch_symbols({"holdings": [{"symbol": "USDC"}]}) == portfolio.TOP_COINS


def test_live_layer_is_served_and_wired():
    assert "/static/live.js" in client.get("/").text and 'id="alBtn"' in client.get("/").text
    js = client.get("/static/live.js").text
    for word in ("startupBriefing", "liquidation", "followers", "morning briefing"):
        assert word.lower() in js.lower()


def test_themes_defined_in_css_and_picker():
    css = client.get("/static/style.css").text
    for t in ("matrix", "solana", "tokyo", "violet", "synth", "bitcoin", "red", "carbon"):
        assert f"html[data-theme={t}]" in css
    js = client.get("/static/app.js").text
    assert "applyTheme" in js and "IRIS CYAN" in js and 'id="themes"' in client.get("/").text


def test_server_voice_fallback(monkeypatch):
    from iris import say
    started = {}

    class FakeProc:
        returncode = 0
        def poll(self): return None
        def terminate(self): started["stopped"] = True
        def communicate(self, timeout=None): return b"", b""

    def fake_popen(cmd, env=None, **kw):
        started.update(cmd=cmd, text=env["IRIS_SAY_TEXT"])
        return FakeProc()
    monkeypatch.setattr(say, "supported", lambda: True)
    monkeypatch.setattr(say.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(say.os, "name", "posix", raising=False)
    monkeypatch.setattr(say.shutil, "which", lambda prog: "/usr/bin/say" if prog == "say" else None)
    assert client.post("/api/say", json={"text": "Hi,  I'm   Iris.\n It's me"}).json() == {"ok": True}
    assert started["text"] == "Hi, I'm Iris. It's me" and started["cmd"][0].endswith("say") and started["text"] not in started["cmd"][:1]
    assert client.post("/api/say/stop").json()["ok"] and started.get("stopped")
    assert client.post("/api/say", json={"text": "x" * 2000}).status_code == 422          # too long is refused
    assert "can_say" in client.get("/api/status").json()


def test_default_theme_is_solana():
    assert 'localStorage.getItem("nx_theme2")||"solana"' in client.get("/").text
    assert "'solana'" in client.get("/static/app.js").text


def test_intro_plays_automatically_once_per_start():
    js = client.get("/static/app.js").text
    assert "nx_intro_boot" in js and "speakIntro();" in js and client.get("/api/status").json()["boot"] > 0


def test_launcher_name_is_plain_ascii_and_recreates_icon_when_renamed(monkeypatch, tmp_path):
    from iris import shortcut
    monkeypatch.setattr(shortcut, "_win", lambda: True)
    assert shortcut.launcher().name == shortcut.LAUNCHER_NAME and shortcut.LAUNCHER_NAME.isascii()
    monkeypatch.setattr(shortcut, "supported", lambda: True)
    monkeypatch.setattr(shortcut, "desktop_dir", lambda: tmp_path)
    monkeypatch.setattr(shortcut, "_run", lambda script: (True, ""))
    (tmp_path / "Iris.url").write_text("old broken icon")
    shortcut.MARK.write_text(f"{shortcut.ROOT}|LAUNCH IRIS (old name).bat")      # marker from an older launcher name
    r = shortcut.ensure()
    assert r and r["ok"] and not (tmp_path / "Iris.url").exists()                 # re-made, stale icon of the other kind removed
    shortcut.MARK.unlink()


def test_linux_voice_programs(monkeypatch):
    from iris import say
    monkeypatch.setattr(say.os, "name", "posix", raising=False)
    monkeypatch.setattr(say.shutil, "which", lambda p: "/usr/bin/espeak-ng" if p == "espeak-ng" else None)
    assert say.supported() and say._unix_cmd("hi") == ["/usr/bin/espeak-ng", "--", "hi"]
    monkeypatch.setattr(say.shutil, "which", lambda p: "/usr/bin/spd-say" if p == "spd-say" else None)
    assert say._unix_cmd("hi")[:2] == ["/usr/bin/spd-say", "-w"]
    monkeypatch.setattr(say.shutil, "which", lambda p: None)
    assert not say.supported() and not say.speak("hello")          # no voice installed: quietly says no


@pytest.mark.parametrize("plat,fname,needle", [("darwin", "Iris.command", "exec bash start.sh"), ("linux", "Iris.desktop", "Terminal=true")])
def test_unix_desktop_icon(monkeypatch, tmp_path, plat, fname, needle):
    from iris import shortcut
    desk = tmp_path / "My Desktop"
    desk.mkdir()
    monkeypatch.setattr(shortcut.os, "name", "posix", raising=False)
    monkeypatch.setattr(shortcut.sys, "platform", plat)
    monkeypatch.setattr(shortcut, "desktop_dir", lambda: desk)
    monkeypatch.setattr(shortcut, "MARK", tmp_path / ".shortcut")
    monkeypatch.setattr(shortcut, "LOG", tmp_path / "shortcut.log")
    monkeypatch.setattr(shortcut.subprocess, "run", lambda *a, **k: None)
    assert shortcut.supported()
    r = shortcut.create()
    assert r["ok"], r
    f = desk / fname
    assert needle in f.read_text() and f.stat().st_mode & 0o100          # executable
    assert shortcut.ensure() is None                                      # already done: not repeated
    assert (shortcut.ROOT / "web" / "iris.png").read_bytes()[:4] == b"\x89PNG"
    if plat == "linux":
        assert "iris.png" in f.read_text() and "start.sh" in f.read_text()


def test_linux_without_desktop_folder_gets_no_icon(monkeypatch, tmp_path):
    from iris import shortcut
    monkeypatch.setattr(shortcut.os, "name", "posix", raising=False)
    monkeypatch.setattr(shortcut.sys, "platform", "linux")
    monkeypatch.setattr(shortcut, "desktop_dir", lambda: tmp_path / "nothing")
    assert not shortcut.supported() and shortcut.ensure() is None


def test_donation_link_only_after_something_is_connected(monkeypatch):
    from iris import donate
    assert donate.ADDRESS == "39oAW7hrufjNi6tm7bS35n3uRaxavV4hMD19y6UKyusU"
    assert not donate.available({"demo": False, "configured": False, "has_socials": False, "ai_ready": False})   # nothing connected
    assert donate.available({"demo": True, "configured": True, "has_socials": True, "ai_ready": False})          # also in demo mode, so it can be tried
    assert donate.available({"demo": False, "configured": True}) and donate.available({"demo": False, "ai_ready": True})
    monkeypatch.setattr(appmod.donate, "available", lambda st: True)
    assert client.get("/api/status").json()["donate"] == donate.ADDRESS
    monkeypatch.setattr(appmod.donate, "available", lambda st: False)
    assert client.get("/api/status").json()["donate"] is None


def test_donation_blockhash_endpoint(monkeypatch):
    from iris.chains import solana
    monkeypatch.setattr(solana, "rpc", lambda m, p: {"value": {"blockhash": "4vJ9JU1bJJE96FWSJKvHsmmFADCg4gpZQff4P3bkLKi", "lastValidBlockHeight": 5}})
    assert client.get("/api/donate/blockhash").json()["blockhash"].startswith("4vJ9")
    def boom(m, p): raise net.ApiError("network error")
    monkeypatch.setattr(solana, "rpc", boom)
    assert client.get("/api/donate/blockhash").status_code == 502
    assert client.get("/api/donate/blockhash", headers={"host": "evil.example"}).status_code == 403          # still local-only
    html = client.get("/").text
    assert 'id="donBtn"' in html and "hidden" in html.split('id="donBtn"')[1][:260] and "/static/donate.js" in html
    js = client.get("/static/donate.js").text
    assert "39oAW7" not in js and "ST.donate" not in js and "s.donate" in js          # the address comes from the server, never typed in the page


def test_cosmic_orb_is_wired_with_classic_fallback():
    html = client.get("/").text
    assert html.index("/static/orb3d.js") < html.index("/static/orb.js") and 'id="orbBtn"' in html
    cosmic = client.get("/static/orb3d.js").text
    assert "window.NX = { cosmic: true" in cosmic and "kick(n)" in cosmic and "webglcontextlost" in cosmic and "nx_orb" in cosmic
    assert "float flat" not in cosmic                                  # 'flat' is a reserved word in GLSL and breaks the shader
    classic = client.get("/static/orb.js").text
    assert "window.NX.cosmic) return" in classic and "window.NX = { busy" in classic          # the classic orb stays as the fallback / alternative
    assert "#fxg" in client.get("/static/style.css").text


def test_old_nexus_desktop_icons_are_removed_when_the_iris_icon_is_made(monkeypatch, tmp_path):
    from iris import shortcut
    desk = tmp_path / "Desktop"; desk.mkdir()
    for n in shortcut.LEGACY:
        (desk / n).write_text("old")
    (desk / "keep.txt").write_text("mine")
    monkeypatch.setattr(shortcut, "_win", lambda: True)
    monkeypatch.setattr(shortcut, "supported", lambda: True)
    monkeypatch.setattr(shortcut, "desktop_dir", lambda: desk)
    monkeypatch.setattr(shortcut, "MARK", tmp_path / ".shortcut")
    monkeypatch.setattr(shortcut, "LOG", tmp_path / "shortcut.log")
    monkeypatch.setattr(shortcut, "_run", lambda script: (True, ""))
    assert shortcut.create()["ok"]
    assert not any((desk / n).exists() for n in shortcut.LEGACY) and (desk / "keep.txt").exists()


def test_app_is_called_iris_everywhere():
    import re
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    skip = {".venv", "__pycache__", "tests", ".pytest_cache"}
    bad = [str(p.relative_to(root)) for p in root.rglob("*") if p.is_file() and not (skip & set(p.parts)) and p.suffix not in (".png", ".ico", ".db")
           and re.search(r"nexus", p.read_text(encoding="utf-8", errors="ignore"), re.I) and p.name != "shortcut.py"]
    assert not bad, bad
    assert "Iris" in client.get("/").text and "<title>Iris" in client.get("/").text


def test_connections_button_pulses_in_demo_mode():
    from iris import shortcut
    css = (shortcut.ROOT / "web" / "style.css").read_text(encoding="utf-8")
    js = (shortcut.ROOT / "web" / "app.js").read_text(encoding="utf-8")
    assert "#connBtn.cta" in css and "ctaBeat" in css
    assert "classList.toggle('cta', !!s.demo)" in js


def test_closed_position_alert_states_result():
    from iris import shortcut
    js = (shortcut.ROOT / "web" / "live.js").read_text(encoding="utf-8")
    assert "has been closed" in js and "closedTxt(" in js and "demo-close" in js


def test_live_layer_follows_the_data():
    """The voice and the question bubbles react to changing data, and answer from the page itself while there is no Claude key."""
    from pathlib import Path
    web = Path(__file__).resolve().parent.parent / "web"
    live, app, mkt = [(web / n).read_text(encoding="utf-8") for n in ("live.js", "app.js", "market.js")]
    for needle in ("local, onMarkets, onMarket", "function ambient", "function extraWatch", "const OBS = ["):
        assert needle in live
    assert "LIVE.local(text)" in app and "LIVE.onMarkets(MKTS)" in app and "CALD = c" in app
    assert "LIVE.onMarket(m)" in mkt
    assert "const CAP = " in app and "CAP.start(clean)" in app and "CAP.bound(" in app      # the caption is typed out as Iris speaks
    assert "CAP.arm(clean)" in app and "const SPEECH = " in app and "SPEECH.f >= ends[k]" in app     # caption starts at once; the highlight follows the voice


# ---------------------------------------------------------------- inner circle (paid Telegram access)
REF = "4vJ9JU1bJJE96FWSJKvHsmmFADCg4gpZQff4P3bkLKi"
REC = "39oAW7hrufjNi6tm7bS35n3uRaxavV4hMD19y6UKyusU"


def _fake_server(monkeypatch, paid_after=1, link="https://t.me/+ABCDEF"):
    from iris import inner
    calls = []
    monkeypatch.setattr(inner, "API", "https://inner.example.workers.dev")

    def fake(method, url, **kw):
        calls.append((url, kw.get("json")))
        if url.endswith("/start"):
            return {"reference": REF, "nonce": "abc.def", "recipient": REC, "lamports": 200000000, "username": kw["json"]["username"]}
        n = sum(1 for u, _ in calls if u.endswith("/check"))
        return {"paid": True, "link": link} if n >= paid_after else {"paid": False}
    monkeypatch.setattr(inner.net, "request", fake)
    return calls


def test_inner_circle_payment_flow_and_saved_link(monkeypatch):
    from iris import inner
    monkeypatch.setattr(inner, "API", "")                                       # as if no server address were set
    assert not inner.configured() and client.get("/api/inner").json()["configured"] is False
    assert client.post("/api/inner/start", json={"username": "@Buyer_One"}).status_code == 400            # server address not set yet
    calls = _fake_server(monkeypatch, paid_after=2)
    assert client.get("/api/status").json()["inner"]["configured"] is True
    assert client.post("/api/inner/start", json={"username": "no"}).status_code == 400                      # not a Telegram username
    r = client.post("/api/inner/start", json={"username": "@Buyer_One"}).json()
    assert r["reference"] == REF and r["recipient"] == REC and r["lamports"] == 200000000 and r["sol"] == "0.2" and r["username"] == "Buyer_One"
    assert calls[0][1] == {"username": "Buyer_One"}                              # only the username goes to the server (no @)
    assert client.post("/api/inner/check").json()["paid"] is False
    done = client.post("/api/inner/check").json()
    assert done["paid"] and done["link"] == "https://t.me/+ABCDEF"
    assert client.get("/api/inner").json()["link"] == "https://t.me/+ABCDEF"                                  # kept so it can be shown again
    n = len(calls); assert client.post("/api/inner/check").json()["link"]; assert len(calls) == n          # no new server call once paid
    client.post("/api/inner/reset"); assert client.get("/api/inner").json()["link"] is None


def test_inner_circle_refuses_odd_server_answers(monkeypatch):
    from iris import inner
    monkeypatch.setattr(inner, "API", "https://inner.example.workers.dev")
    bad = [{"reference": REF, "nonce": "n", "recipient": REC, "lamports": 9_000_000_000}, {"reference": "x", "nonce": "n", "recipient": REC, "lamports": 1},
           {"reference": REF, "nonce": "n", "recipient": "not an address", "lamports": 1}, {}]
    for answer in bad:
        monkeypatch.setattr(inner.net, "request", lambda m, u, _a=answer, **kw: _a)
        assert client.post("/api/inner/start", json={"username": "Buyer_One"}).status_code == 400
    _fake_server(monkeypatch, link="http://evil.example/x")
    client.post("/api/inner/start", json={"username": "Buyer_One"})
    assert client.post("/api/inner/check").json()["link"] is None                # only real Telegram links are accepted
    assert client.post("/api/inner/check", headers={"host": "evil.example"}).status_code == 403


def test_inner_circle_page_wiring():
    html = client.get("/").text
    assert 'id="innerBtn"' in html and "JOIN INNER CIRCLE" in html and 'id="inner"' in html and "/static/inner.js" in html
    assert html.index('id="innerBtn"') < html.index('id="connBtn"')                # next to README and Connections
    js, don = client.get("/static/inner.js").text, client.get("/static/donate.js").text
    assert "DONATE.payTo(" in js and "/api/inner/start" in js and "/api/inner/check" in js
    assert "function buildTx(from, to, blockhash, lam, ref)" in don and "async function payTo(" in don
