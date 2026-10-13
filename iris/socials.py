"""Social accounts: followers, growth and recent post likes/views.

Accounts are listed in data/socials.json (public handles only). Credentials live in the vault (one per platform).
Supported: YouTube, Instagram (Business/Creator), X, Telegram (channel member count), Discord (invite code, no key).
Snapshots of the follower counts are kept in data/socials.db so growth over 24h / 7d / 30d can be shown.
"""
import json
import os
import re
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from urllib.parse import quote

from iris import net, prefs, providers, vault
from iris.config import SOCIALS_DB, SOCIALS_FILE
from iris.model import clean_symbol, f

PLATFORMS = {
    "youtube": {"label": "YouTube", "handle": "Channel @handle (or channel ID UC...)", "needs_key": True},
    "instagram": {"label": "Instagram", "handle": "Numeric Instagram user id (Business/Creator)", "needs_key": True},
    "x": {"label": "X", "handle": "Username without @", "needs_key": True},
    "telegram": {"label": "Telegram", "handle": "@channelname", "needs_key": True},
    "discord": {"label": "Discord", "handle": "Invite code (discord.gg/CODE)", "needs_key": False},
}
HANDLE_RE = {
    "youtube": re.compile(r"^(@[A-Za-z0-9._\-]{3,60}|UC[A-Za-z0-9_\-]{22})$"),
    "instagram": re.compile(r"^\d{5,20}$"),
    "x": re.compile(r"^[A-Za-z0-9_]{1,15}$"),
    "telegram": re.compile(r"^@[A-Za-z][A-Za-z0-9_]{3,31}$"),
    "discord": re.compile(r"^[A-Za-z0-9\-]{2,32}$"),
}
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.\-]{0,23}$")
MAX_ACCOUNTS = 20
CACHE_TTL = 300          # seconds between live reads of one account
SNAP_GAP = 1800          # seconds between saved follower snapshots
_lock = threading.RLock()
_cache: dict = {}


# ---------- the list of tracked accounts ----------
def load() -> list[dict]:
    with _lock:
        try:
            items = json.loads(SOCIALS_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
    return [{"name": str(i["name"]), "platform": i["platform"], "handle": str(i["handle"]), "locked": bool(i.get("locked", True))}
            for i in (items if isinstance(items, list) else [])
            if isinstance(i, dict) and i.get("platform") in PLATFORMS and i.get("name") and i.get("handle")]


def _save(items: list[dict]) -> None:
    tmp = SOCIALS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(items, indent=2), encoding="utf-8")
    os.replace(tmp, SOCIALS_FILE)


def clean_handle(platform: str, handle: str) -> str:
    h = (handle or "").strip()
    if platform == "x":
        h = h.lstrip("@")
    if platform == "discord":
        h = re.sub(r"^(https?://)?(www\.)?(discord\.gg|discord\.com/invite)/", "", h).strip("/")
    if platform == "youtube" and h and not h.startswith(("@", "UC")):
        h = "@" + h
    if platform == "telegram" and h and not h.startswith("@"):
        h = "@" + h
    if platform not in HANDLE_RE:
        raise ValueError("Choose a platform.")
    if not HANDLE_RE[platform].match(h):
        raise ValueError(f"That doesn't look like a valid {PLATFORMS[platform]['label']} handle. Expected: {PLATFORMS[platform]['handle']}.")
    return h


def add(name: str, platform: str, handle: str) -> dict:
    name = (name or "").strip()
    if not NAME_RE.match(name):
        raise ValueError("Name: 1-24 letters, numbers, spaces, dots, dashes or underscores.")
    handle = clean_handle(platform, handle)
    with _lock:
        items = load()
        if len(items) >= MAX_ACCOUNTS:
            raise ValueError(f"At most {MAX_ACCOUNTS} accounts.")
        for i in items:
            if i["name"].lower() == name.lower():
                raise ValueError(f"An account named {i['name']} already exists.")
            if i["platform"] == platform and i["handle"].lower() == handle.lower():
                raise ValueError(f"That account is already tracked as {i['name']}.")
        item = {"name": name, "platform": platform, "handle": handle, "locked": True}
        _save(items + [item])
        return item


def set_locked(name: str, locked: bool) -> None:
    with _lock:
        items = load()
        hit = [i for i in items if i["name"] == name]
        if not hit:
            raise ValueError("No such account.")
        hit[0]["locked"] = bool(locked)
        _save(items)


def remove(name: str) -> None:
    with _lock:
        items = load()
        hit = [i for i in items if i["name"] == name]
        if not hit:
            raise ValueError("No such account.")
        if hit[0]["locked"]:
            raise ValueError("This account is locked. Unlock it first.")
        _save([i for i in items if i["name"] != name])


