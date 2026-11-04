"""Pentair coordinator."""

from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

from pypentair import Pentair

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .cloud_write import merge_field_values, signed_put_sync
from .const import DOMAIN
from .helpers import diff_data

_LOGGER = logging.getLogger(__name__)
UPDATE_INTERVAL = 30
# The cloud can take several seconds to return a value after a write. Reading
# it back right away returns the old value and the entity flips back.
WRITE_REFRESH_DELAY = 10


class PentairDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching data from the API."""

    def __init__(
        self, hass: HomeAssistant, config_entry: ConfigEntry, client: Pentair
    ) -> None:
        """Initialize."""
        self.api = client
        self.devices: dict[str, list[dict[str, Any]]] = {}
        self.device_coordinators: list[PentairDeviceDataUpdateCoordinator] = []

        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=UPDATE_INTERVAL),
        )

    def get_device(self, device_id: str) -> dict | None:
        """Get device by id."""
        return next(
            (
                device
                for device in self.devices.get("data", [])
                if device["deviceId"] == device_id
            ),
            None,
        )

    def get_devices(self, device_type: str | None = None) -> list[dict]:
        """Get device by id."""
        return [
            device
            for device in self.devices.get("data", [])
            if device_type is None or device["deviceType"] == device_type
        ]

    async def _async_update_data(self):
        """Update data via library, refresh token if necessary."""
        try:
            if devices := await self.hass.async_add_executor_job(self.api.get_devices):
                if _LOGGER.isEnabledFor(logging.DEBUG):
                    _LOGGER.debug(
                        "Devices updated: %s",
                        diff_data(self.devices, devices) or "no changes",
                    )
                self.devices = devices
        except Exception as err:  # pylint: disable=broad-except
            _LOGGER.exception("Unknown exception while updating Pentair data")
            raise UpdateFailed(err) from err
        return self.devices


class PentairDeviceDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching data from the device endpoint."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        client: Pentair,
        device_id: str,
    ) -> None:
        """Initialize."""
        self.api = client
        self.device_id = device_id
        self._unsub_write_refresh: CALLBACK_TYPE | None = None

        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=UPDATE_INTERVAL),
        )

    def get_device_data(self) -> dict | None:
        """Get the device data."""
        if self.data and (data := self.data.get("data")):
            return data
        return None

    async def async_set_fields(self, fields: dict[str, str]) -> dict[str, Any]:
        """Write device fields with a SigV4-signed PUT.

        Reserved ``rsv*`` and location fields are rejected. The local payload
        is updated immediately, then a delayed refresh confirms the device.
        """
        result = await self.hass.async_add_executor_job(
            signed_put_sync, self.api, self.device_id, fields
        )
        if (updated := merge_field_values(self.data, fields)) is not None:
            self.async_set_updated_data(updated)
        self._schedule_write_refresh()
        return result

    @callback
    def _schedule_write_refresh(self) -> None:
        """Refresh once the cloud has had time to apply the latest write."""
        if self._unsub_write_refresh:
            self._unsub_write_refresh()
        self._unsub_write_refresh = async_call_later(
            self.hass, WRITE_REFRESH_DELAY, self._async_write_refresh
        )

    async def _async_write_refresh(self, _now: Any) -> None:
        """Run the delayed refresh scheduled after a write."""
        self._unsub_write_refresh = None
        await self.async_request_refresh()

    async def async_shutdown(self) -> None:
        """Cancel a pending write refresh before shutting down."""
        if self._unsub_write_refresh:
            self._unsub_write_refresh()
            self._unsub_write_refresh = None
        await super().async_shutdown()

    async def _async_update_data(self):
        """Update data via library, refresh token if necessary."""
        try:
            if device := await self.hass.async_add_executor_job(
                self.api.get_device, self.device_id
            ):
                if _LOGGER.isEnabledFor(logging.DEBUG):
                    _LOGGER.debug(
                        "Device %s updated: %s",
                        self.device_id,
                        diff_data(self.data, device) or "no changes",
                    )
                return device
        except Exception as err:  # pylint: disable=broad-except
            _LOGGER.exception("Unknown exception while updating Pentair data")
            raise UpdateFailed(err) from err
        else:
            return None
