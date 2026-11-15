# Yeelight Curtain BLE

Control **Yeelight Curtain Lights YLYDD-0053** from Home Assistant over Bluetooth,
using a local adapter or an ESPHome Bluetooth Proxy.

[![Add to HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=eldarsudden&repository=hass-yeelight-curtain-ble&category=integration)
[![Set up in Home Assistant](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=yeelight_curtain_ble)

The integration provides:

- Power and brightness controls.
- 19 regular animation presets, with an optional dashboard picker showing an icon beside every preset.
- Music Mode using the curtain's microphone, with 6 effects and 40 palettes.

**Experimental support.** After a factory reset, direct control from a Mac was
verified for connection, power, brightness, two regular presets and all six music
effects, without the Yeelight app. Operation through Home Assistant and an
ESPHome proxy still needs hardware verification. Only YLYDD-0053 (product ID
16787461) has been tested.

## Requirements

- **Home Assistant 2026.11.0 or later.** Development checks use 2026.11.1.
- Bluetooth configured in HA: a local adapter or an ESPHome proxy with active
  connections enabled and a free connection slot.
- A YLYDD-0053 curtain within Bluetooth range.

Close the Yeelight app and disconnect other BLE clients, such as a laptop test
script, before connecting. You do not need to reset a working curtain to install
this integration. On the tested unit, local commands worked immediately after a
factory reset, without a Yeelight account or app setup. Reconnection after
unplugging and reconnecting power was also verified.

## Install with HACS

Use the **first button** above to open the repository in your HACS installation.
Download the integration and restart HA, then use the **second button** to set up
the curtain. If My Home Assistant asks for your HA URL, enter it. HACS must
already be installed.

You can also add the repository manually:

1. Open **HACS → ⋮ → Custom repositories**.
2. Add `https://github.com/eldarsudden/hass-yeelight-curtain-ble` and select **Integration**.
3. Find **Yeelight Curtain BLE**, download it and restart Home Assistant.
4. Open **Settings → Devices & services → Add integration** and choose
   **Yeelight Curtain BLE**. If the curtain has already been discovered, choose
   **Configure** on its discovery card instead.
5. Select the curtain and confirm the connection check.

Setup only reads the device state. No integration YAML is required.
For installation without HACS, see [INSTALL.md](INSTALL.md).

## Updates

Published versions and their changes are available in
[Releases](https://github.com/eldarsudden/hass-yeelight-curtain-ble/releases) and the
[changelog](CHANGELOG.md). Update through HACS and restart Home Assistant.
The `main` branch is used for development; published releases are offered for installation.

If you use the optional presets card, update the version in its resource URL
and reload your dashboard after upgrading.

## ESPHome connection

Include the following in your ESP32 proxy configuration if these options are
not already enabled:

```yaml
esp32_ble_tracker:

bluetooth_proxy:
  active: true
```

This is a configuration fragment, not a complete firmware configuration.
Both the Bluetooth and ESPHome integrations must be configured in HA.
You do not need to enter the proxy's IP address: HA chooses an available adapter.
The curtain occupies one connection slot while the integration is connected.

## Controls

Five entities appear on the device page:

| Entity | Controls |
| --- | --- |
| Light | Power, brightness from 1–100%, regular effects |
| Preset | A separate list of 19 regular animations, including Christmas Tree, Rainbow and Bonfire |
| Music Mode | Sound response using the curtain's microphone |
| Music effect | Sound Wave, Shine, Spectrum, Converge, Bounce, Breath |
| Music palette | One of 40 palettes |

For music, turn on the light first, then enable Music Mode. Choosing a regular
effect stops Music Mode. Streaming audio from the phone's microphone is not supported.

The **Preset** list is independent of music settings. Choosing a preset turns on
the light and starts that animation. The same animations are available in the
light's effect selector. During Music Mode, no regular preset is shown as active.
The Preset entity's icon follows the confirmed animation.

With Music Mode off, effect and palette changes are saved for the next time you
enable it. With Music Mode on, changes apply immediately. The palette shows the
saved preference: its current colors cannot be read from the curtain.
The initial music selection is **Bounce / Father's Day**.

## Preset picker with icons

The included dashboard card displays a semantic icon **beside each of the 19
options** in its dropdown. It uses the regular Preset entity and the same HA
commands as the standard controls. The standard HA entity dropdown continues
to show text options.

After installing or updating the integration and restarting HA:

1. Add a dashboard resource with this URL and resource type **JavaScript module**:

   ```text
   /yeelight_curtain_ble/yeelight-curtain-presets.js?v=0.2.0
   ```

   For dashboards managed through the UI, open **Settings → Dashboards → ⋮ →
   Resources**. Enable Advanced mode in your user profile if this menu is hidden.
   If you manage resources in YAML, add the URL under `lovelace.resources` with
   `type: module` instead.

2. Add **Yeelight Curtain Presets** from the dashboard card picker, or use:

   ```yaml
   type: custom:yeelight-curtain-presets-card
   entity: select.your_curtain_preset
   title: Presets
   ```

Replace `select.your_curtain_preset` with your curtain's **regular Preset** entity,
not Music effect or Music palette. `title` is optional. The card follows the HA
interface language, with English as the default and Russian also available.
All card assets are served by your HA instance; no external scripts are loaded.

The curtain artwork remains the integration icon and the light's picture.

## Limitations

**Bonfire, Rainbow and Starry sky** are built into the curtain. The other 16
regular presets require an animation file upload; all files are included.
Uploads require large BLE packets: **ATT MTU 512** and support for 509-byte writes
on the adapter or proxy. If a GIF upload fails, check that connection's
capabilities. Power, brightness, built-in effects and Music Mode do not need GIF uploads.

Pure Color Mode, custom images, grouping multiple curtains and firmware updates
are not implemented. Rainbow, the Christmas Tree GIF transfer and switching all
six music effects with the Tranquil palette were tested on the device. Other
presets and palettes were reconstructed from app recordings and have not been
individually tested with the new client. Visual response to sound was not assessed.

## Troubleshooting

1. Close Yeelight and other apps that might hold the BLE connection.
2. Check that the adapter or proxy can see a device named `YLBT_CURT_…`.
3. For ESPHome, check `active: true` and a free connection slot.
4. Wait for the next connection check, which runs every 30 seconds.

If the problem persists, [open an issue](https://github.com/eldarsudden/hass-yeelight-curtain-ble/issues)
with your HA version, proxy or adapter model, attempted action and error message.
For detailed logs, merge the following into your existing `logger` configuration:

```yaml
logger:
  logs:
    custom_components.yeelight_curtain_ble: debug
    bleak_retry_connector: debug
```

Protocol details, development instructions, tests and packaging are documented
in [AGENTS.md](AGENTS.md).
