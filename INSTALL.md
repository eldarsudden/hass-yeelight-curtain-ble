# Install Yeelight Curtain BLE

You need Home Assistant 2026.11.0 or later, a configured Bluetooth adapter or
ESPHome Bluetooth Proxy with active connections, and a YLYDD-0053 curtain.
Support is experimental; operation through HA and ESPHome still needs hardware verification.

## HACS

[![Add to HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=eldarsudden&repository=hass-yeelight-curtain-ble&category=integration)

The button opens the repository in your HACS installation. Download the
integration and restart HA. Install HACS first if it is not already available.
Alternatively, add the repository through the menu:

1. Open **HACS → ⋮ → Custom repositories**.
2. Add `https://github.com/eldarsudden/hass-yeelight-curtain-ble`, type **Integration**.
3. Download **Yeelight Curtain BLE** and restart HA.
4. Close Yeelight on your phone and disconnect other BLE clients.
5. In **Settings → Devices & services**, configure the discovered curtain or
   choose **Add integration → Yeelight Curtain BLE**.

## Manual installation

1. Copy `custom_components/yeelight_curtain_ble` from the release archive or
   repository into your HA configuration directory. On HA OS, the resulting
   manifest path is `/config/custom_components/yeelight_curtain_ble/manifest.json`.
   For Container, use the directory mounted at `/config`.
2. Restart Home Assistant.
3. Close Yeelight on your phone and disconnect other BLE clients.
4. In **Settings → Devices & services**, configure the discovered curtain or
   choose **Add integration → Yeelight Curtain BLE**.

Select the curtain and confirm the connection check. Setup only reads the device
state. No YAML is required for the integration itself.
You do not need to reset a working curtain to install it. On the tested unit,
local control from a Mac worked immediately after a factory reset without
initial setup in the Yeelight app.

After installation and restart, this button opens integration setup:

[![Set up in Home Assistant](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=yeelight_curtain_ble)

## Connection settings

After setup, open the curtain's **Configure** dialog under **Settings → Devices &
services → Yeelight Curtain BLE**. **Persistent BLE connection** is enabled by
default. Disable it to release the adapter/proxy slot after each command with
readback and after each poll. Polling remains every 30 seconds. Saving reloads
the integration automatically and keeps music preferences.

## Custom GIF library

In the same **Configure** dialog, enter a GIF name and choose a file. Use a
19×25-pixel GIF with 1–48 frames and at most 128520 bytes. Save to import it;
then choose it in the separate **GIF — last requested** entity to upload and play.
Adding a file does not change the curtain until you select it for playback.
Reusing a name replaces the file. Use **Remove from library** to delete entries.

Files are stored in `yeelight_curtain_ble/<entry_id>/` inside the HA configuration
directory, outside the HACS component. Back them up together with HA's configuration
storage. Playback is experimental: arbitrary user GIFs have not been visually
verified on hardware. The selector shows the last requested file, not its identity
read from the curtain. See the README for protocol limitations and automation examples.

## Optional preset picker with icons

Add this dashboard resource as a **JavaScript module**:

```text
/yeelight_curtain_ble/yeelight-curtain-presets.js?v=0.2.0
```

Then add a card using your curtain's regular Preset entity:

```yaml
type: custom:yeelight-curtain-presets-card
entity: select.your_curtain_preset
title: Presets
```

The card shows an icon beside every regular preset. Use the Preset entity,
not a music selector. After future updates, change the resource URL version and
reload the dashboard.

ESPHome configuration, controls, full card setup and limitations are described
in the [repository README](https://github.com/eldarsudden/hass-yeelight-curtain-ble#readme).
