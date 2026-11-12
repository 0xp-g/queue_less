"""QR and ticket tokens (ADR-0004). Pure functions of (secret, message) - no I/O.

* Join token:    HMAC(secret, "join:{queue_id}:{date}")         rotates daily
* Counter nonce: HMAC(secret, "counter:{id}:{30 s window}")     rotates every window
* Ticket token:  HMAC(secret, "ticket:{queue_id}:{request_id}")  128 bits, only its SHA-256 stored

The ticket token is derived from the browser-generated client_request_id so that a retried join
returns the *same* token (idempotent response) without the server storing the raw token.
"""

import base64
import hashlib
import hmac
from datetime import date, timedelta


class TokenSigner:
    """HMAC-SHA256 signing with constant-time verification."""

    def __init__(self, secret: str | bytes, nbytes: int = 16):
        self._key = secret.encode() if isinstance(secret, str) else secret
        self._nbytes = nbytes

    def sign(self, message: str) -> str:
        digest = hmac.new(self._key, message.encode(), hashlib.sha256).digest()[: self._nbytes]
        return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()

    def verify(self, message: str, signature: str) -> bool:
        return hmac.compare_digest(self.sign(message), signature or "")


class JoinTokenService:
    def __init__(self, signer: TokenSigner):
        self._signer = signer

    def issue(self, queue_id: int, day: date) -> str:
        return self._signer.sign(f"join:{queue_id}:{day.isoformat()}")

    def verify(self, queue_id: int, token: str, today: date) -> bool:
        """Accept today's and yesterday's token so a QR scanned at 23:59 still works."""
        return any(
            self._signer.verify(f"join:{queue_id}:{d.isoformat()}", token)
            for d in (today, today - timedelta(days=1))
        )


class CounterNonceService:
    def __init__(self, signer: TokenSigner, window_sec: int = 30):
        self._signer = signer
        self.window_sec = window_sec

    def _window(self, now: float) -> int:
        return int(now // self.window_sec)

    def issue(self, counter_id: int, now: float) -> str:
        return self._signer.sign(f"counter:{counter_id}:{self._window(now)}")

    def expires_in(self, now: float) -> float:
        return self.window_sec - (now % self.window_sec)

    def verify(self, counter_id: int, nonce: str, now: float) -> bool:
        """Current or previous window: a nonce lives between window_sec and 2 * window_sec."""
        w = self._window(now)
        return any(self._signer.verify(f"counter:{counter_id}:{x}", nonce) for x in (w, w - 1))


class TicketTokens:
    def __init__(self, signer: TokenSigner):
        self._signer = signer

    def issue(self, queue_id: int, client_request_id: str) -> str:
        return self._signer.sign(f"ticket:{queue_id}:{client_request_id}")

    @staticmethod
    def hash(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()
