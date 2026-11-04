"""Import the new platforms against the Home Assistant stubs."""

from __future__ import annotations


def test_new_modules_import() -> None:
    from pentair_cloud import cloud_write, light, sensor

    assert callable(light.async_setup_entry)
    assert callable(sensor.async_setup_entry)
    assert callable(cloud_write.signed_put_sync)
