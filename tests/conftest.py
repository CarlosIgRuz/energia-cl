from __future__ import annotations

import json


class FakeResp:
    def __init__(self, status=200, payload=None, headers=None, text=None, content=b""):
        self.status_code = status
        self._payload = payload
        self.headers = headers or {}
        self.text = text if text is not None else json.dumps(payload) if payload is not None else ""
        self.content = content

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload

    def raise_for_status(self):
        import requests

        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class FakeSession:
    """Responde con una función (url, params) -> FakeResp y registra las llamadas."""

    def __init__(self, responder):
        self.responder = responder
        self.llamadas: list[tuple[str, dict]] = []
        self.headers: dict = {}

    def get(self, url, params=None, timeout=None):
        self.llamadas.append((url, dict(params or {})))
        return self.responder(url, params or {})
