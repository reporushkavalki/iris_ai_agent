"""Market pulse: important news and data releases the moment they come out, the economic calendar (Fed meetings, CPI, jobs),
the crypto Fear & Greed index and a mood read. Read-only; free public sources only, no keys and no accounts needed.

  Official + data   Federal Reserve press releases, BLS latest numbers (CPI, jobs, PPI ... the actual figures), SEC press releases
  Crypto news       CoinDesk, Cointelegraph, Decrypt, The Block (RSS)
  Calendar          this week's and next week's high-impact events (free public JSON) + the 2026 FOMC schedule
  Mood              Fear & Greed index, trending coins, Reddit hot posts, headline tone

Importance of a headline is scored 1-3 from keywords. 3 = "breaking": Iris says it out loud.
"""
import html
import math
import re
import threading
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

import httpx

UA = "Mozilla/5.0 (compatible; Iris-Retail/1.0; personal market monitor)"
NEWS_FEEDS = [  # (name, url, kind)
    ("Fed", "https://www.federalreserve.gov/feeds/press_all.xml", "official"),
    ("SEC", "https://www.sec.gov/news/pressreleases.rss", "official"),
    ("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/", "crypto"),
    ("Cointelegraph", "https://cointelegraph.com/rss", "crypto"),
    ("Decrypt", "https://decrypt.co/feed", "crypto"),
    ("The Block", "https://www.theblock.co/rss.xml", "crypto"),
]
BLS_URL = "https://www.bls.gov/feed/bls_latest.rss"
CAL_URLS = ["https://nfs.faireconomy.media/ff_calendar_thisweek.json", "https://nfs.faireconomy.media/ff_calendar_nextweek.json"]
FNG_URL = "https://api.alternative.me/fng/?limit=8"
TRENDING_URL = "https://api.coingecko.com/api/v3/search/trending"
REDDIT = ["CryptoCurrency", "solana"]

# FOMC meetings 2026 (decision on the second day, 14:00 New York time). Source: federalreserve.gov/monetarypolicy/fomccalendars.htm
# Add the next year's dates here when the Fed publishes them.
FOMC = [(2026, 1, 28), (2026, 3, 18), (2026, 4, 29), (2026, 6, 17), (2026, 7, 29), (2026, 9, 16), (2026, 10, 28), (2026, 12, 9)]
NY = ZoneInfo("America/New_York")

SCHEMA = {
    "name": "get_market_pulse",
    "description": (
        "Market and crypto pulse: the latest important news and data releases (Fed, BLS CPI/jobs numbers, SEC, crypto news), "
        "upcoming high-impact events such as FOMC meetings, CPI and jobs reports with forecasts, the Fear & Greed index, trending coins, "
        "Reddit mood, and an overall mood score. Use it for sentiment, news, 'what is moving the market' and "
        "'what is coming up' questions. Read-only."
    ),
    "input_schema": {"type": "object", "properties": {}},
}

# ---------------------------------------------------------------- tiny cache (keeps the last good value if a source fails)
_lock = threading.Lock()
_store: dict[str, tuple[float, object]] = {}
_errors: dict[str, str] = {}


def _cached(key: str, ttl: float, fn):
    now = time.time()
    with _lock:
        hit = _store.get(key)
        if hit and now - hit[0] < ttl:
            return hit[1]
    try:
        val = fn()
        with _lock:
            _store[key] = (now, val)
            _errors.pop(key, None)
        return val
    except Exception as e:  # noqa: BLE001 - a dead source must never break the rest
        with _lock:
            _errors[key] = f"{type(e).__name__}: {e}"[:160]
            _store[key] = (now, hit[1] if hit else None)   # wait a full interval before asking a failing source again
            return hit[1] if hit else None


def _get(url: str, **kw):
    r = httpx.get(url, headers={"User-Agent": UA, "Accept": "*/*", **kw.pop("headers", {})}, timeout=10, follow_redirects=True, **kw)
    r.raise_for_status()
    return r


# ---------------------------------------------------------------- text helpers
def _clean(t: str, n: int = 240) -> str:
    t = re.sub(r"<[^>]+>", " ", html.unescape(t or ""))
    t = re.sub(r"\s+", " ", t).strip()
    return t if len(t) <= n else t[: n - 1].rstrip() + "…"


