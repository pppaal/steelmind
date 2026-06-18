"""Proxy-aware client IP resolution for rate limiting / session fallback."""

from starlette.requests import Request

import backend.main as main


def _request(peer: str | None, headers: dict[str, str] | None = None) -> Request:
    raw_headers = [
        (k.lower().encode(), v.encode()) for k, v in (headers or {}).items()
    ]
    scope = {
        "type": "http",
        "headers": raw_headers,
        "client": (peer, 12345) if peer else None,
    }
    return Request(scope)


def test_ignores_forwarded_header_by_default(monkeypatch) -> None:
    monkeypatch.setattr(main.config, "TRUST_PROXY_HEADERS", False)
    req = _request("10.0.0.1", {"x-forwarded-for": "1.2.3.4"})
    # Without trust, an attacker-supplied header must not win.
    assert main._client_ip(req) == "10.0.0.1"


def test_uses_leftmost_forwarded_when_trusted(monkeypatch) -> None:
    monkeypatch.setattr(main.config, "TRUST_PROXY_HEADERS", True)
    req = _request("10.0.0.1", {"x-forwarded-for": "1.2.3.4, 10.0.0.1"})
    assert main._client_ip(req) == "1.2.3.4"


def test_falls_back_to_peer_when_trusted_but_no_header(monkeypatch) -> None:
    monkeypatch.setattr(main.config, "TRUST_PROXY_HEADERS", True)
    req = _request("10.0.0.1")
    assert main._client_ip(req) == "10.0.0.1"


def test_unknown_when_no_peer(monkeypatch) -> None:
    monkeypatch.setattr(main.config, "TRUST_PROXY_HEADERS", False)
    req = _request(None)
    assert main._client_ip(req) == "unknown"
