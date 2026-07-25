import pytest


class FakeResponse:
    def __init__(self, json_body, status_code=200):
        self._json = json_body
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._json


def _client(monkeypatch, responses):
    """responses: list of dicts returned by successive _post() calls."""
    from app.faz_client import FAZClient

    client = FAZClient(host="192.168.64.4", token="test-token", adom="root")
    calls = []

    def fake_post(url, json=None, headers=None, verify=None, timeout=None):
        calls.append({"url": url, "json": json, "headers": headers})
        return FakeResponse(responses[len(calls) - 1])

    monkeypatch.setattr(client._http, "post", fake_post)
    return client, calls


def test_preflight_success(monkeypatch):
    client, calls = _client(
        monkeypatch,
        [{"jsonrpc": "2.0", "id": 1, "result": [{"status": {"code": 0, "message": "OK"}}]}],
    )
    assert client.preflight() is True
    assert calls[0]["headers"]["Authorization"] == "Bearer test-token"
    assert calls[0]["json"]["params"][0]["url"] == "/logview/adom/root/logfields"


def test_preflight_success_with_bare_result_and_no_status_field(monkeypatch):
    # Confirmed live against 192.168.64.4: /logview/adom/<adom>/logfields
    # returns result as a bare dict ({"data": [...]}) with no "status" key
    # at all — absence of "status" means success, not an implicit error.
    client, _ = _client(
        monkeypatch,
        [{"jsonrpc": "2.0", "id": 1, "result": {"data": [{"index": 10, "field": []}]}}],
    )
    assert client.preflight() is True


def test_preflight_permission_denied_raises(monkeypatch):
    from app.faz_client import FAZError

    client, _ = _client(
        monkeypatch,
        [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "result": [{"status": {"code": -11, "message": "No permission for the resource"}}],
            }
        ],
    )
    with pytest.raises(FAZError, match="No permission for the resource"):
        client.preflight()


def test_preflight_jsonrpc_error_raises(monkeypatch):
    from app.faz_client import FAZError

    client, _ = _client(
        monkeypatch,
        [{"jsonrpc": "2.0", "id": 1, "error": {"code": -32600, "message": "Invalid Request"}}],
    )
    with pytest.raises(FAZError, match="Invalid Request"):
        client.preflight()


def test_get_sys_status_returns_data(monkeypatch):
    client, calls = _client(
        monkeypatch,
        [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "result": [
                    {
                        "status": {"code": 0, "message": "OK"},
                        "data": {
                            "hostname": "FAZ-TEST",
                            "version": "v7.6.7",
                            "serial": "FAZ-VM0000000001",
                            "ha-mode": "standalone",
                        },
                    }
                ],
            }
        ],
    )
    data = client.get_sys_status()
    assert data["hostname"] == "FAZ-TEST"
    assert calls[0]["json"]["params"][0]["url"] == "/sys/status"


def test_context_manager_closes_session(monkeypatch):
    from app.faz_client import FAZClient

    client = FAZClient(host="192.168.64.4", token="t", adom="root")
    closed = {"value": False}
    monkeypatch.setattr(client._http, "close", lambda: closed.__setitem__("value", True))
    with client as c:
        assert c is client
    assert closed["value"] is True
