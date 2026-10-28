"""Coinbase (Advanced Trade API, CDP key): balances of every account/wallet, read-only. BETA.

Auth: a short-lived JWT signed with ES256 (ECDSA P-256) using the key's private key, sent as 'Authorization: Bearer <jwt>'. A new JWT for every request.
The private key is a PEM block; pasted into a single-line box it loses its line breaks, so it is rebuilt from its Base64 body here.
Needs the 'cryptography' package (in requirements.txt).
"""
import base64
import json
import os
import re
import time

from iris import net, stocks
from iris.exchanges.base import Exchange
from iris.model import f, holding, make_account

HOST = "api.coinbase.com"
STABLES = {"USD", "USDC", "USDT", "DAI"}


def normalize_pem(text: str) -> str:
    """Accepts the PEM with real line breaks, with literal \\n, or all on one line, and returns a proper PEM."""
    t = (text or "").replace("\\n", "\n").strip()
    m = re.search(r"-----BEGIN ([A-Z ]*PRIVATE KEY)-----(.*?)-----END \1-----", t, re.S)
    if not m:
        raise net.ApiError("The private key is not in the expected format. Paste the whole key, including the BEGIN and END lines.")
    body = re.sub(r"\s+", "", m.group(2))
    lines = "\n".join(body[i:i + 64] for i in range(0, len(body), 64))
    return f"-----BEGIN {m.group(1)}-----\n{lines}\n-----END {m.group(1)}-----\n"


def _b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def make_jwt(key_name: str, pem: str, method: str, host: str, path: str, now: int | None = None) -> str:
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
    except ImportError:
        raise net.ApiError("Coinbase needs the 'cryptography' package. Run LAUNCH IRIS again to install it.")
    try:
        key = serialization.load_pem_private_key(normalize_pem(pem).encode(), password=None)
    except (ValueError, TypeError):
        raise net.ApiError("Could not read the Coinbase private key. Create an ECDSA key (not Ed25519) and paste the whole private key.")
    if not isinstance(key, ec.EllipticCurvePrivateKey):
        raise net.ApiError("This Coinbase key is not an ECDSA key. Create the key again and choose ECDSA.")
    now = int(time.time()) if now is None else now
    header = {"alg": "ES256", "kid": key_name, "nonce": os.urandom(8).hex(), "typ": "JWT"}
    payload = {"sub": key_name, "iss": "cdp", "nbf": now, "exp": now + 120, "uri": f"{method.upper()} {host}{path}"}
    signing_input = _b64u(json.dumps(header, separators=(",", ":")).encode()) + "." + _b64u(json.dumps(payload, separators=(",", ":")).encode())
    r, s = decode_dss_signature(key.sign(signing_input.encode(), ec.ECDSA(hashes.SHA256())))
    return signing_input + "." + _b64u(r.to_bytes(32, "big") + s.to_bytes(32, "big"))


class Coinbase(Exchange):
    id = "coinbase"
    name = "Coinbase"

    def _get(self, path: str, query: str = ""):
        jwt = make_jwt(self.v["api_key"], self.v["api_secret"], "GET", HOST, path)      # the uri claim has the path without the query
        return net.get(f"https://{HOST}{path}" + (("?" + query) if query else ""), headers={"Authorization": "Bearer " + jwt})

    def fetch(self) -> dict:
        merged: dict[str, float] = {}
        cursor, pages = "", 0
        while pages < 10:
            body = self._get("/api/v3/brokerage/accounts", "limit=250" + (f"&cursor={cursor}" if cursor else ""))
            for a in body.get("accounts") or []:
                amt = f((a.get("available_balance") or {}).get("value")) + f((a.get("hold") or {}).get("value"))
                if amt > 0:
                    cur = str(a.get("currency") or "?").upper()
                    merged[cur] = merged.get(cur, 0.0) + amt
            pages += 1
            cursor = body.get("cursor") or ""
            if not body.get("has_next") or not cursor:
                break
        holdings = []
        for cur, amt in merged.items():
            if cur in STABLES:
                holdings.append(holding(cur, amt, "wallet", usd=amt))
            elif cur in ("EUR", "GBP", "CAD", "AUD", "CHF", "JPY"):
                try:
                    holdings.append(holding(cur, amt, "cash", usd=amt * stocks.fx_to_usd(cur)))
                except net.ApiError:
                    holdings.append(holding(cur, amt, "cash", usd=None))
            else:
                holdings.append(holding(cur, amt, "wallet"))
        return make_account("ex:coinbase", self.name, "exchange", self.id, holdings,
                            warnings=["Coinbase support is new (beta). If a balance looks wrong, tell the developer."])
