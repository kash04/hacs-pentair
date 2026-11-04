"""Import the new platforms against the Home Assistant stubs."""

from __future__ import annotations


def test_new_modules_import() -> None:
    from pentair_cloud import cloud_write, light, sensor

    assert callable(light.async_setup_entry)
    assert callable(sensor.async_setup_entry)
    assert callable(cloud_write.signed_put_sync)


def test_intellivibe_current_draw_is_diagnostic() -> None:
    from pentair_cloud import sensor

    current, temperature = sensor._intellivibe_sensors()
    assert current.translation_key == "current_draw"
    assert current.entity_category == "diagnostic"
    assert temperature.translation_key == "controller_temperature"
    assert getattr(temperature, "entity_category", None) is None
