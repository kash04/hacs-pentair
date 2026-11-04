"""IntelliVibe zone payload and state tests."""

from __future__ import annotations

import json

from pentair_cloud.cloud_write import encode_payload, merge_field_values
from pentair_cloud.clw1 import (
    brightness_to_percent,
    format_rgb,
    is_forbidden_field,
    percent_to_brightness,
    read_zone,
    reported_unit,
    sensor_number,
    turn_off_fields,
    turn_on_fields,
    validate_writable_fields,
)
import pytest


def _zone(**fields: object) -> dict:
    return {"fields": fields}


def test_verified_zone_power_payload() -> None:
    """On and off match the PUT body verified against a live controller."""
    assert encode_payload(turn_on_fields(1)) == '{"payload": {"l1d8": "1"}}'
    assert encode_payload(turn_off_fields(1)) == '{"payload": {"l1d8": "0"}}'
    assert json.loads(encode_payload(turn_off_fields(4))) == {"payload": {"l4d8": "0"}}


def test_color_clears_show_and_uses_app_hex() -> None:
    fields = turn_on_fields(1, rgb=(4, 40, 255))
    assert fields == {"l1d8": "1", "l1d2": "#0428ff00", "l1d3": ""}
    assert format_rgb(28, 255, 0) == "#1cff0000"
    assert format_rgb(255, 255, 255) == "#ffffff00"


def test_color_temperature_clears_show_and_clamps() -> None:
    assert turn_on_fields(2, color_temp_kelvin=4000) == {
        "l2d8": "1",
        "l2d2": "K4000",
        "l2d3": "",
    }
    assert turn_on_fields(2, color_temp_kelvin=1500)["l2d2"] == "K2000"
    assert turn_on_fields(2, color_temp_kelvin=20000)["l2d2"] == "K12000"


def test_show_clears_color_and_accepts_app_names() -> None:
    assert turn_on_fields(3, effect="Party") == {
        "l3d8": "1",
        "l3d3": "2",
        "l3d2": "",
    }
    fields = turn_on_fields(1, effect="deep blue sea", rgb=(0, 0, 255))
    assert fields["l1d3"] == "8"
    assert fields["l1d2"] == ""
    assert "l1d4" not in fields


def test_show_ids_absent_from_the_app_are_not_effects() -> None:
    for show_id in ("1", "6", "", None):
        state = read_zone(
            _zone(l1d8="1", l1d2="#0428ff00", l1d3=show_id, l1d4="100"),
            1,
        )
        assert state.effect is None
        assert state.color_mode == "rgb"


def test_clearing_the_show_without_a_color_only_clears_the_show() -> None:
    assert turn_on_fields(1, effect="off") == {"l1d8": "1", "l1d3": ""}


def test_brightness_is_independent_and_limited_to_the_app_range() -> None:
    assert turn_on_fields(1, brightness=255) == {"l1d8": "1", "l1d4": "100"}
    assert brightness_to_percent(0) == 10
    assert brightness_to_percent(255) == 100
    assert percent_to_brightness(100) == 255
    assert percent_to_brightness(10) == round(10 * 255 / 100)
    with pytest.raises(ValueError):
        brightness_to_percent(256)


def test_unknown_show_and_zone_are_rejected() -> None:
    with pytest.raises(ValueError, match="Unknown IntelliVibe color show"):
        turn_on_fields(1, effect="Not a show")
    with pytest.raises(ValueError, match="1-4"):
        turn_off_fields(5)


def test_read_zone_from_nested_and_flat_fields() -> None:
    nested = read_zone(
        {
            "fields": {
                "l4d8": {"name": "4 - Light State", "value": "1"},
                "l4d2": {"value": ""},
                "l4d3": {"value": "12"},
                "l4d4": {"value": "80"},
            }
        },
        4,
    )
    assert nested.is_on is True
    assert nested.effect == "Northern Lights"
    assert nested.color_mode == "brightness"
    assert nested.brightness == percent_to_brightness(80)
    assert nested.rgb_color is None

    flat = read_zone(_zone(l1d8="0", l1d2="K4000", l1d3="", l1d4="10"), 1)
    assert flat.is_on is False
    assert flat.color_mode is None
    assert flat.color_temp_kelvin == 4000
    assert flat.effect is None


def test_sensors_and_units() -> None:
    data = {
        "fields": {
            "scs1": {"value": "250", "unit": "mA"},
            "sts1": {"value": "21.5", "unit": "Celsius"},
        }
    }
    assert sensor_number(data, "scs1") == 250
    assert sensor_number(data, "sts1") == 21.5
    assert sensor_number(data, "missing") is None
    assert sensor_number({"fields": {"scs1": {"value": ""}}}, "scs1") is None
    assert reported_unit(data, "scs1", "mA") == "mA"
    assert reported_unit(data, "sts1", "°C") == "°C"
    assert reported_unit({"fields": {"sts1": {"unit": "F"}}}, "sts1", "°C") == "°F"
    assert reported_unit({"fields": {}}, "sts1", "°C") == "°C"


def test_reserved_fields_are_not_writable() -> None:
    for key in (
        "rsv3",
        "rsv10",
        "RSV1",
        "lat",
        "long",
        "latitude",
        "longitude",
        "deviceLatitude",
    ):
        assert is_forbidden_field(key)
        with pytest.raises(ValueError, match="Refusing to write"):
            validate_writable_fields({key: "1"})
    assert validate_writable_fields({"l1d8": "1", "l1d2": ""}) == {
        "l1d8": "1",
        "l1d2": "",
    }
    with pytest.raises(TypeError):
        validate_writable_fields({"l1d8": 1})
    with pytest.raises(ValueError):
        validate_writable_fields({})


def test_merge_field_values_does_not_mutate_the_previous_payload() -> None:
    original = {
        "data": {
            "fields": {
                "l1d8": {"name": "1 - Light State", "value": "0"},
                "l1d2": "K4000",
            }
        }
    }
    merged = merge_field_values(original, {"l1d8": "1", "l1d2": "#ffffff00"})
    assert merged is not None
    assert merged["data"]["fields"]["l1d8"] == {
        "name": "1 - Light State",
        "value": "1",
    }
    assert merged["data"]["fields"]["l1d2"] == "#ffffff00"
    assert original["data"]["fields"]["l1d8"]["value"] == "0"
    assert original["data"]["fields"]["l1d2"] == "K4000"
    assert merge_field_values(None, {"l1d8": "1"}) is None
