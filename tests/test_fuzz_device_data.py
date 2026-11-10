"""Property-based (fuzz) tests: data from the device is untrusted.

Hypothesis generates random, unexpected and oversized values for the fields the
device reports. Parsing and every entity state must cope with them without
raising, so a misbehaving device can never crash or block the integration.
"""

from types import SimpleNamespace
from typing import Any

from hypothesis import HealthCheck, given, settings, strategies as st

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
    MAX_MAX_AGE,
    MIN_MAX_AGE,
    REDACTED,
    SENSITIVE_STATUS_KEYS,
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
from custom_components.philips_airpurifier_local.sensor import PhilipsFilterSensor, PhilipsSensor

from .const import DEVICE_ID, HOST, STATUS_AC2889

FUZZ = settings(
    max_examples=150,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)

# anything a broken or hostile device could put in a JSON field
device_values = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(),
    st.integers(min_value=10**300, max_value=10**400),
    st.floats(allow_nan=True, allow_infinity=True),
    st.text(max_size=200),
    st.lists(st.integers(), max_size=3),
    st.dictionaries(st.text(max_size=5), st.integers(), max_size=3),
)

status_keys = st.one_of(
    st.sampled_from(
        [
            PhilipsApi.MODEL_ID,
            PhilipsApi.NEW_MODEL_ID,
            PhilipsApi.NEW2_MODEL_ID,
            PhilipsApi.WIFI_VERSION,
            PhilipsApi.DEVICE_ID,
            PhilipsApi.NAME,
            "err",
        ]
    ),
    st.text(max_size=10),
)

statuses = st.dictionaries(status_keys, device_values, max_size=10)


def _entry_data(status: dict[str, Any]) -> SimpleNamespace:
    """Return the minimal runtime data an entity needs."""
    return SimpleNamespace(
        device_information=DeviceInformation(
            model="AC2889", name="Bedroom", device_id=DEVICE_ID, host=HOST
        ),
        coordinator=SimpleNamespace(status=status),
        latest_status=status,
    )


@FUZZ
@given(value=device_values)
def test_safe_conversions(value: Any) -> None:
    """Conversions return a usable number or None, never raise."""
    as_int = safe_int(value)
    as_float = safe_float(value)
    assert as_int is None or isinstance(as_int, int)
    assert as_float is None or isinstance(as_float, float)


@FUZZ
@given(value=device_values)
def test_clamp_max_age_bounds(value: Any) -> None:
    """The watchdog interval always stays within its bounds."""
    assert MIN_MAX_AGE <= clamp_max_age(value) <= MAX_MAX_AGE


@FUZZ
@given(status=statuses)
def test_resolve_model_never_raises(status: dict[str, Any]) -> None:
    """Model detection copes with any status."""
    model = resolve_model(status)
    assert model is None or isinstance(model, str)


@FUZZ
@given(status=statuses)
def test_redaction_never_leaks(status: dict[str, Any]) -> None:
    """Redacted data never contains the sensitive fields."""
    redacted = redact_status(status)
    for key in SENSITIVE_STATUS_KEYS & redacted.keys():
        assert redacted[key] == REDACTED


@FUZZ
@given(kind=st.sampled_from(sorted(SENSOR_TYPES)), value=device_values)
def test_sensor_states(kind: str, value: Any) -> None:
    """Sensor values and icons survive any device value."""
    sensor = PhilipsSensor(None, None, _entry_data({**STATUS_AC2889, kind: value}), kind)
    native = sensor.native_value
    assert not isinstance(native, dict | list | tuple | set)
    _ = sensor.icon


@FUZZ
@given(kind=st.sampled_from(sorted(FILTER_TYPES)), value=device_values, total=device_values)
def test_filter_sensor_states(kind: str, value: Any, total: Any) -> None:
    """Filter sensors survive any value and total."""
    total_key = FILTER_TYPES[kind][FanAttributes.TOTAL]
    sensor = PhilipsFilterSensor(
        None, None, _entry_data({**STATUS_AC2889, kind: value, total_key: total}), kind
    )
    _ = sensor.native_value
    _ = sensor.extra_state_attributes
    _ = sensor.icon


@FUZZ
@given(kind=st.sampled_from(sorted(BINARY_SENSOR_TYPES)), value=device_values)
def test_binary_sensor_states(kind: str, value: Any) -> None:
    """Binary sensors survive any device value."""
    sensor = PhilipsBinarySensor(None, None, _entry_data({**STATUS_AC2889, kind: value}), kind)
    _ = sensor.is_on


@FUZZ
@given(kind=st.sampled_from(sorted(LIGHT_TYPES)), value=device_values)
def test_light_states(kind: str, value: Any) -> None:
    """Lights survive any device value and keep brightness in range."""
    light = PhilipsLight(
        None, None, _entry_data({**STATUS_AC2889, kind.partition("#")[0]: value}), kind
    )
    _ = light.is_on
    brightness = light.brightness
    assert brightness is None or 0 <= brightness <= 255


@FUZZ
@given(kind=st.sampled_from(sorted(SELECT_TYPES)), value=device_values)
def test_select_states(kind: str, value: Any) -> None:
    """Selects survive any device value."""
    select = PhilipsSelect(
        None, None, _entry_data({**STATUS_AC2889, kind.partition("#")[0]: value}), kind
    )
    _ = select.current_option


@FUZZ
@given(kind=st.sampled_from(sorted(NUMBER_TYPES)), value=device_values)
def test_number_states(kind: str, value: Any) -> None:
    """Numbers survive any device value."""
    number = PhilipsNumber(None, None, _entry_data({**STATUS_AC2889, kind: value}), kind)
    native = number.native_value
    assert native is None or isinstance(native, float)


@FUZZ
@given(
    kind=st.sampled_from(sorted(HEATER_TYPES)),
    target=device_values,
    current=device_values,
    power=device_values,
)
def test_heater_states(kind: str, target: Any, current: Any, power: Any) -> None:
    """The heater survives any temperature and power values."""
    spec = HEATER_TYPES[kind]
    status = {
        **STATUS_AC2889,
        kind.partition("#")[0]: target,
        spec[FanAttributes.TEMPERATURE]: current,
        spec[FanAttributes.POWER]: power,
    }
    heater = PhilipsHeater(None, None, _entry_data(status), kind, {}, {}, {})
    for value in (heater._get_target_temperature(), heater._get_current_temperature()):
        assert value is None or isinstance(value, float)
    _ = (heater.hvac_action, heater.hvac_mode, heater.preset_mode)


@FUZZ
@given(status=st.dictionaries(st.sampled_from(sorted(STATUS_AC2889)), device_values, max_size=8))
def test_fan_states(status: dict[str, Any]) -> None:
    """The fan entity and its attributes survive any status values."""
    fan = PhilipsAC2889(None, None, _entry_data({**STATUS_AC2889, **status}))
    _ = fan.is_on
    _ = fan.preset_mode
    _ = fan.percentage
    _ = fan.icon
    _ = fan.extra_state_attributes
