"""SigV4-signed writes to the Pentair device endpoint.

pypentair 0.4.3 signs requests in ``Pentair.__request`` before the body is
attached, then passes ``data`` only to ``requests``. API Gateway checks the
payload hash inside the signature, so a PUT built that way is rejected.
The JSON body has to be on the ``AWSRequest`` before ``SigV4Auth.add_auth``.
"""

from __future__ import annotations

import base64
from collections.abc import Mapping
import json
import logging
import time
from typing import Any
from urllib.parse import urljoin

from botocore.awsrequest import AWSRequest
from pypentair import Pentair
import requests

from .clw1 import validate_writable_fields

_LOGGER = logging.getLogger(__name__)

BASE_URL = "https://api.pentair.cloud/"
DEVICE_PATH = "device/device-service/user/device/{device_id}"
USER_AGENT = "aws-amplify/4.3.10 react-native"
_REFRESH_HORIZON_SEC = 5 * 60
_SUCCESS_CODE = "set_device_success"


def device_put_url(device_id: str) -> str:
    """Return the device write URL."""
    return urljoin(BASE_URL, DEVICE_PATH.format(device_id=device_id))


def encode_payload(fields: Mapping[str, str]) -> str:
    """Encode the verified ``{"payload": {...}}`` body."""
    return json.dumps({"payload": dict(fields)}, separators=(", ", ": "))


def build_put_request(*, url: str, body: str | bytes, id_token: str) -> AWSRequest:
    """Build a PUT whose body is part of the request that will be signed."""
    return AWSRequest(
        method="PUT",
        url=url,
        data=body,
        headers={
            "x-amz-id-token": id_token,
            "content-type": "application/json; charset=UTF-8",
            "user-agent": USER_AGENT,
        },
    )


def merge_field_values(
    data: Mapping[str, Any] | None, fields: Mapping[str, str]
) -> dict[str, Any] | None:
    """Return a copy of a get_device payload with written values applied."""
    if not isinstance(data, Mapping) or not isinstance(data.get("data"), Mapping):
        return None
    device = dict(data["data"])
    raw_fields = device.get("fields")
    if not isinstance(raw_fields, Mapping):
        return None
    device_fields = dict(raw_fields)
    for key, value in fields.items():
        current = device_fields.get(key)
        if isinstance(current, Mapping):
            device_fields[key] = {**current, "value": value}
        else:
            device_fields[key] = value
    device["fields"] = device_fields
    return {**data, "data": device}


def signed_put_sync(
    client: Pentair, device_id: str, fields: Mapping[str, Any]
) -> dict[str, Any]:
    """PUT field values and require Pentair's success code.

    Refreshes the Cognito id token when it is inside five minutes of expiry,
    and retries once after a 401 or 403. Reserved ``rsv*`` and location
    fields are rejected before any request is signed.
    """
    payload = validate_writable_fields(fields)
    _ensure_token_fresh(client)
    response = _execute_put(client, device_id, payload)
    if response.status_code in (401, 403):
        _LOGGER.info(
            "Pentair field write returned HTTP %s; refreshing credentials and retrying once",
            response.status_code,
        )
        _force_token_refresh(client)
        response = _execute_put(client, device_id, payload)
    if response.status_code != 200:
        raise RuntimeError(f"Pentair write failed with HTTP {response.status_code}")
    try:
        body = response.json()
    except ValueError as err:
        raise RuntimeError("Pentair write returned a non-JSON response") from err
    data = body.get("data") if isinstance(body, dict) else None
    code = data.get("code") if isinstance(data, dict) else None
    if code != _SUCCESS_CODE:
        raise RuntimeError(f"Pentair API rejected write: {code or 'unknown'}")
    _LOGGER.debug("Wrote Pentair fields: %s", ", ".join(payload))
    return body


def _execute_put(
    client: Pentair, device_id: str, fields: Mapping[str, str]
) -> requests.Response:
    token = client.id_token
    if not token:
        raise RuntimeError("Pentair id token is missing")
    # Sign and send the same bytes. Encoding after signing would change the hash.
    body = encode_payload(fields).encode("utf-8")
    request = build_put_request(
        url=device_put_url(device_id), body=body, id_token=token
    )
    client.get_auth().add_auth(request)
    prepared = request.prepare()
    return requests.request(
        method="PUT",
        url=prepared.url,
        data=body,
        headers=dict(prepared.headers),
        timeout=15,
    )


def _id_token_ttl(client: Pentair) -> int:
    """Seconds left on the cached id token, or 0 when it cannot be read."""
    token = client.id_token
    if not isinstance(token, str):
        return 0
    parts = token.split(".")
    if len(parts) < 2:
        return 0
    try:
        padded = parts[1] + "=" * (-len(parts[1]) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))
        exp = int(payload["exp"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return 0
    return max(0, exp - int(time.time()))


def _ensure_token_fresh(client: Pentair) -> None:
    if _id_token_ttl(client) >= _REFRESH_HORIZON_SEC:
        return
    _force_token_refresh(client)


def _force_token_refresh(client: Pentair) -> None:
    """Renew Cognito tokens and drop cached SigV4 credentials.

    pypentair keeps the SigV4 signer in ``_auth`` while ``check_token()``
    still reports the previous id token as valid. Clearing it makes the next
    ``get_auth()`` mint credentials from the refreshed token.
    """
    client.get_user().renew_access_token()
    client._auth = None
