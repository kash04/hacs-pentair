"""IntelliVibe (CLW1) lights.

One light per zone. Brightness, RGB color, color temperature, and the twelve
color shows are supported. A color show and a solid color clear each other.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any, ClassVar

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_EFFECT,
    ATTR_RGB_COLOR,
    ColorMode,
    LightEntity,
    LightEntityDescription,
    LightEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import PentairConfigEntry
from .clw1 import (
    COLOR_MODE_BRIGHTNESS,
    COLOR_MODE_COLOR_TEMP,
    COLOR_MODE_RGB,
    COLOR_SHOW_NAMES,
    DEVICE_TYPE,
    MAX_COLOR_TEMP_KELVIN,
    MIN_COLOR_TEMP_KELVIN,
    ZONES,
    ZoneState,
    read_zone,
    turn_off_fields,
    turn_on_fields,
)
from .entity import PentairEntity

_LOGGER = logging.getLogger(__name__)

_COLOR_MODES = {
    COLOR_MODE_BRIGHTNESS: ColorMode.BRIGHTNESS,
    COLOR_MODE_COLOR_TEMP: ColorMode.COLOR_TEMP,
    COLOR_MODE_RGB: ColorMode.RGB,
}


@dataclass(frozen=True, kw_only=True)
class PentairLightEntityDescription(LightEntityDescription):
    """Light description for one IntelliVibe zone."""

    zone: int


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: PentairConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up one light for each IntelliVibe zone."""
    coordinator = config_entry.runtime_data
    entities: list[PentairIntelliVibeLight] = []
    for device_coordinator in coordinator.device_coordinators:
        data = device_coordinator.get_device_data()
        if not data or data.get("deviceType") != DEVICE_TYPE:
            continue
        device_id = data["deviceId"]
        entities.extend(
            PentairIntelliVibeLight(
                coordinator=device_coordinator,
                config_entry=config_entry,
                description=PentairLightEntityDescription(
                    key=f"zone_{zone}",
                    zone=zone,
                    translation_key="zone",
                    translation_placeholders={"zone": str(zone)},
                    name=f"Zone {zone}",
                ),
                device_id=device_id,
            )
            for zone in ZONES
        )
    if entities:
        async_add_entities(entities)


class PentairIntelliVibeLight(PentairEntity, LightEntity):
    """One IntelliVibe zone."""

    entity_description: PentairLightEntityDescription

    _attr_effect_list: ClassVar[list[str]] = list(COLOR_SHOW_NAMES)
    _attr_max_color_temp_kelvin = MAX_COLOR_TEMP_KELVIN
    _attr_min_color_temp_kelvin = MIN_COLOR_TEMP_KELVIN
    _attr_supported_color_modes: ClassVar[set[ColorMode]] = {
        ColorMode.COLOR_TEMP,
        ColorMode.RGB,
    }
    _attr_supported_features = LightEntityFeature.EFFECT

    @property
    def is_on(self) -> bool | None:
        """Return True when the zone output is on."""
        return self._zone_state().is_on

    @property
    def brightness(self) -> int | None:
        """Return brightness on Home Assistant's 0-255 scale."""
        return self._zone_state().brightness

    @property
    def color_mode(self) -> ColorMode | None:
        """Return the active color mode."""
        mode = self._zone_state().color_mode
        if mode is None:
            return None
        return _COLOR_MODES[mode]

    @property
    def rgb_color(self) -> tuple[int, int, int] | None:
        """Return the solid RGB color while that mode is active."""
        state = self._zone_state()
        if state.color_mode != COLOR_MODE_RGB:
            return None
        return state.rgb_color

    @property
    def color_temp_kelvin(self) -> int | None:
        """Return the white color temperature while that mode is active."""
        state = self._zone_state()
        if state.color_mode != COLOR_MODE_COLOR_TEMP:
            return None
        return state.color_temp_kelvin

    @property
    def effect(self) -> str | None:
        """Return the active color show."""
        return self._zone_state().effect

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the zone on and apply color, temperature, show, or brightness."""
        rgb = kwargs.get(ATTR_RGB_COLOR)
        if rgb is not None:
            rgb = (int(rgb[0]), int(rgb[1]), int(rgb[2]))
        kelvin = kwargs.get(ATTR_COLOR_TEMP_KELVIN)
        try:
            fields = turn_on_fields(
                self.entity_description.zone,
                brightness=kwargs.get(ATTR_BRIGHTNESS),
                rgb=rgb,
                color_temp_kelvin=None if kelvin is None else int(kelvin),
                effect=kwargs.get(ATTR_EFFECT),
            )
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err
        await self._async_write(fields)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the zone off."""
        await self._async_write(turn_off_fields(self.entity_description.zone))

    async def _async_write(self, fields: dict[str, str]) -> None:
        try:
            await self.coordinator.async_set_fields(fields)
        except Exception as err:
            _LOGGER.debug(
                "IntelliVibe zone %s write failed",
                self.entity_description.zone,
                exc_info=True,
            )
            raise HomeAssistantError(
                f"Unable to update IntelliVibe zone {self.entity_description.zone}"
            ) from err

    def _zone_state(self) -> ZoneState:
        data = self.get_device()
        if not isinstance(data, dict):
            return ZoneState(
                is_on=None,
                brightness=None,
                rgb_color=None,
                color_temp_kelvin=None,
                effect=None,
            )
        return read_zone(data, self.entity_description.zone)
