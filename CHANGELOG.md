# Changelog

## 0.3.0 — 2026-11-15

- Add a **Persistent BLE connection** option to the curtain's Configure dialog.
  It defaults to enabled, preserving existing connection behavior.
- With persistence disabled, connect for each complete command and its state
  readback, or for a poll, then release the BLE adapter/proxy slot. GIF upload,
  activation and verification share one uninterrupted session.
- Release on-demand connections on success, errors and cancellation. Keep state
  polling every 30 seconds; device notifications are unavailable while disconnected
  and commands may take longer because they reconnect.
- Apply option changes by automatically reloading the integration. Preserve music
  effect and palette preferences, including changes made while the form is open.
- Add English and Russian option descriptions and connection-mode documentation.

On-demand operation was tested with a simulated peripheral. Hardware behavior
through HA/ESPHome and Music Mode persistence after disconnect still need
verification.

## 0.2.0 — 2026-11-15

- Add an optional dashboard card with a semantic icon beside every one of the
  19 regular presets in its dropdown. Configure it as
  `custom:yeelight-curtain-presets-card` with the curtain's regular Preset entity.
- Serve the card, preset catalog and curtain artwork locally through Home
  Assistant. Add the resource
  `/yeelight_curtain_ble/yeelight-curtain-presets.js?v=0.2.0` as a JavaScript module
  after updating and restarting HA; see the README for setup.
- Support keyboard navigation, pending-command feedback and accessible errors.
  The selected preset follows confirmed HA state; music selectors are rejected.
- Keep the curtain artwork as the integration icon and use it for the light's
  picture. No Yeelight app logo is included.
- Translate the README, installation guide, development documentation and
  changelog into English. Retain Russian interface translations.
- Synchronize the descriptions of existing releases from the English changelog
  without changing their tags or downloadable assets.

The standard HA dropdown continues to use text options. Icons beside individual
options are available in the new card. Support remains experimental; actual
HA/ESPHome proxy operation still needs hardware verification.

## 0.1.2 — 2026-11-15

- Assign a semantic icon to each of the 19 regular presets: a tree for Christmas
  Tree, a rainbow for Rainbow, a campfire for Bonfire, and others.
- Update the Preset entity's icon to match the active animation. Show a generic
  animation icon during Music Mode or when the regular preset is unknown.
- Preserve preset names and existing automation parameters.
- Document successful local control from a Mac after a factory reset and a full
  power cycle, without the Yeelight app.

The standard HA dropdown does not display a separate icon beside each option.
In this release, the icon is displayed for the selected preset.

## 0.1.1 — 2026-11-15

First published release for installation and updates through HACS.

- Add a separate Preset selector with 19 regular animations.
- Separate regular presets from music effects and palettes. Choosing a regular
  preset stops Music Mode; the active preset is confirmed by reading device state.
- Keep regular effects available in the light card.
- Add buttons for HACS installation and Home Assistant setup.

Includes power, brightness, regular presets, Music Mode, 6 music effects and
40 music palettes.

This version is experimental. Connection, state reads and power off were tested
on a real device from a Mac. HA/ESPHome proxy operation and the remaining commands
with the new client still needed verification at the time of this release.
The 16 GIF presets require an MTU of at least 512.

## 0.1.0 — 2026-11-15

Initial integration distributed from the `main` branch without a GitHub Release.

- Add local BLE control for YLYDD-0053 through the HA Bluetooth API.
- Implement power, brightness, regular effects, Music Mode and its settings.
- Include reconstructed GIF presets, translations and tests with a simulated device.
