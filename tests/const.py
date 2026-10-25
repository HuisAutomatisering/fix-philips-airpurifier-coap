"""Shared test data for the Philips AirPurifier tests."""

from custom_components.philips_airpurifier_coap.const import CONF_DEVICE_ID, CONF_MODEL, CONF_STATUS
from homeassistant.const import CONF_HOST, CONF_NAME

HOST = "192.168.1.50"
NEW_HOST = "192.168.1.51"
DEVICE_ID = "3c84c6c8123311ebb1ae8e3584d00715"
OTHER_DEVICE_ID = "ffffffffffffffffffffffffffffffff"
MAC = "aa:bb:cc:dd:ee:ff"

# raw status of an AC2889 (original CoAP API generation)
STATUS_AC2889 = {
    "name": "Bedroom",
    "type": "AC2889",
    "modelid": "AC2889/10",
    "swversion": "0.2.1",
    "DeviceId": DEVICE_ID,
    "ProductId": "85bc26fae62611e8a1e3061302926720",
    "WifiVersion": "AWS_Philips_AIR@62.1",
    "pwr": "1",
    "mode": "P",
    "om": "1",
    "uil": "1",
    "aqil": 100,
    "ddp": "1",
    "pm25": 5,
    "iaql": 1,
    "runtime": 123456789,
}

# exact model match ("AC0850/81" is a key of model_to_class)
STATUS_EXACT = {
    **STATUS_AC2889,
    "modelid": "AC0850/81",
    "name": "Living room",
}

# model + firmware match ("AC0850/11 AWS_Philips_AIR")
STATUS_LONG = {
    **STATUS_AC2889,
    "modelid": "AC0850/11",
    "WifiVersion": "AWS_Philips_AIR@64.3",
    "name": "Office",
}

STATUS_UNSUPPORTED = {
    **STATUS_AC2889,
    "modelid": "XX9999/10",
}

STATUS_NO_DEVICE_ID = {key: value for key, value in STATUS_AC2889.items() if key != "DeviceId"}

ENTRY_DATA = {
    CONF_HOST: HOST,
    CONF_MODEL: "AC2889",
    CONF_NAME: "Bedroom",
    CONF_DEVICE_ID: DEVICE_ID,
    CONF_STATUS: STATUS_AC2889,
}
