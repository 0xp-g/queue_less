from datetime import date

from app.domain.tokens import CounterNonceService, JoinTokenService, TicketTokens, TokenSigner

signer = TokenSigner("unit-test-secret")


def test_join_token_valid_today_and_yesterday_only():
    svc = JoinTokenService(signer)
    tok = svc.issue(7, date(2026, 1, 10))
    assert svc.verify(7, tok, date(2026, 1, 10))
    assert svc.verify(7, tok, date(2026, 1, 11))  # midnight grace
    assert not svc.verify(7, tok, date(2026, 1, 12))  # a photo from two days ago is dead
    assert not svc.verify(8, tok, date(2026, 1, 10))  # bound to the queue


def test_join_token_rejects_tampering():
    svc = JoinTokenService(signer)
    tok = svc.issue(1, date(2026, 1, 1))
    assert not svc.verify(1, tok[:-1] + ("A" if tok[-1] != "A" else "B"), date(2026, 1, 1))
    assert not svc.verify(1, "", date(2026, 1, 1))


def test_other_secret_cannot_forge():
    forged = JoinTokenService(TokenSigner("attacker")).issue(1, date(2026, 1, 1))
    assert not JoinTokenService(signer).verify(1, forged, date(2026, 1, 1))


def test_counter_nonce_rotates():
    svc = CounterNonceService(signer, window_sec=30)
    nonce = svc.issue(3, now=1000.0)
    assert svc.verify(3, nonce, now=1000.0)
    assert svc.verify(3, nonce, now=1000.0 + 30)  # previous window still accepted
    assert not svc.verify(3, nonce, now=1000.0 + 61)  # expired
    assert not svc.verify(4, nonce, now=1000.0)  # other counter


def test_ticket_token_is_deterministic_per_request_and_128_bit():
    tt = TicketTokens(signer)
    a = tt.issue(1, "req-1")
    assert a == tt.issue(1, "req-1")  # idempotent replay returns the same token
    assert a != tt.issue(1, "req-2")
    assert len(a) == 22  # 16 bytes base64url
    assert len(TicketTokens.hash(a)) == 64 and TicketTokens.hash(a) != a