# ---------- platform readers: each returns {title, followers, stats: {label: n}, posts: [...], url} ----------
def _post(title, url, ts, **metrics):
    return {"title": re.sub(r"\s+", " ", str(title or ""))[:90], "url": url, "ts": ts, **{k: int(f(v)) for k, v in metrics.items()}}


def read_youtube(handle: str) -> dict:
    key = providers.values("youtube")["api_key"]
    q = {"id": handle} if handle.startswith("UC") else {"forHandle": handle}
    ch = net.get("https://www.googleapis.com/youtube/v3/channels", params={"part": "snippet,statistics,contentDetails", "key": key, **q})
    items = ch.get("items") or []
    if not items:
        raise net.ApiError("channel not found")
    c = items[0]
    st = c.get("statistics", {})
    posts = []
    try:
        uploads = c["contentDetails"]["relatedPlaylists"]["uploads"]
        pl = net.get("https://www.googleapis.com/youtube/v3/playlistItems", params={"part": "contentDetails", "playlistId": uploads, "maxResults": 5, "key": key})
        ids = [i["contentDetails"]["videoId"] for i in pl.get("items", [])]
        if ids:
            vids = net.get("https://www.googleapis.com/youtube/v3/videos", params={"part": "snippet,statistics", "id": ",".join(ids), "key": key})
            for v in vids.get("items", []):
                s = v.get("statistics", {})
                posts.append(_post(v["snippet"]["title"], f"https://www.youtube.com/watch?v={v['id']}", v["snippet"].get("publishedAt"),
                                   views=s.get("viewCount"), likes=s.get("likeCount"), comments=s.get("commentCount")))
    except (net.ApiError, KeyError):
        pass
    return {"title": c["snippet"]["title"], "followers": None if st.get("hiddenSubscriberCount") else int(f(st.get("subscriberCount"))),
            "stats": {"views": int(f(st.get("viewCount"))), "videos": int(f(st.get("videoCount")))}, "posts": posts,
            "url": f"https://www.youtube.com/{handle}" if handle.startswith("@") else f"https://www.youtube.com/channel/{handle}"}


def read_instagram(ig_id: str) -> dict:
    v = providers.values("instagram")
    host, token = v.get("host", "graph.facebook.com"), v["access_token"]
    me = net.get(f"https://{host}/v21.0/{ig_id}", params={"fields": "username,followers_count,follows_count,media_count", "access_token": token})
    posts = []
    try:
        media = net.get(f"https://{host}/v21.0/{ig_id}/media",
                        params={"fields": "caption,like_count,comments_count,timestamp,permalink", "limit": 5, "access_token": token})
        for m in media.get("data", []):
            posts.append(_post(m.get("caption") or "(no caption)", m.get("permalink"), m.get("timestamp"),
                               likes=m.get("like_count"), comments=m.get("comments_count")))
    except net.ApiError:
        pass
    return {"title": "@" + str(me.get("username", ig_id)), "followers": int(f(me.get("followers_count"))),
            "stats": {"following": int(f(me.get("follows_count"))), "posts": int(f(me.get("media_count")))}, "posts": posts,
            "url": f"https://www.instagram.com/{me.get('username', '')}/"}


def read_x(username: str) -> dict:
    h = {"Authorization": "Bearer " + providers.values("x")["bearer_token"]}
    u = net.get(f"https://api.twitter.com/2/users/by/username/{quote(username)}", params={"user.fields": "public_metrics,name"}, headers=h)
    d = u.get("data")
    if not d:
        raise net.ApiError("; ".join(e.get("detail", "user not found") for e in u.get("errors", [])) or "user not found")
    pm = d.get("public_metrics", {})
    posts = []
    try:
        tw = net.get(f"https://api.twitter.com/2/users/{d['id']}/tweets", headers=h,
                     params={"max_results": 5, "tweet.fields": "public_metrics,created_at", "exclude": "retweets,replies"})
        for t in tw.get("data", []):
            m = t.get("public_metrics", {})
            posts.append(_post(t.get("text"), f"https://x.com/{username}/status/{t['id']}", t.get("created_at"),
                               likes=m.get("like_count"), views=m.get("impression_count"), comments=m.get("reply_count")))
    except net.ApiError:
        pass
    return {"title": d.get("name") or "@" + username, "followers": int(f(pm.get("followers_count"))),
            "stats": {"following": int(f(pm.get("following_count"))), "posts": int(f(pm.get("tweet_count")))}, "posts": posts,
            "url": f"https://x.com/{username}"}


def read_telegram(chat: str) -> dict:
    token = providers.values("telegram")["bot_token"]
    base = f"https://api.telegram.org/bot{token}"
    cnt = net.get(f"{base}/getChatMemberCount", params={"chat_id": chat})
    if not cnt.get("ok"):
        raise net.ApiError(cnt.get("description", "Telegram refused the request"))
    title = chat
    try:
        info = net.get(f"{base}/getChat", params={"chat_id": chat})
        title = (info.get("result") or {}).get("title") or chat
    except net.ApiError:
        pass
    return {"title": title, "followers": int(f(cnt["result"])), "stats": {}, "posts": [], "url": f"https://t.me/{chat.lstrip('@')}"}


