"""Philips (pap:) icons for entities.

Home Assistant's icons.json only accepts Material Design Icons, so icons.json holds
MDI fallbacks and the original Philips icons are returned from code instead.
The structure mirrors icons.json: platform -> translation key -> default/state.
The pap: icon set itself is served by this integration (see main.js).
"""

PAP_ENTITY_ICONS: dict[str, dict[str, dict]] = {
    "fan": {"pap": {"state": {"off": "pap:power_button"}}},
    "humidifier": {"pap": {"state": {"off": "pap:power_button"}}},
    "climate": {
        "pap": {
            "state": {
                "off": "pap:power_button",
                "auto": "pap:auto_mode",
                "fan_only": "pap:circulate",
                "heat": "pap:heating",
            }
        }
    },
    "binary_sensor": {
        "humidification": {
            "state": {"on": "pap:two_in_one_mode", "off": "pap:purification_only_mode"}
        }
    },
    "sensor": {
        "indoor_allergen_index": {"default": "pap:iai"},
        "pm25": {"default": "pap:pm25b"},
        "gas": {"default": "pap:gas"},
    },
    "switch": {
        "child_lock": {
            "default": "pap:child_lock_button",
            "state": {"on": "pap:child_lock_button", "off": "pap:child_lock_button_open"},
        }
    },
    "light": {"display_backlight": {"default": "pap:light_dimming_button"}},
    "select": {
        "function": {
            "default": "pap:mode",
            "state": {
                "purification": "pap:purification_only_mode",
                "purification_humidification": "pap:two_in_one_mode",
                "fan": "pap:clean",
                "circulation": "pap:circulate",
                "heating": "pap:heating",
            },
        },
        "lamp_mode": {
            "default": "pap:light_function",
            "state": {
                "off": "pap:light_function",
                "air_quality": "pap:light_function",
                "ambient_light_mode": "pap:light_function",
                "humidity": "pap:light_function",
            },
        },
        "ambient_light_mode": {
            "default": "pap:ambient_light",
            "state": {
                "off": "pap:ambient_light",
                "warm": "pap:ambient_light",
                "dawn": "pap:ambient_light",
                "calm": "pap:ambient_light",
                "breath": "pap:ambient_light",
            },
        },
        "preferred_index": {
            "state": {"indoor_allergen_index": "pap:iai", "pm25": "pap:pm25b", "gas": "pap:gas"}
        },
    },
    "number": {"oscillaton": {"default": "pap:oscillate"}},
}
