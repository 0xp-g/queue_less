# ADR-0004: QR and token design

**Status:** Accepted

## Context
Three QR/token surfaces carry three different threats:
* **Join QR** is posted publicly, so it can be photographed and shared off-site.
* **Ticket token** proves who owns a ticket (cancel, status), so it must be unguessable and must not leak from the DB.
* **Check-in**: a visitor must be physically at the counter, so remote check-in has to be prevented.

## Decision
| Token | Format | Validation |
|---|---|---|
| Join | `HMAC-SHA256(secret, "join:{queue_id}:{YYYY-MM-DD}")`, truncated base64url | Accept today and yesterday (midnight grace). Constant-time compare |
| Ticket | `secrets.token_urlsafe(16)` (128 bits) | DB stores `sha256(token)` only, so a DB leak doesn't let anyone act as a visitor |
| Counter nonce | `HMAC(secret, "counter:{id}:{floor(now/30)}")` shown on the counter screen, refreshing every 30 s | Accept the current and previous window (≤ 60 s) |

Abuse controls: a Redis fixed-window per-IP join rate limit (fails **open** if Redis is down, logged), and a partial unique index allowing **one active ticket per `device_id` per queue**.

## Alternatives rejected
* **JWT for QR tokens:** larger QR codes and nothing extra gained; we don't need claims beyond queue and date.
* **Storing raw ticket tokens:** a DB dump would let anyone cancel tickets.
* **GPS check-in:** spoofable, needs a permissions prompt, and is inaccurate indoors.

## Consequences
* A shared photo of the join QR stops working within about 24 hours. Determined abuse needs more (CAPTCHA, venue Wi-Fi gating), which is listed as future work.
* `device_id` is a client-generated value in localStorage, so it's a speed bump, not identity. That's stated honestly.
