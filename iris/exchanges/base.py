"""Exchange connectors are READ-ONLY: they only call balance / position endpoints. There is no trading code anywhere."""
import base64
import hashlib
import hmac


def hmac_hex(secret: str, message: str, algo=hashlib.sha256) -> str:
    return hmac.new(secret.encode(), message.encode(), algo).hexdigest()


def hmac_b64(secret: str, message: str, algo=hashlib.sha256) -> str:
    return base64.b64encode(hmac.new(secret.encode(), message.encode(), algo).digest()).decode()


class Exchange:
    id = ""
    name = ""

    def __init__(self, values: dict):
        self.v = values

    def fetch(self) -> dict:
        """Return a normalised account (see iris.model.make_account)."""
        raise NotImplementedError

    def permissions(self) -> list[dict]:
        """Best effort: warn when the key can trade or withdraw. [{'level': 'danger'|'warn'|'info', 'text': str}]"""
        return []


def warn(level: str, text: str) -> dict:
    return {"level": level, "text": text}
