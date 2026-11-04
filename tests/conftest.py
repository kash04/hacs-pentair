"""Import the integration without a Home Assistant install.

The protocol and SigV4 tests only need the real pypentair/botocore modules.
Home Assistant is stubbed so importing the package does not require it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC
from pathlib import Path
import sys
import types

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "custom_components"))


def _module(name: str) -> types.ModuleType:
    if name in sys.modules:
        return sys.modules[name]
    module = sys.modules.get(name) or types.ModuleType(name)
    module.__path__ = []
    sys.modules[name] = module
    if "." in name:
        parent_name, child = name.rsplit(".", 1)
        setattr(_module(parent_name), child, module)
    return module


class _Attr:
    def __init__(self, **attrs: object) -> None:
        for key, value in attrs.items():
            setattr(self, key, value)


def _install_stubs() -> None:
    const = _module("homeassistant.const")
    const.CONF_ACCESS_TOKEN = "access_token"
    const.CONF_USERNAME = "username"
    const.EntityCategory = _Attr(DIAGNOSTIC="diagnostic")
    const.Platform = _Attr(
        BINARY_SENSOR="binary_sensor", LIGHT="light", SENSOR="sensor"
    )
    const.UnitOfElectricCurrent = _Attr(MILLIAMPERE="mA", AMPERE="A")
    const.UnitOfMass = _Attr(KILOGRAMS="kg")
    const.UnitOfTemperature = _Attr(CELSIUS="°C", FAHRENHEIT="°F")

    core = _module("homeassistant.core")
    core.CALLBACK_TYPE = object
    core.HomeAssistant = type("HomeAssistant", (), {})
    core.callback = lambda func: func

    exceptions = _module("homeassistant.exceptions")
    exceptions.ConfigEntryAuthFailed = type("ConfigEntryAuthFailed", (Exception,), {})
    exceptions.ConfigEntryNotReady = type("ConfigEntryNotReady", (Exception,), {})
    exceptions.HomeAssistantError = type("HomeAssistantError", (Exception,), {})

    config_entries = _module("homeassistant.config_entries")
    config_entries.ConfigEntry = type("ConfigEntry", (), {})

    device_registry = _module("homeassistant.helpers.device_registry")
    device_registry.DeviceEntry = type("DeviceEntry", (), {})

    event = _module("homeassistant.helpers.event")
    event.async_call_later = None

    entity = _module("homeassistant.helpers.entity")
    entity.DeviceInfo = dict
    entity.EntityDescription = type("EntityDescription", (), {})

    class _Subscriptable:
        def __class_getitem__(cls, _item: object) -> type:
            return cls

    update_coordinator = _module("homeassistant.helpers.update_coordinator")
    update_coordinator.DataUpdateCoordinator = type("DataUpdateCoordinator", (), {})
    update_coordinator.UpdateFailed = type("UpdateFailed", (Exception,), {})
    update_coordinator.CoordinatorEntity = type(
        "CoordinatorEntity", (_Subscriptable,), {}
    )

    entity_platform = _module("homeassistant.helpers.entity_platform")
    entity_platform.AddConfigEntryEntitiesCallback = object

    light = _module("homeassistant.components.light")
    light.ATTR_BRIGHTNESS = "brightness"
    light.ATTR_COLOR_TEMP_KELVIN = "color_temp_kelvin"
    light.ATTR_EFFECT = "effect"
    light.ATTR_RGB_COLOR = "rgb_color"
    light.ColorMode = _Attr(BRIGHTNESS="brightness", COLOR_TEMP="color_temp", RGB="rgb")
    light.LightEntity = type("LightEntity", (), {})
    light.LightEntityDescription = type("LightEntityDescription", (), {})
    light.LightEntityFeature = _Attr(EFFECT=4)

    sensor = _module("homeassistant.components.sensor")
    sensor.SensorDeviceClass = _Attr(
        CURRENT="current", TEMPERATURE="temperature", TIMESTAMP="timestamp"
    )
    sensor.SensorEntity = type("SensorEntity", (), {})
    @dataclass(frozen=True, kw_only=True)
    class SensorEntityDescription:
        key: str
        name: str | None = None
        device_class: str | None = None
        entity_category: str | None = None
        entity_registry_enabled_default: bool = True
        native_unit_of_measurement: str | None = None
        state_class: str | None = None
        translation_key: str | None = None

    sensor.SensorEntityDescription = SensorEntityDescription
    sensor.SensorStateClass = _Attr(MEASUREMENT="measurement")

    dt = _module("homeassistant.util.dt")
    dt.UTC = UTC


_install_stubs()
