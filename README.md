# Philips AirPurifier Local (CoAP)

[![Release](https://img.shields.io/github/v/release/HuisAutomatisering/fix-philips-airpurifier-coap?sort=semver&display_name=tag)](https://github.com/HuisAutomatisering/fix-philips-airpurifier-coap/releases/latest)
[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/docs/faq/custom_repositories)
[![HACS validation](https://github.com/HuisAutomatisering/fix-philips-airpurifier-coap/actions/workflows/hacs.yml/badge.svg?branch=master)](https://github.com/HuisAutomatisering/fix-philips-airpurifier-coap/actions/workflows/hacs.yml)
[![Hassfest](https://github.com/HuisAutomatisering/fix-philips-airpurifier-coap/actions/workflows/hassfest.yml/badge.svg?branch=master)](https://github.com/HuisAutomatisering/fix-philips-airpurifier-coap/actions/workflows/hassfest.yml)
[![Ruff](https://github.com/HuisAutomatisering/fix-philips-airpurifier-coap/actions/workflows/ruff.yml/badge.svg?branch=master)](https://github.com/HuisAutomatisering/fix-philips-airpurifier-coap/actions/workflows/ruff.yml)
[![Tests](https://github.com/HuisAutomatisering/fix-philips-airpurifier-coap/actions/workflows/tests.yml/badge.svg?branch=master)](https://github.com/HuisAutomatisering/fix-philips-airpurifier-coap/actions/workflows/tests.yml)
[![CodeQL](https://github.com/HuisAutomatisering/fix-philips-airpurifier-coap/actions/workflows/codeql.yml/badge.svg?branch=master)](https://github.com/HuisAutomatisering/fix-philips-airpurifier-coap/actions/workflows/codeql.yml)
[![Quality scale: Bronze](https://img.shields.io/badge/quality%20scale-Bronze%20(aligned)-cd7f32.svg)](#quality-scale)
[![OpenSSF Scorecard](https://api.scorecard.dev/projects/github.com/HuisAutomatisering/fix-philips-airpurifier-coap/badge)](https://scorecard.dev/viewer/?uri=github.com/HuisAutomatisering/fix-philips-airpurifier-coap)

[![Open your Home Assistant instance and open this repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=HuisAutomatisering&repository=fix-philips-airpurifier-coap&category=integration)

This is a `Local Push` integration for Philips air purifiers, humidifiers and fan heaters.
Currently only encrypted CoAP is implemented.

## About this fork

This repository is a maintained fork of
[kongo09/philips-airpurifier-coap](https://github.com/kongo09/philips-airpurifier-coap).
All device support comes from the original project and its contributors (see [Credits](#credits)).
It uses its own domain, `philips_airpurifier_local`, so it can be installed next to the original.
This fork adds:

- the `UnitOfDensity` fix for the deprecated `CONCENTRATION_MICROGRAMS_PER_CUBIC_METER` constant
- alignment with the Home Assistant quality scale **Bronze** tier
- hardening against a misbehaving device: bounded reconnect watchdog, growing pause between
  failed reconnects, one command at a time with a timeout, unusable values shown as unknown
  instead of errors (covered by property-based fuzz tests)
- privacy: device id, product id and name are redacted in the debug log and the id attributes are
  kept out of the recorder history
- signed releases: HACS installs a zip with a SLSA build provenance attestation
- CI for Ruff (incl. Bandit security rules), hassfest, HACS validation, tests, CodeQL and
  OpenSSF Scorecard, with all GitHub Actions pinned by commit

## Word of caution

The Philips CoAP interface was reverse engineered and the devices are known to stop
responding now and then. When that happens, the integration tries to reconnect
automatically; in stubborn cases a power cycle of the Philips device (and sometimes a
Home Assistant restart) is needed. Using the Philips app at the same time as Home Assistant
tends to make this worse, because both compete for the same encrypted session.

It all goes back to reverse engineering by @rgerganov, you can read about it here:
https://xakcop.com/post/ctrl-air-purifier/

Philips also offers a cloud API, but it is not public and only integrates with Google Home
and Alexa.

## Installation

This integration is installed through [HACS](https://hacs.xyz) as a custom repository.

1. Click the **Open in HACS** badge above, or in HACS open the menu (three dots) →
   **Custom repositories**, add `https://github.com/HuisAutomatisering/fix-philips-airpurifier-coap` with category **Integration**.
2. Download **Philips AirPurifier Local (CoAP)** in HACS.
3. Restart Home Assistant.

HACS downloads `philips_airpurifier_local.zip` from the release. You can verify that the zip was
built by this repository's release workflow with the GitHub CLI:

```bash
gh attestation verify philips_airpurifier_local.zip --repo HuisAutomatisering/fix-philips-airpurifier-coap
```

### Switching from the original integration

This integration has its own domain, so you can install it next to the original
*Philips AirPurifier (with CoAP)*. Your devices have to be added again:

1. Delete the purifier from the original integration first (**Settings** → **Devices &
   services**). This frees its entity IDs, so the new entities usually get the same IDs and your
   automations keep working.
2. Install this integration as described above and add the purifier (autodiscovery or IP address).
3. When everything works, remove the original integration in HACS. While both are installed,
   both may offer a discovered purifier: pick this one.

## Configuration

* The integration attempts to autodiscover your purifiers. Autodiscovery is based on the MAC
  address and original hostname of the devices. Home Assistant will notify you if that is
  successful.
* Alternatively, go to **Settings** → **Devices & services**
* Click **Add Integration**
* Search for **Philips AirPurifier Local** and select it
* Enter the hostname or IP address of your device
* The model type is detected automatically. You get a warning in the log if it is not supported.

Tip: give the device a fixed IP address (DHCP reservation in your router).

Note: `configuration.yaml` is not supported.

## Re-configuration

- If autodiscovery works for your device and network, Home Assistant will rediscover a device
  with a new IP address and update it automatically.
- Otherwise, open the integration under **Settings** → **Devices & services**, click
  **Configure** on the device and enter the new address. The integration checks that the device
  at that address is the same one.
- Adding the device again with its new address also works: Home Assistant recognises it and
  updates the existing entry.

## Removal

1. Go to **Settings** → **Devices & services** → **Philips AirPurifier Local**.
2. Open the menu (three dots) of each device entry and select **Delete**.
3. In HACS, open **Philips AirPurifier Local (CoAP)**, open the menu and select **Remove**.
4. Restart Home Assistant.

## Security and network

The Philips CoAP protocol uses a fixed, publicly known key and no authentication: every device
that can reach the purifier on your network can read and control it. The integration cannot
change that, so the protection has to come from the network:

- Put the purifier in an IoT VLAN and give it a fixed IP address (DHCP reservation).
- Allow only Home Assistant → purifier on **UDP 5683** (stateful, so the answers are allowed back).
- Block the purifier from reaching your other LAN devices.
- Optional: block the purifier's internet access. Then the Philips app and cloud stop working,
  but a firmware update can no longer switch off local control.
- Autodiscovery does not work across VLANs: add the purifier by IP address.

The integration itself opens no listening ports. It only uses an outgoing UDP (CoAP) connection
to the purifier, and serves its icons to the Home Assistant frontend.

Debug logs of this integration redact the device id, product id and name. The `coap` and
`aioairctrl` loggers print full device messages: only enable those temporarily.

Report vulnerabilities as described in [SECURITY.md](SECURITY.md).

## Quality scale

This integration is **aligned with the Home Assistant quality scale: Bronze**.
Home Assistant only grades core integrations, so this is a self-assessment and not an official
tier. The status per rule is documented in
[`quality_scale.yaml`](custom_components/philips_airpurifier_local/quality_scale.yaml).

## License

MIT, as declared by the upstream project in its `pyproject.toml`. The upstream repositories do
not contain a license file yet and the upstream code remains copyright of its authors. See
[LICENSE](LICENSE) and [NOTICE.md](NOTICE.md).

## Credits

- Original reverse engineering by @rgerganov: https://github.com/rgerganov/py-air-control
- The base of the integration by @betaboon: https://github.com/betaboon/philips-airpurifier-coap
- The rework by @Denaun: https://github.com/Denaun/philips-airpurifier-coap
- The current upstream integration and the `aioairctrl` library by @kongo09:
  https://github.com/kongo09/philips-airpurifier-coap - if this integration is useful to you,
  consider [buying kongo09 a coffee](https://www.buymeacoffee.com/kongo09)
- Many other contributors, notably @mhetzi, @Kraineff and @shexbeer
- Icon loading code by @thomasloven

## Supported models

Note: Some of these models seem to have a newer firmware that does not allow local connections anymore. If you buy the device with the intention to manage it via Home Assistant, make sure you can return it, if the integration doesn't work for you.

- AC0850/11 AWS_Philips_AIR
- AC0850/11 AWS_Philips_AIR_Combo
- AC0850/20 AWS_Philips_AIR
- AC0850/20 AWS_Philips_AIR_Combo
- AC0850/31 AWS_Philips_AIR
- AC0850/31 AWS_Philips_AIR_Combo
- AC0850/41 AWS_Philips_AIR
- AC0850/41 AWS_Philips_AIR_Combo
- AC0850/70 AWS_Philips_AIR
- AC0850/70 AWS_Philips_AIR_Combo
- AC0850/81
- AC0850/85
- AC0950
- AC0951
- AC1214
- AC1715
- AC2210
- AC2220
- AC2221
- AC2729
- AC2889
- AC2936
- AC2939
- AC2958
- AC2959
- AC3021
- AC3033
- AC3036
- AC3039
- AC3055
- AC3059
- AC3210
- AC3220
- AC3221
- AC3420
- AC3421
- AC3259
- AC3737
- AC3829
- AC3836
- AC3854/50
- AC3854/51
- AC3858/50
- AC3858/51
- AC3858/83
- AC3858/86
- AC4220
- AC4221
- AC4231
- AC4236
- AC4550
- AC4558
- AC5660
- AC5659
- AMF765
- AMF870
- CX3120
- CX5120
- CX3550
- HU1509
- HU1510
- HU4209
- HU4210
- HU5710


## Is your model not supported yet?

You can help to get us there.

Please open an issue and provide the raw status-data for each combination of modes and speeds for your model.

To aquire those information please follow these steps:

### Prepare the environment

Create yourself a virtual environment

```sh
python -m venv env
source ./env/bin/activate
```

Install `aioairctrl` package inside the virtual environment

```sh
python -m pip install aioairctrl
```

### Aquire raw status-data

- Use the philips-app to activate a mode or speed
- run the following command to aquire the raw data (still in the virtual environment)

```sh
aioairctrl --host $DEVICE_IP status --json
```

to exit the virtual environment, simply type

```sh
deactivate
```

## Debugging

To aquire debug-logs, add the following to your `configuration.yaml`:

```yaml
logger:
  logs:
    custom_components.philips_airpurifier_local: debug
    coap: debug
    aioairctrl: debug
```

logs should now be available in `home-assistant.log`


## Usage

### Entities

The integration provides `fan` entities for your devices which are [documented here](https://www.home-assistant.io/integrations/fan/). In addition, if your device is a humidifier or a 2-in-1 device, the integration will also provide a `humidifier` entity which is [documented here](https://www.home-assistant.io/integrations/humidifier/). The two entities work together, i.e. the `fan` controls power and settings for the fan operation while the `humidifier` adds extra capabilities.

It also provides a number of `sensor` entities for the air quality and other data measured by the device, as well as some diagnostic `sensor` entities with information about the filter or water fill level for humidifiers. A `switch` entity allows you to control the child lock function, should your device have one, or a set of other capabilities depending on your model. Finally, there are some `light` entities to control the display backlight and the brightness of the air quality display and some `select` entities to set other functions like timers. Few devices also have `number` entities to set certain values.

The goal is, to offer all existing functionality that is also available both, on the device itself but also in the official app.


### Services

Unlike the original `philips_airpurifier_local` integration, this version does not provide any additional services anymore. Everything can be controlled through the entities provided.


### Attributes

The `fan` entity has some additional attributes not captured with sensors. Specifcs depend on the model. The following list gives an overview:

| attribute |content | example |
|---|---|---|
| name: | Name of the device | bedroom |
| type: | Configured model | AC2729 |
| model_id: | Philips model ID | AC2729/10 |
| product_id: | Philips product ID | 85bc26fae62611e8a1e3061302926720 |
| device_id: | Philips device ID | 3c84c6c8123311ebb1ae8e3584d00715 |
| software_version: | Installed software version on device | 0.2.1 |
| wifi_version: | Installed WIFI version on device | AWS_Philips_AIR\@62.1 |
| error_code: | Philips error code | 49408 |
| error: | Error in clear text | no water |
| preferred_index: | State of preferred air quality index | `PM2.5`, `IAI` |
| runtime: | Time the device is running in readable text | 9 days, 10:44:41 |


### Icons

The integration also provides the original Philips icons for your use in the frontend. The icons can be accessed with the prefix `pap:` and should be visible in the icon picker. Credit for this part of the code goes to @thomasloven

| icon                                                                                           | name                    |
|------------------------------------------------------------------------------------------------|-------------------------|
| ![Preview](./custom_components/philips_airpurifier_local/icons/pap/power_button.svg)            | power_button            |
| ![Preview](./custom_components/philips_airpurifier_local/icons/pap/child_lock_button.svg)       | child_lock_button       |
| ![Preview](./custom_components/philips_airpurifier_local/icons/pap/child_lock_button_open.svg)  | child_lock_button_open  |
| ![Preview](./custom_components/philips_airpurifier_local/icons/pap/auto_mode_button.svg)        | auto_mode_button        |
| ![Preview](./custom_components/philips_airpurifier_local/icons/pap/fan_speed_button.svg)        | fan_speed_button        |
| ![Preview](./custom_components/philips_airpurifier_local/icons/pap/humidity_button.svg)         | humidity_button         |
| ![Preview](./custom_components/philips_airpurifier_local/icons/pap/light_dimming_button.svg)    | light_dimming_button    |
| ![Preview](./custom_components/philips_airpurifier_local/icons/pap/light_function.svg)          | light_function          |
| ![Preview](./custom_components/philips_airpurifier_local/icons/pap/ambient_light.svg)           | ambient_light           |
| ![Preview](./custom_components/philips_airpurifier_local/icons/pap/two_in_one_mode_button.svg)  | two_in_one_mode_button  |
| ![Preview](./custom_components/philips_airpurifier_local/icons/pap/timer_reset_button.svg)      | timer_reset_button      |
| ![Preview](./custom_components/philips_airpurifier_local/icons/pap/sleep_mode.svg)              | sleep_mode              |
| ![Preview](./custom_components/philips_airpurifier_local/icons/pap/auto_mode.svg)               | auto_mode               |
| ![Preview](./custom_components/philips_airpurifier_local/icons/pap/speed_1.svg)                 | speed_1                 |
| ![Preview](./custom_components/philips_airpurifier_local/icons/pap/speed_2.svg)                 | speed_2                 |
| ![Preview](./custom_components/philips_airpurifier_local/icons/pap/speed_3.svg)                 | speed_3                 |
| ![Preview](./custom_components/philips_airpurifier_local/icons/pap/allergen_mode.svg)           | allergen_mode           |
| ![Preview](./custom_components/philips_airpurifier_local/icons/pap/purification_only_mode.svg)  | purification_only_mode  |
| ![Preview](./custom_components/philips_airpurifier_local/icons/pap/two_in_one_mode.svg)         | two_in_one_mode         |
| ![Preview](./custom_components/philips_airpurifier_local/icons/pap/bacteria_virus_mode.svg)     | bacteria_virus_mode     |
| ![Preview](./custom_components/philips_airpurifier_local/icons/pap/pollution_mode.svg)          | pollution_mode          |
| ![Preview](./custom_components/philips_airpurifier_local/icons/pap/nanoprotect_filter.svg)      | nanoprotect_filter      |
| ![Preview](./custom_components/philips_airpurifier_local/icons/pap/filter_replacement.svg)      | filter_replacement      |
| ![Preview](./custom_components/philips_airpurifier_local/icons/pap/water_refill.svg)            | water_refill            |
| ![Preview](./custom_components/philips_airpurifier_local/icons/pap/prefilter_cleaning.svg)      | prefilter_clearning     |
| ![Preview](./custom_components/philips_airpurifier_local/icons/pap/prefilter_wick_cleaning.svg) | prefilter_wick_cleaning |
| ![Preview](./custom_components/philips_airpurifier_local/icons/pap/pm25.svg)                    | pm25                    |
| ![Preview](./custom_components/philips_airpurifier_local/icons/pap/iai.svg)                     | iai                     |
| ![Preview](./custom_components/philips_airpurifier_local/icons/pap/wifi.svg)                    | wifi                    |
| ![Preview](./custom_components/philips_airpurifier_local/icons/pap/reset.svg)                   | reset                   |
| ![Preview](./custom_components/philips_airpurifier_local/icons/pap/circulate.svg)               | circulate               |
| ![Preview](./custom_components/philips_airpurifier_local/icons/pap/clean.svg)                   | clean                   |
| ![Preview](./custom_components/philips_airpurifier_local/icons/pap/mode.svg)                    | mode                    |
| ![Preview](./custom_components/philips_airpurifier_local/icons/pap/pm25b.svg)                   | pm25b                   |
| ![Preview](./custom_components/philips_airpurifier_local/icons/pap/rotate.svg)                  | rotate                  |
| ![Preview](./custom_components/philips_airpurifier_local/icons/pap/oscillate.svg)               | oscillate               |
| ![Preview](./custom_components/philips_airpurifier_local/icons/pap/heating.svg)                 | heating                 |
| ![Preview](./custom_components/philips_airpurifier_local/icons/pap/gas.svg)                     | gas                     |
| ![Preview](./custom_components/philips_airpurifier_local/icons/pap/circle.svg)                  | circle                  |
| ![Preview](./custom_components/philips_airpurifier_local/icons/pap/temp_high.svg)               | temp_high               |
| ![Preview](./custom_components/philips_airpurifier_local/icons/pap/temp_medium.svg)             | temp_medium             |
| ![Preview](./custom_components/philips_airpurifier_local/icons/pap/temp_low.svg)                | temp_low                |

Note: you might have to clear your browser cache after installation to see the icons.
