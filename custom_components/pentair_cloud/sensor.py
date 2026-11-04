"""Support for Pentair sensors."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfMass,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import PentairConfigEntry
from .clw1 import (
    CURRENT_FIELD,
    DEVICE_TYPE as INTELLIVIBE,
    TEMPERATURE_FIELD,
    reported_unit,
    sensor_number,
)
from .entity import PentairEntity
from .helpers import convert_timestamp, get_field_value

UNIT_MAP = {"kg": UnitOfMass.KILOGRAMS}


@dataclass(frozen=True, kw_only=True)
class PentairSensorEntityDescription(SensorEntityDescription):
    """Pentair sensor entity description."""

    value_fn: Callable[[dict], Any]


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: PentairConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Pentair sensors using config entry."""
    coordinator = config_entry.runtime_data

    entities: list[PentairSensorEntity] = []
    for device_coordinator in coordinator.device_coordinators:
        if data := device_coordinator.get_device_data():
            entities.append(
                PentairSensorEntity(
                    coordinator=device_coordinator,
                    config_entry=config_entry,
                    description=PentairSensorEntityDescription(
                        key="last_report",
                        device_class=SensorDeviceClass.TIMESTAMP,
                        entity_category=EntityCategory.DIAGNOSTIC,
                        translation_key="last_report",
                        value_fn=lambda data: (
                            convert_timestamp(ts)
                            if (ts := data.get("delivered"))
                            else None
                        ),
                    ),
                    device_id=data["deviceId"],
                )
            )
            if data.get("deviceType") == INTELLIVIBE:
                # Zone fields are lights. Skip the generic field dump so
                # reserved rsv* values (including location) are not recorded
                # as sensors. Current and temperature are added explicitly.
                for description in _intellivibe_sensors():
                    entities.append(
                        PentairSensorEntity(
                            coordinator=device_coordinator,
                            config_entry=config_entry,
                            description=description,
                            device_id=data["deviceId"],
                        )
                    )
                continue
            for field, field_data in data.get("fields", {}).items():
                if not isinstance(field_data, dict):
                    continue
                unit = UNIT_MAP.get(field_data.get("unit"))
                entity_description = PentairSensorEntityDescription(
                    key=field,
                    name=(field_data.get("name") or field).strip().capitalize(),
                    entity_category=(
                        None
                        if field_data.get("category") == "data"
                        else EntityCategory.DIAGNOSTIC
                    ),
                    native_unit_of_measurement=unit,
                    state_class=SensorStateClass.MEASUREMENT if unit else None,
                    translation_key=field,
                    value_fn=lambda data, field=field: get_field_value(field, data),
                )
                entities.append(
                    PentairSensorEntity(
                        coordinator=device_coordinator,
                        config_entry=config_entry,
                        description=entity_description,
                        device_id=data["deviceId"],
                    )
                )

    if not entities:
        return

    async_add_entities(entities)


def _intellivibe_sensors() -> tuple[PentairSensorEntityDescription, ...]:
    """Current draw and controller temperature for an IntelliVibe."""
    return (
        PentairSensorEntityDescription(
            key=CURRENT_FIELD,
            device_class=SensorDeviceClass.CURRENT,
            native_unit_of_measurement=UnitOfElectricCurrent.MILLIAMPERE,
            state_class=SensorStateClass.MEASUREMENT,
            translation_key="current_draw",
            entity_category=EntityCategory.DIAGNOSTIC,
            value_fn=lambda data: sensor_number(data, CURRENT_FIELD),
        ),
        PentairSensorEntityDescription(
            key=TEMPERATURE_FIELD,
            device_class=SensorDeviceClass.TEMPERATURE,
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            state_class=SensorStateClass.MEASUREMENT,
            translation_key="controller_temperature",
            value_fn=lambda data: sensor_number(data, TEMPERATURE_FIELD),
        ),
    )


class PentairSensorEntity(PentairEntity, SensorEntity):
    """Pentair sensor entity."""

    entity_description: PentairSensorEntityDescription

    @property
    def native_value(self) -> str | int | datetime | None:
        """Return the value reported by the sensor."""
        if isinstance(device_data := self.get_device(), dict):
            return self.entity_description.value_fn(device_data)
        return None

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Prefer the unit reported by IntelliVibe field metadata."""
        default = super().native_unit_of_measurement
        if self.entity_description.key not in (CURRENT_FIELD, TEMPERATURE_FIELD):
            return default
        if not isinstance(default, str) or not isinstance(
            device := self.get_device(), dict
        ):
            return default
        return reported_unit(device, self.entity_description.key, default)