def _ts(s: str | None) -> float:
    if not s:
        return 0.0
    try:
        return parsedate_to_datetime(s).timestamp()
    except (TypeError, ValueError):
        pass
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _parse_feed(xml_bytes: bytes, source: str, kind: str) -> list[dict]:
    root = ET.fromstring(xml_bytes)
    out = []
    for it in root.iter():
        if _local(it.tag) not in ("item", "entry"):
            continue
        f = {}
        for ch in it:
            k = _local(ch.tag)
            if k == "link":
                f["link"] = (ch.text or "").strip() or ch.attrib.get("href", "")
            elif k in ("title", "guid", "id", "pubDate", "published", "updated", "description", "summary") and k not in f:
                f[k] = ch.text or ""
        title = _clean(f.get("title", ""), 220)
        if not title:
            continue
        ts = _ts(f.get("pubDate") or f.get("published") or f.get("updated"))
        out.append({
            "id": (f.get("guid") or f.get("id") or f.get("link") or title).strip(),
            "title": title, "link": f.get("link", ""), "ts": ts, "source": source, "kind": kind,
            "text": _clean(f.get("description") or f.get("summary") or "", 200),
        })
    return out


# ---------------------------------------------------------------- importance and tone
_STRONG = [r"\bfomc\b", r"federal funds rate", r"rate decision", r"\b(cuts?|hikes?|holds?|keeps?|raises?|lowers?)\b.{0,30}\b(interest )?rates?\b",
           r"\bcpi\b", r"consumer price", r"non-?farm", r"jobs report", r"payrolls?", r"\bpowell\b", r"\betf\b.{0,40}\b(approv|reject|launch|delay|inflows?|outflows?)",
           r"\b(approv|reject)\w*\b.{0,40}\betf\b", r"\b(hack(ed)?|exploit(ed)?|drained|stolen|breach(ed)?)\b", r"bankrupt\w*|insolven\w*",
           r"\bemergency\b", r"\bhalts?\b|\bsuspends?\b", r"crash(es|ed)?\b|plunge[sd]?|plummet\w*|collapse[sd]?|tumble[sd]?",
           r"all-time high|record high|\bath\b", r"\bliquidations?\b", r"\bsec\b.{0,30}\b(sues|charges|settles?|approves?|rejects?)\b",
           r"strategic bitcoin reserve", r"\btariffs?\b", r"rate (cut|hike)"]
_MED = [r"inflation", r"unemployment", r"\bgdp\b", r"\bpce\b", r"treasury|bond yields?", r"\bban(s|ned)?\b", r"lawsuit|sued",
        r"\bbitcoin\b|\bbtc\b", r"\bether(eum)?\b|\beth\b", r"\bsolana\b|\bsol\b", r"surge[sd]?|soar(s|ed)?|jump(s|ed)?|rall(y|ies|ied)|slump(s|ed)?|drop(s|ped)?|fall(s)?\b|sell-?off",
        r"\betf\b", r"regulat\w+", r"\bsec\b", r"\bfed\b|federal reserve", r"stablecoin", r"\$\d[\d,.]*\s?(million|billion|m|b)\b"]
_BULL = [r"\bsurg\w*", r"\bsoar\w*", r"\brall(y|ies|ied)\b", r"\brecord\b", r"\bapprov\w*", r"\badopt\w*", r"\bbreakout\b", r"\bgains?\b", r"\bbull\w*", r"\binflows?\b",
         r"\bjumps?\b", r"\brises?\b|\brising\b", r"\brebound\w*", r"\brate cuts?\b|\bcuts? rates\b", r"\bpartnership\b", r"\bupgrade\w*", r"\ball-time high\b", r"\baccumulat\w*"]
_BEAR = [r"\bcrash\w*", r"\bplung\w*", r"\bhack\w*", r"\bexploit\w*", r"\bdrained\b", r"\bstolen\b", r"\bbans?\b|\bbanned\b", r"\blawsuit\b|\bsues?\b", r"\bsell-?off\b",
         r"\bfear\b", r"\bliquidat\w*", r"\bdump\w*", r"\bbear\w*", r"\bdrops?\b|\bdropped\b", r"\bfalls?\b|\bfalling\b", r"\bslump\w*", r"\bfraud\b", r"\brug\b",
         r"\bbankrupt\w*", r"\boutflows?\b", r"\brate hikes?\b|\bhikes? rates\b", r"\btariffs?\b", r"\bdelay\w*", r"\breject\w*", r"\bcollaps\w*", r"\btumbl\w*", r"\bwarns?\b"]


def importance(title: str, source: str = "", kind: str = "") -> int:
    t = title.lower()
    score = 0
    for p in _STRONG:
        if re.search(p, t):
            score += 2
    for p in _MED:
        if re.search(p, t):
            score += 1
    if kind == "official" and source == "Fed" and not re.search(r"fomc|monetary policy|federal funds|interest rate|balance sheet|discount rate|statement|minutes|rate", t):
        score = min(score, 1)   # Fed enforcement actions, surveys and so on do not move markets
    if kind == "official" and source == "SEC" and not re.search(r"crypto|bitcoin|ether|etf|digital asset|token|stablecoin", t):
        score = min(score, 1)
    return 3 if score >= 3 else 2 if score == 2 else 1


