"""One shared HTTP client. Errors never contain the URL, because URLs can hold keys (RPC providers, Telegram)."""
import re
import time

import httpx

_client = httpx.Client(
    timeout=httpx.Timeout(15.0, connect=8.0),
    headers={"User-Agent": "Iris-Retail/1.0 (+local dashboard)"},
    follow_redirects=True,
)


class ApiError(Exception):
    """A readable problem from an exchange, chain or social API."""


def _message(r: httpx.Response, body) -> str:
    if isinstance(body, dict):
        for k in ("msg", "message", "error_description", "detail", "retMsg"):
            v = body.get(k)
            if isinstance(v, str) and v:
                code = body.get("code") or body.get("retCode")
                return f"{v} (code {code})" if code not in (None, "", 0, "0") else v
        err = body.get("error")
        if isinstance(err, dict) and err.get("message"):
            return str(err["message"])
        if isinstance(err, str) and err:
            return err
        if isinstance(err, list) and err:
            return "; ".join(str(e) for e in err)
    text = re.sub(r"\s+", " ", r.text or "").strip()
    return text[:140] or r.reason_phrase


def request(method: str, url: str, *, params=None, headers=None, json=None, data=None, retries: int = 2):
    """Returns parsed JSON. Raises ApiError with a short, key-free message."""
    last: Exception | None = None
    for i in range(retries + 1):
        try:
            r = _client.request(method, url, params=params, headers=headers, json=json, data=data)
        except httpx.HTTPError as e:
            last = ApiError(f"network error ({type(e).__name__}); check your internet connection")
            time.sleep(0.4 * (i + 1))
            continue
        if r.status_code in (429, 502, 503) and i < retries:
            time.sleep(1.2 * (i + 1))
            continue
        try:
            body = r.json()
        except ValueError:
            body = None
        if r.status_code >= 400:
            raise ApiError(f"HTTP {r.status_code}: {_message(r, body)}")
        if body is None:
            raise ApiError("the server did not answer with JSON")
        return body
    raise last or ApiError("request failed")


def get(url: str, **kw):
    return request("GET", url, **kw)


def post(url: str, **kw):
    return request("POST", url, **kw)
