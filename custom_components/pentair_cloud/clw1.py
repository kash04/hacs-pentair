"""IntelliVibe (CLW1) zone light protocol.

Field keys are ``l{zone}d{index}`` for zones 1-4. Reads come back as strings.
Writes are string values in one payload. Setting a solid color clears the
color show, and setting a show clears the color, which is what the Pentair
Home app does. Show ids 1 and 6 are not in the app and are ignored.

``rsv*`` fields hold certificate rotation, location, and the post interval.
Those, and latitude/longitude keys, are never written.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import re
from typing import Any

DEVICE_TYPE = "CLW1"
ZONES = (1, 2, 3, 4)

FIELD_COLOR = 2
FIELD_SHOW = 3
FIELD_BRIGHTNESS = 4
FIELD_STATE = 8

CURRENT_FIELD = "scs1"
TEMPERATURE_FIELD = "sts1"

MIN_BRIGHTNESS_PERCENT = 10
MAX_BRIGHTNESS_PERCENT = 100
MIN_COLOR_TEMP_KELVIN = 2000
MAX_COLOR_TEMP_KELVIN = 12000

COLOR_MODE_BRIGHTNESS = "brightness"
COLOR_MODE_COLOR_TEMP = "color_temp"
COLOR_MODE_RGB = "rgb"

# App grid order. The id is the string written to lnd3.
COLOR_SHOWS: dict[str, str] = {
    "2": "Party",
    "3": "Romance",
    "4": "Caribbean",
    "5": "American",
    "7": "Royal",
    "8": "Deep Blue Sea",
    "9": "Rainbow",
    "10": "Stormy Night",
    "11": "Rave",
    "12": "Northern Lights",
    "13": "Candyland",
    "14": "Lava Flow",
}
COLOR_SHOW_NAMES = tuple(COLOR_SHOWS.values())

_SHOWS_BY_NAME = {
    name.casefold(): (show_id, name) for show_id, name in COLOR_SHOWS.items()
}
_HEX_COLOR = re.compile(r"^#([0-9a-fA-F]{6})([0-9a-fA-F]{2})?$")
_KELVIN = re.compile(r"^K(\d+)$", re.IGNORECASE)
_EFFECT_OFF = "off"

_CURRENT_UNITS = {"ma": "mA", "a": "A", "amp": "A", "amps": "A"}
_TEMPERATURE_UNITS = {
    "c": "°C",
    "celsius": "°C",
    "f": "°F",
    "fahrenheit": "°F",
}


def zone_field(zone: int, index: int) -> str:
    """Return the cloud field key for one zone property."""
    _require_zone(zone)
    return f"l{zone}d{index}"


def field_value(data: Mapping[str, Any], key: str) -> Any:
    """Return a device field value from either a flat or nested payload."""
    fields = data.get("fields")
    if not isinstance(fields, Mapping) or key not in fields:
        return None
    raw = fields[key]
    if isinstance(raw, Mapping):
        return raw.get("value")
    return raw


def field_unit(data: Mapping[str, Any], key: str) -> str | None:
    """Return the unit string from nested field metadata, if any."""
    fields = data.get("fields")
    if not isinstance(fields, Mapping):
        return None
    raw = fields.get(key)
    if not isinstance(raw, Mapping):
        return None
    unit = raw.get("unit")
    if not isinstance(unit, str) or not unit.strip():
        return None
    return unit.strip()


def reported_unit(data: Mapping[str, Any], key: str, default: str) -> str:
    """Map device field metadata onto a Home Assistant unit string."""
    unit = field_unit(data, key)
    if unit is None:
        return default
    normalized = unit.lower().replace("°", "")
    table = {
        CURRENT_FIELD: _CURRENT_UNITS,
        TEMPERATURE_FIELD: _TEMPERATURE_UNITS,
    }.get(key, {})
    return table.get(normalized, default)


def sensor_number(data: Mapping[str, Any], key: str) -> int | float | None:
    """Parse a numeric sensor field. Missing and blank values are unknown."""
    raw = field_value(data, key)
    if raw is None or raw == "":
        return None
    try:
        number = float(str(raw).strip())
    except (TypeError, ValueError):
        return None
    if number.is_integer():
        return int(number)
    return number


def is_forbidden_field(key: str) -> bool:
    """Return True for reserved config and location fields."""
    lowered = key.lower()
    if lowered.startswith("rsv"):
        return True
    if lowered in {"lat", "long", "lng", "latitude", "longitude"}:
        return True
    return "latitude" in lowered or "longitude" in lowered


def validate_writable_fields(fields: Mapping[str, Any]) -> dict[str, str]:
    """Return a string payload, rejecting reserved and non-string values."""
    if not fields:
        raise ValueError("No Pentair fields to write")
    cleaned: dict[str, str] = {}
    for key, value in fields.items():
        if not isinstance(key, str) or is_forbidden_field(key):
            raise ValueError(f"Refusing to write reserved Pentair field {key!r}")
        if not isinstance(value, str):
            raise TypeError(f"Pentair field {key!r} must be a string")
        cleaned[key] = value
    return cleaned


def percent_to_brightness(percent: int) -> int:
    """Map a device brightness percent (0-100) to Home Assistant's 0-255."""
    bounded = min(MAX_BRIGHTNESS_PERCENT, max(0, int(percent)))
    return round(bounded * 255 / 100)


def brightness_to_percent(brightness: int) -> int:
    """Map Home Assistant brightness to the app range of 10-100%."""
    value = int(brightness)
    if value < 0 or value > 255:
        raise ValueError(f"Brightness must be 0-255, got {brightness}")
    percent = round(value * 100 / 255)
    return min(MAX_BRIGHTNESS_PERCENT, max(MIN_BRIGHTNESS_PERCENT, percent))


