"""Coverage-guided fuzz harness (Atheris): data from the device is untrusted.

Atheris generates device status messages: random keys from the real protocol
tables with values of any JSON type, plus raw JSON text. Parsing and every
entity state must handle them without raising.

Run locally or in CI (the Fuzz workflow):

    PYTHONPATH=. python fuzz/fuzz_device_data.py -max_total_time=60
"""

import json
import sys
from types import SimpleNamespace
from typing import Any

import atheris

with atheris.instrument_imports(include=["custom_components.philips_airpurifier_local"]):
    from custom_components.philips_airpurifier_local.binary_sensor import PhilipsBinarySensor
    from custom_components.philips_airpurifier_local.climate import PhilipsHeater
    from custom_components.philips_airpurifier_local.config_flow import resolve_model
    from custom_components.philips_airpurifier_local.const import (
        BINARY_SENSOR_TYPES,
        FILTER_TYPES,
        HEATER_TYPES,
        LIGHT_TYPES,
        NUMBER_TYPES,
        SELECT_TYPES,
        SENSOR_TYPES,
        FanAttributes,
        PhilipsApi,
    )
    from custom_components.philips_airpurifier_local.helpers import (
        clamp_max_age,
        redact_status,
        safe_float,
        safe_int,
    )
    from custom_components.philips_airpurifier_local.light import PhilipsLight
    from custom_components.philips_airpurifier_local.model import DeviceInformation
    from custom_components.philips_airpurifier_local.number import PhilipsNumber
    from custom_components.philips_airpurifier_local.philips import PhilipsAC2889
    from custom_components.philips_airpurifier_local.select import PhilipsSelect
    from custom_components.philips_airpurifier_local.sensor import (
        PhilipsFilterSensor,
        PhilipsSensor,
    )

BASE_STATUS: dict[str, Any] = {
    PhilipsApi.DEVICE_ID: "fuzz-device",
    PhilipsApi.WIFI_VERSION: "AWS_Philips_AIR@62.1",
    PhilipsApi.MODEL_ID: "AC2889/10",
    PhilipsApi.NAME: "Fuzz",
}
DEVICE = DeviceInformation(model="AC2889", name="Fuzz", device_id="fuzz-device", host="192.0.2.1")

# every status key the entities read
STATUS_KEYS: list[str] = sorted(
    {
        *BASE_STATUS,
        *SENSOR_TYPES,
        *BINARY_SENSOR_TYPES,
        *NUMBER_TYPES,
        *(key.partition("#")[0] for key in (*LIGHT_TYPES, *SELECT_TYPES)),
        *FILTER_TYPES,
        *(spec[FanAttributes.TOTAL] for spec in FILTER_TYPES.values()),
        *(spec[FanAttributes.TYPE] for spec in FILTER_TYPES.values()),
        *(key.partition("#")[0] for key in HEATER_TYPES),
        *(spec[FanAttributes.TEMPERATURE] for spec in HEATER_TYPES.values()),
        *(spec[FanAttributes.POWER] for spec in HEATER_TYPES.values()),
        "pwr",
        "mode",
        "om",
        "runtime",
        "err",
    }
)


def _value(fdp: atheris.FuzzedDataProvider, depth: int = 0) -> Any:
    """Return a random JSON-like value."""
    choice = fdp.ConsumeIntInRange(0, 7 if depth < 2 else 4)
    if choice == 0:
        return None
    if choice == 1:
        return fdp.ConsumeBool()
    if choice == 2:
        return fdp.ConsumeInt(fdp.ConsumeIntInRange(1, 64))
    if choice == 3:
        return fdp.ConsumeFloat()
    if choice == 4:
        return fdp.ConsumeUnicodeNoSurrogates(fdp.ConsumeIntInRange(0, 64))
    if choice == 5:
        return [_value(fdp, depth + 1) for _ in range(fdp.ConsumeIntInRange(0, 3))]
    if choice == 6:
        return {
            fdp.ConsumeUnicodeNoSurrogates(4): _value(fdp, depth + 1)
            for _ in range(fdp.ConsumeIntInRange(0, 3))
        }
    return fdp.ConsumeIntInRange(-1, 300)


def _check_entities(status: dict[str, Any]) -> None:
    """Build every entity type on the status and read all its state."""
    data = SimpleNamespace(
        device_information=DEVICE,
        coordinator=SimpleNamespace(status=status),
        latest_status=status,
    )
    for kind in SENSOR_TYPES:
        sensor = PhilipsSensor(None, None, data, kind)
        _ = (sensor.native_value, sensor.icon)
    for kind in FILTER_TYPES:
        filter_sensor = PhilipsFilterSensor(None, None, data, kind)
        _ = (filter_sensor.native_value, filter_sensor.extra_state_attributes, filter_sensor.icon)
    for kind in BINARY_SENSOR_TYPES:
        _ = PhilipsBinarySensor(None, None, data, kind).is_on
    for kind in LIGHT_TYPES:
        light = PhilipsLight(None, None, data, kind)
        _ = (light.is_on, light.brightness)
    for kind in SELECT_TYPES:
        _ = PhilipsSelect(None, None, data, kind).current_option
    for kind in NUMBER_TYPES:
        _ = PhilipsNumber(None, None, data, kind).native_value
    for kind in HEATER_TYPES:
        heater = PhilipsHeater(None, None, data, kind, {}, {}, {})
        _ = (
            heater._get_target_temperature(),
            heater._get_current_temperature(),
            heater.hvac_action,
            heater.hvac_mode,
            heater.preset_mode,
        )
    fan = PhilipsAC2889(None, None, data)
    _ = (fan.is_on, fan.preset_mode, fan.percentage, fan.icon, fan.extra_state_attributes)


def test_one_input(data: bytes) -> None:
    """Fuzz target: one device message."""
    fdp = atheris.FuzzedDataProvider(data)

    if fdp.ConsumeBool():
        # raw JSON text, as decrypted from the device
        try:
            decoded = json.loads(fdp.ConsumeUnicodeNoSurrogates(fdp.remaining_bytes()))
        except (ValueError, RecursionError):
            return
    else:
        decoded = {
            fdp.PickValueInList(STATUS_KEYS): _value(fdp)
            for _ in range(fdp.ConsumeIntInRange(0, 12))
        }

    safe_int(decoded)
    safe_float(decoded)
    clamp_max_age(decoded)
    redact_status(decoded)
    if not isinstance(decoded, dict):
        return
    resolve_model(decoded)
    _check_entities({**BASE_STATUS, **decoded})


def main() -> None:
    """Start the fuzzer."""
    atheris.Setup(sys.argv, test_one_input)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