def tone(title: str) -> float:
    t = title.lower()
    b = sum(1 for p in _BULL if re.search(p, t))
    s = sum(1 for p in _BEAR if re.search(p, t))
    return 0.0 if b == s else (1.0 if b > s else -1.0)


def _words(t: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9$%.]+", t.lower()) if len(w) > 2}


def _similar(a: str, b: str) -> bool:
    x, y = _words(a), _words(b)
    return bool(x and y) and len(x & y) / len(x | y) >= 0.55


# ---------------------------------------------------------------- sources
def _news() -> tuple[list[dict], dict]:
    def one(f):
        name, url, kind = f
        return name, _cached("feed:" + name, 45, lambda: _parse_feed(_get(url).content, name, kind))
    feeds = list(NEWS_FEEDS)
    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(one, feeds))
    items = []
    for name, got in results:
        items += got or []
    return items, {n: _errors.get("feed:" + n) for n, g in results if _errors.get("feed:" + n)}


_bls_prev: dict[str, str] = {}
_bls_events: list[dict] = []
_BLS_BIG = re.compile(r"consumer price|cpi|unemployment rate|payroll|average hourly|producer price|ppi", re.I)


def _bls() -> list[dict]:
    """The BLS 'latest numbers' feed lists the newest figure of each indicator. A figure that changed = a data release."""
    def fetch():
        root = ET.fromstring(_get(BLS_URL).content)
        pub = ""
        desc = ""
        for it in root.iter("item"):
            pub = (it.findtext("pubDate") or "").strip()
            desc = it.findtext("description") or ""
            break
        rows = {}
        for p in re.findall(r"<p[^>]*>(.*?)</p>", desc, re.S | re.I):
            m = re.search(r"<span[^>]*class=\"data\"[^>]*>(.*?)</span>", p, re.S | re.I)
            if not m:
                continue
            label = _clean(p[: m.start()], 80).rstrip(":").strip()
            value = _clean(m.group(1), 60)
            if label and value:
                rows[label] = value
        return pub, rows
    got = _cached("bls", 45, fetch)
    if not got:
        return _bls_events
    pub, rows = got
    ts = _ts(pub) or time.time()
    first = not _bls_prev
    if rows and rows != _bls_prev:
        if not first:
            for label, value in rows.items():
                if _bls_prev.get(label) != value:
                    _bls_events.append({
                        "id": f"bls|{label}|{value}", "title": f"BLS data: {label} {value}", "link": "https://www.bls.gov/bls/newsrels.htm",
                        "ts": max(ts, time.time() - 60), "source": "BLS", "kind": "data", "text": "", "imp": 3 if _BLS_BIG.search(label) else 2,
                    })
            del _bls_events[:-30]
        _bls_prev.clear()
        _bls_prev.update(rows)
    return _bls_events


def _calendar() -> list[dict]:
    def fetch():
        out = []
        for u in CAL_URLS:
            try:
                for e in _get(u).json():
                    if e.get("impact") != "High":
                        continue
                    ts = _ts(e.get("date"))
                    if not ts:
                        continue
                    out.append({"id": f"cal|{e.get('date')}|{e.get('title')}|{e.get('country')}", "title": e.get("title", ""), "country": e.get("country", ""),
                                "ts": ts, "forecast": e.get("forecast") or "", "previous": e.get("previous") or ""})
            except Exception:  # noqa: BLE001 - next week's file is not published until late in the week
                if u == CAL_URLS[0]:
                    raise
        return out
    ev = _cached("calendar", 600, fetch) or []
    now = time.time()
    for y, m, d in FOMC:   # the official schedule, in case the weekly file does not carry it yet
        ts = datetime(y, m, d, 14, 0, tzinfo=NY).timestamp()
        if now - 3 * 3600 < ts < now + 30 * 86400 and not any(abs(e["ts"] - ts) < 3 * 3600 and "fomc" in e["title"].lower() for e in ev):
            ev = ev + [{"id": f"fomc|{y}-{m}-{d}", "title": "FOMC interest rate decision", "country": "USD", "ts": ts, "forecast": "", "previous": ""}]
    return sorted([e for e in ev if e["ts"] > now - 3 * 3600], key=lambda e: e["ts"])[:25]


def _fng() -> dict | None:
    def fetch():
        d = _get(FNG_URL).json()["data"]
        v = [int(x["value"]) for x in d]
        return {"value": v[0], "label": d[0]["value_classification"], "yesterday": v[1] if len(v) > 1 else None, "week_ago": v[-1] if len(v) > 6 else None}
    return _cached("fng", 600, fetch)