def format_rgb(red: int, green: int, blue: int) -> str:
    """Format an RGB color the way the app writes the color wheel.

    The white byte stays ``00``. White level is the separate ``Kxxxx`` color
    temperature value, not this byte.
    """
    channels = []
    for channel in (red, green, blue):
        value = int(channel)
        if value < 0 or value > 255:
            raise ValueError(f"RGB channel must be 0-255, got {channel}")
        channels.append(value)
    return "#{:02x}{:02x}{:02x}00".format(*channels)


def format_kelvin(kelvin: int) -> str:
    """Format a color temperature inside the app range of 2000-12000 K."""
    value = min(MAX_COLOR_TEMP_KELVIN, max(MIN_COLOR_TEMP_KELVIN, int(kelvin)))
    return f"K{value}"


def parse_rgb(raw: Any) -> tuple[int, int, int] | None:
    """Parse ``#RRGGBB`` or ``#RRGGBBWW`` into RGB. Other values are not RGB."""
    if not isinstance(raw, str):
        return None
    match = _HEX_COLOR.match(raw.strip())
    if match is None:
        return None
    hex_rgb = match.group(1)
    return tuple(int(hex_rgb[index : index + 2], 16) for index in (0, 2, 4))


def parse_kelvin(raw: Any) -> int | None:
    """Parse a ``K2000`` style color temperature."""
    if not isinstance(raw, str):
        return None
    match = _KELVIN.match(raw.strip())
    if match is None:
        return None
    return int(match.group(1))


def show_name(raw: Any) -> str | None:
    """Return the app name for a color-show id, or None when no show is active."""
    if raw is None or isinstance(raw, bool):
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        text = str(int(text))
    except ValueError:
        return None
    return COLOR_SHOWS.get(text)


def turn_off_fields(zone: int) -> dict[str, str]:
    """Payload that turns one zone off."""
    return {zone_field(zone, FIELD_STATE): "0"}


def turn_on_fields(
    zone: int,
    *,
    brightness: int | None = None,
    rgb: tuple[int, int, int] | None = None,
    color_temp_kelvin: int | None = None,
    effect: str | None = None,
) -> dict[str, str]:
    """Payload that turns one zone on and applies any requested light change.

    A named show clears the color. A color or color temperature clears the
    show. Brightness is independent. When both a named show and a color are
    passed, the show wins and the color is cleared.
    """
    fields = {zone_field(zone, FIELD_STATE): "1"}
    if brightness is not None:
        fields[zone_field(zone, FIELD_BRIGHTNESS)] = str(
            brightness_to_percent(brightness)
        )

    if effect is not None and effect.strip().casefold() != _EFFECT_OFF:
        show_id, _canonical = _resolve_show(effect)
        fields[zone_field(zone, FIELD_SHOW)] = show_id
        fields[zone_field(zone, FIELD_COLOR)] = ""
    elif rgb is not None:
        fields[zone_field(zone, FIELD_COLOR)] = format_rgb(*rgb)
        fields[zone_field(zone, FIELD_SHOW)] = ""
    elif color_temp_kelvin is not None:
        fields[zone_field(zone, FIELD_COLOR)] = format_kelvin(color_temp_kelvin)
        fields[zone_field(zone, FIELD_SHOW)] = ""
    elif effect is not None:
        fields[zone_field(zone, FIELD_SHOW)] = ""
    return fields


@dataclass(frozen=True, kw_only=True)
class ZoneState:
    """Interpreted state for one IntelliVibe zone."""

    is_on: bool | None
    brightness: int | None
    rgb_color: tuple[int, int, int] | None
    color_temp_kelvin: int | None
    effect: str | None

    @property
    def color_mode(self) -> str | None:
        """Return the active color mode, or None while the zone is off."""
        if self.is_on is not True:
            return None
        if self.effect:
            return COLOR_MODE_BRIGHTNESS
        if self.color_temp_kelvin is not None:
            return COLOR_MODE_COLOR_TEMP
        return COLOR_MODE_RGB


def read_zone(data: Mapping[str, Any], zone: int) -> ZoneState:
    """Interpret one zone from a device payload."""
    raw_state = field_value(data, zone_field(zone, FIELD_STATE))
    is_on = (
        None if raw_state is None or raw_state == "" else str(raw_state).strip() == "1"
    )
    color_raw = field_value(data, zone_field(zone, FIELD_COLOR))
    kelvin = parse_kelvin(color_raw)
    return ZoneState(
        is_on=is_on,
        brightness=_parse_brightness(
            field_value(data, zone_field(zone, FIELD_BRIGHTNESS))
        ),
        rgb_color=None if kelvin is not None else parse_rgb(color_raw),
        color_temp_kelvin=kelvin,
        effect=show_name(field_value(data, zone_field(zone, FIELD_SHOW))),
    )


def _require_zone(zone: int) -> None:
    if zone not in ZONES:
        raise ValueError(f"IntelliVibe zone must be 1-4, got {zone}")


def _resolve_show(name: str) -> tuple[str, str]:
    match = _SHOWS_BY_NAME.get(name.strip().casefold())
    if match is None:
        raise ValueError(f"Unknown IntelliVibe color show: {name}")
    return match


def _parse_brightness(raw: Any) -> int | None:
    if raw is None or raw == "":
        return None
    try:
        percent = int(float(str(raw).strip()))
    except (TypeError, ValueError):
        return None
    return percent_to_brightness(percent)
