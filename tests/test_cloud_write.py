"""SigV4 PUT tests. No device ids, accounts, or coordinates."""

from __future__ import annotations

import base64
import hashlib
import json
import time
from typing import Any

from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.credentials import Credentials
from pentair_cloud.cloud_write import (
    build_put_request,
    device_put_url,
    encode_payload,
    signed_put_sync,
)
import pytest


def _token(exp: int) -> str:
    def encode(payload: dict[str, Any]) -> str:
        raw = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
        return raw.rstrip("=")

    return f"{encode({'alg': 'none'})}.{encode({'exp': exp})}.sig"


def _authorization(body: str) -> str:
    request = build_put_request(
        url=device_put_url("example"),
        body=body,
        id_token="token",
    )
    SigV4Auth(
        Credentials("AKIDEXAMPLE", "secretsecret", "session"),
        "execute-api",
        "us-west-2",
    ).add_auth(request)
    return request.headers["Authorization"]


def test_signature_covers_the_json_body() -> None:
    on_body = encode_payload({"l1d8": "1"})
    off_body = encode_payload({"l1d8": "0"})
    assert on_body == '{"payload": {"l1d8": "1"}}'
    assert _authorization(on_body) != _authorization(off_body)
    assert _authorization(on_body) != _authorization("")

    unsigned = AWSRequest(
        method="PUT",
        url=device_put_url("example"),
        headers={"content-type": "application/json; charset=UTF-8"},
    )
    signed = build_put_request(
        url=device_put_url("example"), body=on_body, id_token="token"
    )
    auth = SigV4Auth(
        Credentials("AKIDEXAMPLE", "secretsecret", "session"),
        "execute-api",
        "us-west-2",
    )
    auth.add_auth(unsigned)
    auth.add_auth(signed)
    assert unsigned.headers["Authorization"] != signed.headers["Authorization"]
    assert (
        hashlib.sha256(on_body.encode()).hexdigest() != hashlib.sha256(b"").hexdigest()
    )


class _Response:
    def __init__(self, status_code: int, payload: dict[str, Any] | None = None) -> None:
        self.status_code = status_code
        self._payload = payload or {"data": {"code": "set_device_success"}}

    def json(self) -> dict[str, Any]:
        return self._payload


class _Auth:
    def __init__(self, signed: dict[str, Any]) -> None:
        self._signed = signed

    def add_auth(self, request: AWSRequest) -> None:
        body = request.body
        if isinstance(body, bytes):
            body = body.decode()
        self._signed["body"] = body
        request.headers["Authorization"] = "test-signature"


class _Client:
    def __init__(self, exp: int) -> None:
        self.id_token = _token(exp)
        self._auth: object = "stale"
        self.refreshed = 0
        self.signed: dict[str, Any] = {}

    def get_auth(self) -> _Auth:
        return _Auth(self.signed)

    def get_user(self) -> Any:
        client = self

        class _User:
            def renew_access_token(self) -> None:
                client.refreshed += 1

        return _User()


def test_put_sends_the_body_that_was_signed(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _Client(int(time.time()) + 3600)
    sent: dict[str, Any] = {}

    def fake_request(method: str, url: str, **kwargs: Any) -> _Response:
        sent["method"] = method
        sent["url"] = url
        sent["data"] = kwargs["data"]
        sent["headers"] = kwargs["headers"]
        return _Response(200)

    monkeypatch.setattr("pentair_cloud.cloud_write.requests.request", fake_request)
    result = signed_put_sync(client, "example", {"l1d8": "1"})

    assert result["data"]["code"] == "set_device_success"
    assert sent["method"] == "PUT"
    assert sent["url"].endswith("/device/device-service/user/device/example")
    assert sent["data"] == b'{"payload": {"l1d8": "1"}}'
    assert sent["data"].decode() == client.signed["body"]
    assert sent["headers"]["Authorization"] == "test-signature"
    assert sent["headers"]["x-amz-id-token"] == client.id_token
    assert client.refreshed == 0


def test_reserved_fields_are_rejected_before_signing() -> None:
    class _Exploding:
        id_token = "unused"

        def get_auth(self) -> None:
            raise AssertionError("reserved fields must not be signed")

    with pytest.raises(ValueError, match="Refusing to write"):
        signed_put_sync(_Exploding(), "example", {"rsv3": "1"})


def test_auth_failure_retries_once_with_a_new_signature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _Client(int(time.time()) + 3600)
    calls = {"n": 0}

    def fake_request(method: str, url: str, **kwargs: Any) -> _Response:
        calls["n"] += 1
        return _Response(403 if calls["n"] == 1 else 200)

    monkeypatch.setattr("pentair_cloud.cloud_write.requests.request", fake_request)
    signed_put_sync(client, "example", {"l1d8": "0"})
    assert calls["n"] == 2
    assert client.refreshed == 1
    assert client._auth is None


def test_expiring_token_is_refreshed_before_the_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _Client(int(time.time()) + 30)
    monkeypatch.setattr(
        "pentair_cloud.cloud_write.requests.request",
        lambda *args, **kwargs: _Response(200),
    )
    signed_put_sync(client, "example", {"l1d4": "40"})
    assert client.refreshed == 1
    assert client._auth is None


def test_errors_do_not_include_response_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _Client(int(time.time()) + 3600)

    def rejected(method: str, url: str, **kwargs: Any) -> _Response:
        return _Response(
            200,
            {"data": {"code": "set_device_failed", "deviceId": "should-not-leak"}},
        )

    monkeypatch.setattr("pentair_cloud.cloud_write.requests.request", rejected)
    with pytest.raises(RuntimeError, match="set_device_failed") as error:
        signed_put_sync(client, "example", {"l1d8": "1"})
    assert "should-not-leak" not in str(error.value)

    monkeypatch.setattr(
        "pentair_cloud.cloud_write.requests.request",
        lambda *args, **kwargs: _Response(400, {"secret": "nope"}),
    )
    with pytest.raises(RuntimeError, match="HTTP 400") as error:
        signed_put_sync(client, "example", {"l1d8": "1"})
    assert "nope" not in str(error.value)


def test_platforms_include_light() -> None:
    from pentair_cloud import PLATFORMS

    assert "light" in PLATFORMS