def _trending() -> list[dict]:
    def fetch():
        coins = _get(TRENDING_URL).json().get("coins", [])
        return [{"name": c["item"]["name"], "symbol": c["item"]["symbol"], "rank": c["item"].get("market_cap_rank")} for c in coins[:7]]
    return _cached("trending", 900, fetch) or []


def _reddit() -> dict | None:
    def fetch():
        posts = []
        for sub in REDDIT:
            data = _get(f"https://www.reddit.com/r/{sub}/hot.json?limit=12").json()
            for c in data["data"]["children"]:
                p = c["data"]
                if p.get("stickied"):
                    continue
                posts.append({"title": _clean(p["title"], 160), "score": p.get("score", 0), "comments": p.get("num_comments", 0), "sub": sub,
                              "link": "https://www.reddit.com" + p.get("permalink", "")})
        posts.sort(key=lambda p: -p["score"])
        w = [math.log10(max(10, p["score"])) for p in posts]
        t = sum(tone(p["title"]) * wi for p, wi in zip(posts, w)) / sum(w) if posts else 0.0
        return {"tone": round(t * 100), "posts": posts[:6]}
    return _cached("reddit", 300, fetch)


# ---------------------------------------------------------------- the whole picture
def pulse() -> dict:
    now = time.time()
    items, feed_errors = _news()
    for b in _bls():
        items.append(b)
    cal = _calendar()
    fng, trend, reddit = _fng(), _trending(), _reddit()

    horizon = now - 24 * 3600
    items = [i for i in items if i["ts"] and horizon < i["ts"] <= now + 600]
    for i in items:
        i["imp"] = i.get("imp") or importance(i["title"], i["source"], i["kind"])
        i["tone"] = tone(i["title"])
    items.sort(key=lambda i: i["ts"])
    kept: list[dict] = []   # the same story from three outlets is one item: the earliest one, with the others listed
    for i in items:
        twin = next((k for k in kept if k["id"] != i["id"] and _similar(k["title"], i["title"]) and abs(k["ts"] - i["ts"]) < 6 * 3600), None)
        if twin:
            twin.setdefault("also", [])
            if i["source"] != twin["source"] and i["source"] not in twin["also"]:
                twin["also"].append(i["source"])
            twin["imp"] = max(twin["imp"], i["imp"])
        else:
            kept.append(dict(i))
    kept.sort(key=lambda i: -i["ts"])
    news = [{k: v for k, v in i.items() if k != "text" or i["source"] == "BLS"} for i in kept[:40]]

    parts, wsum = [], 0.0
    if fng:
        parts.append(("fear_greed", (fng["value"] - 50) * 2, 0.5))
    recent = [i for i in kept if i["kind"] == "crypto" and i["ts"] > now - 12 * 3600]
    if recent:
        parts.append(("news", 100 * sum(i["tone"] for i in recent) / len(recent), 0.3))
    if reddit:
        parts.append(("reddit", reddit["tone"], 0.2))
    wsum = sum(w for _, _, w in parts)
    score = round(sum(v * w for _, v, w in parts) / wsum) if wsum else None
    label = None if score is None else "VERY BULLISH" if score >= 50 else "BULLISH" if score >= 15 else "NEUTRAL" if score > -15 else "BEARISH" if score > -50 else "VERY BEARISH"

    nxt = next((e for e in cal if e["ts"] > now and "fomc" in e["title"].lower()), None)
    return {
        "now": now,
        "mood": {"score": score, "label": label, "parts": {n: round(v) for n, v, _ in parts}},
        "fear_greed": fng,
        "news": news,
        "events": cal,
        "next_fomc": nxt,
        "trending": trend,
        "reddit": reddit,
        "errors": {**feed_errors, **{k: v for k, v in _errors.items() if not k.startswith("feed:")}},
    }


def get_market_pulse() -> dict:
    p = pulse()
    now = p["now"]
    return {
        "mood": p["mood"], "fear_greed": p["fear_greed"],
        "breaking_and_important_news": [{"time_ago_min": round((now - n["ts"]) / 60), "source": n["source"], "importance": n["imp"], "headline": n["title"], "also_reported_by": n.get("also", [])}
                                        for n in p["news"] if n["imp"] >= 2][:12],
        "latest_headlines": [{"time_ago_min": round((now - n["ts"]) / 60), "source": n["source"], "headline": n["title"]} for n in p["news"][:8]],
        "upcoming_events": [{"in_minutes": round((e["ts"] - now) / 60), "title": e["title"], "country": e["country"], "forecast": e["forecast"], "previous": e["previous"]} for e in p["events"]][:10],
        "trending_coins": p["trending"], "reddit_top": (p["reddit"] or {}).get("posts", [])[:4],
        "note": "mood score is -100 (very bearish) to +100 (very bullish), a blend of Fear & Greed, headline tone and Reddit when available. Source errors: " + str(p["errors"]),
    }
