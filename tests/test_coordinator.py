"""Device coordinator write tests. No device ids, accounts, or coordinates."""

from __future__ import annotations

import asyncio
from typing import Any

from pentair_cloud import coordinator as coordinator_module
from pentair_cloud.coordinator import (
    WRITE_REFRESH_DELAY,
    PentairDeviceDataUpdateCoordinator,
)
import pytest


class _Hass:
    async def async_add_executor_job(self, target: Any, *args: Any) -> Any:
        return target(*args)


def _coordinator(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[PentairDeviceDataUpdateCoordinator, list[Any], list[str]]:
    scheduled: list[Any] = []
    calls: list[str] = []

    def call_later(hass: Any, delay: float, action: Any) -> Any:
        entry = {"delay": delay, "action": action, "cancelled": False}
        scheduled.append(entry)

        def cancel() -> None:
            entry["cancelled"] = True

        return cancel

    monkeypatch.setattr(coordinator_module, "async_call_later", call_later)
    monkeypatch.setattr(
        coordinator_module,
        "signed_put_sync",
        lambda api, device_id, fields: {"code": "set_device_success"},
    )

    coordinator = PentairDeviceDataUpdateCoordinator.__new__(
        PentairDeviceDataUpdateCoordinator
    )
    coordinator.hass = _Hass()
    coordinator.api = object()
    coordinator.device_id = "example"
    coordinator._unsub_write_refresh = None
    coordinator.data = {"data": {"fields": {"l1d8": {"value": "0"}}}}

    def set_updated_data(data: dict[str, Any]) -> None:
        coordinator.data = data
        calls.append("set")

    async def request_refresh() -> None:
        calls.append("refresh")

    coordinator.async_set_updated_data = set_updated_data
    coordinator.async_request_refresh = request_refresh
    return coordinator, scheduled, calls


def test_write_keeps_local_value_and_delays_refresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    coordinator, scheduled, calls = _coordinator(monkeypatch)

    asyncio.run(coordinator.async_set_fields({"l1d8": "1"}))

    assert coordinator.data["data"]["fields"]["l1d8"]["value"] == "1"
    assert calls == ["set"]
    assert [entry["delay"] for entry in scheduled] == [WRITE_REFRESH_DELAY]

    asyncio.run(scheduled[0]["action"](None))

    assert calls == ["set", "refresh"]
    assert coordinator._unsub_write_refresh is None


def test_new_write_replaces_pending_refresh(monkeypatch: pytest.MonkeyPatch) -> None:
    coordinator, scheduled, _calls = _coordinator(monkeypatch)

    asyncio.run(coordinator.async_set_fields({"l1d8": "1"}))
    asyncio.run(coordinator.async_set_fields({"l1d8": "0"}))

    assert [entry["cancelled"] for entry in scheduled] == [True, False]
    assert coordinator.data["data"]["fields"]["l1d8"]["value"] == "0"