def read_discord(code: str) -> dict:
    d = net.get(f"https://discord.com/api/v10/invites/{quote(code)}", params={"with_counts": "true"})
    return {"title": (d.get("guild") or {}).get("name") or code, "followers": int(f(d.get("approximate_member_count"))),
            "stats": {"online now": int(f(d.get("approximate_presence_count")))}, "posts": [], "url": f"https://discord.gg/{code}"}


READERS = {"youtube": read_youtube, "instagram": read_instagram, "x": read_x, "telegram": read_telegram, "discord": read_discord}


def configured(platform: str) -> bool:
    return not PLATFORMS[platform]["needs_key"] or providers.is_configured(platform)


# ---------- snapshots + growth ----------
def _db() -> sqlite3.Connection:
    c = sqlite3.connect(SOCIALS_DB)
    c.execute("CREATE TABLE IF NOT EXISTS snaps(ts REAL, acct TEXT, followers INTEGER, PRIMARY KEY(ts, acct))")
    return c


def _record(name: str, followers: int | None) -> None:
    if followers is None:
        return
    with _lock, closing(_db()) as c:
        last = c.execute("SELECT MAX(ts) FROM snaps WHERE acct=?", (name,)).fetchone()[0]
        if last is None or time.time() - last >= SNAP_GAP:
            c.execute("INSERT OR REPLACE INTO snaps VALUES (?,?,?)", (time.time(), name, followers))
            c.commit()


def _growth(name: str, now_followers: int | None) -> dict:
    if now_followers is None:
        return {}
    out = {}
    now = time.time()
    with closing(_db()) as c:
        for key, span, stale in (("d1", 86400, 6 * 3600), ("d7", 7 * 86400, 24 * 3600), ("d30", 30 * 86400, 3 * 86400)):
            start = now - span
            row = c.execute("SELECT ts, followers FROM snaps WHERE acct=? AND ts<=? ORDER BY ts DESC LIMIT 1", (name, start)).fetchone()
            if not row or start - row[0] > stale:
                row = c.execute("SELECT ts, followers FROM snaps WHERE acct=? AND ts>? ORDER BY ts ASC LIMIT 1", (name, start)).fetchone() or row
            if row:
                d = now_followers - row[1]
                out[key] = {"change": d, "pct": round(d / row[1] * 100, 2) if row[1] else None, "partial": row[0] > start + stale}
        spark = c.execute("SELECT ts, followers FROM snaps WHERE acct=? AND ts>? ORDER BY ts ASC", (name, now - 30 * 86400)).fetchall()
    step = max(1, len(spark) // 60)
    out["spark"] = [r[1] for r in spark[::step]] + ([now_followers] if spark else [])
    return out


def forget(name: str) -> None:
    with _lock, closing(_db()) as c:
        c.execute("DELETE FROM snaps WHERE acct=?", (name,))
        c.commit()


# ---------- reading one / all ----------
def read_one(item: dict, force: bool = False) -> dict:
    key = (item["platform"], item["handle"])
    hit = _cache.get(key)
    base = {"name": item["name"], "platform": item["platform"], "platform_label": PLATFORMS[item["platform"]]["label"], "handle": item["handle"]}
    if hit and not force and time.time() - hit[0] < CACHE_TTL:
        data, err = hit[1], hit[2]
    else:
        data, err = None, None
        if not configured(item["platform"]):
            err = f"Add your {PLATFORMS[item['platform']]['label']} key under Connections."
        else:
            try:
                data = READERS[item["platform"]](item["handle"])
            except (net.ApiError, KeyError, ValueError) as e:
                err = vault.scrub(f"{type(e).__name__}: {e}" if not isinstance(e, net.ApiError) else str(e))
        if data is None and hit and hit[1]:      # keep showing the last good numbers when a refresh fails
            data = hit[1]
        _cache[key] = (time.time(), data, err)
    if not data:
        return {**base, "error": err, "followers": None, "stats": {}, "posts": [], "growth": {}}
    _record(item["name"], data["followers"])
    return {**base, "error": err, "title": clean_symbol_text(data["title"]), "followers": data["followers"], "stats": data["stats"],
            "posts": data["posts"], "url": data["url"], "growth": _growth(item["name"], data["followers"])}


def clean_symbol_text(s: str) -> str:
    return re.sub(r"[\r\n\t]+", " ", str(s))[:60]


def read_all(force: bool = False) -> list[dict]:
    if prefs.demo_on():
        from iris import demo
        return demo.socials()
    items = load()
    if not items:
        return []
    with ThreadPoolExecutor(max_workers=6) as ex:
        return list(ex.map(lambda i: read_one(i, force), items))
