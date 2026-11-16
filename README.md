# Yeelight Curtain BLE

Control **Yeelight Curtain Lights YLYDD-0053** from Home Assistant over Bluetooth,
using a local adapter or an ESPHome Bluetooth Proxy.

[![Add to HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=eldarsudden&repository=hass-yeelight-curtain-ble&category=integration)
[![Set up in Home Assistant](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=yeelight_curtain_ble)

The integration provides:

- Local initial setup without a Yeelight account or app, including mounting-side selection.
- Power, brightness and a native color picker for a single color across the curtain.
- 19 regular animation presets, with an optional dashboard picker showing an icon beside every preset.
- Music Mode using the curtain's microphone, with 6 effects and 40 palettes.

**Experimental support.** After a factory reset, direct control from a Mac was
verified for connection, power, brightness, two regular presets and all six music
effects, without the Yeelight app. Native solid-color commands were subsequently
verified from a Mac, including readback and transitions to/from presets and music.
Operation through Home Assistant and an
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
5. Select the curtain and confirm the connection check. For a new or reset curtain,
   choose the controller mounting side when prompted.

Already configured curtains keep their mounting side. No integration YAML is required.
For installation without HACS, see [INSTALL.md](INSTALL.md).

## Initial setup without Yeelight

You can add the tested YLYDD-0053 directly to HA, without a Yeelight account,
app or pairing code. Close other BLE clients and follow the installation steps
above. For an unconfigured curtain, setup asks for **Mounting side: Left / Right**.
Choose the controller side you would select in Yeelight. The integration saves it
to the curtain and checks the device's response before completing setup.

An already configured curtain skips this step and keeps its current side. Setup
never changes placement until you explicitly choose it. You do not need to reset
a working curtain to add it.

To change placement later, open the device page and use **Mounting side** under
**Configuration**. If you factory-reset a curtain already added to HA, use this
same control to initialize it again; removing and re-adding the integration is
unnecessary. The side is stored on the curtain and read back, rather than being
only an HA preference.

A fresh factory reset followed by the actual setup-flow code was verified over
Mac Bluetooth without opening Yeelight: initial setup was unset, choosing Right
completed setup, and colors, brightness, Rainbow and power off worked. A new
connection confirmed that Right was retained. This verifies the tested unit and
firmware; actual HA/ESPHome proxy hardware operation remains unverified.

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
The curtain occupies one connection slot while connected. By default, the
integration keeps that connection open; see the connection setting below.

## Connection settings

Open **Settings → Devices & services → Yeelight Curtain BLE** and choose
**Configure** for your curtain. The **Persistent BLE connection** option is
**enabled by default**, including for existing installations.

- **Enabled:** keep the BLE session open between commands and polls, receive
  device notifications and occupy one adapter/proxy connection slot.
- **Disabled:** connect for a command and its state readback, or a scheduled
  poll, then disconnect. A GIF upload and its activation finish in the same
  session before disconnecting. A successful disconnect releases the connection
  slot between operations.

Polling remains every **30 seconds** in both modes. With persistence disabled,
commands may take longer because each operation reconnects, and external changes
are discovered at the next successful poll rather than through notifications
while disconnected. A state read also runs at startup. Complete power, brightness,
color and effect state cannot currently be decoded reliably from this model's
advertisements, so passive scanning does not replace these reads.
Releasing the connection does not itself turn off the light.
Music Mode behavior after disconnect has not been verified on hardware; use a
persistent connection if your curtain exits Music Mode when the session closes.

Saving the option automatically reloads this integration; an HA restart is not
needed. Music effect and palette preferences are preserved. This setting frees
the slot between operations, but does not coordinate ownership with another BLE
client that may connect to the curtain.

When every reachable adapter is already establishing another BLE connection,
the integration waits up to 30 seconds before trying the curtain. If they remain
busy, the operation fails without starting another connection. Existing persistent
sessions with other devices do not count as connection attempts. This reduces
overlap but cannot reserve the proxy against other integrations.

Before each connection attempt, the integration checks whether a scanner still
reports this curtain in its occupied slots. After disconnect, it waits for this
address to disappear from the reported allocations. Another free slot does not
count as confirmation. Scanners without allocation reporting use backend cleanup
checks only.

If Home Assistant discards its internal client after a failed connection, the
integration keeps its own reference to that session's BLE backend and sends
disconnect through it. For ESPHome, this requests release of the curtain alone,
even when the backend already reports a disconnected local link. The reference
is released only after cleanup and the allocation check succeed.

If teardown fails, times out or leaves a reported allocation, the integration
logs a warning and blocks new connections until cleanup succeeds. It retains that
backend across integration reloads and waits separately for disconnect rather
than applying the shorter command timeout. Repeatedly restarting HA does not
clear a slot already orphaned inside a proxy. Disable this integration, restart
the affected proxy, then re-enable the integration to clear existing orphaned
slots. This also interrupts other BLE devices using that proxy.

On-demand control and repeated disconnect/reconnect were verified on a real
curtain over Mac Bluetooth with version 0.6.2. Actual Home Assistant/ESPHome
slot release still needs hardware verification.

## Controls

Six standard entities appear on the device page. Importing a custom GIF also
adds a separate GIF selector:

| Entity | Controls |
| --- | --- |
| Light | Power, brightness from 1–100%, a single color, regular effects |
| Preset | A separate list of 19 regular animations, including Christmas Tree, Rainbow and Bonfire |
| Music Mode | Sound response using the curtain's microphone |
| Music effect | Sound Wave, Shine, Spectrum, Converge, Bounce, Breath |
| Music palette | One of 40 palettes |
| Mounting side | Left / Right, under Configuration; also initializes a reset curtain |

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

## Single color

Open the curtain's light controls in Home Assistant and use the standard color
picker. The chosen color fills the entire curtain. Brightness remains adjustable.
Choosing a color turns on the light and stops Music Mode or the current animation;
choosing a regular preset starts that animation again.

For white, move saturation to zero. This is white mixed from the RGB LEDs, not
adjustable white color temperature. Color commands use the curtain's native HSV
mode; they do not upload a GIF or need the large MTU used by animation uploads.
The displayed hue and saturation come from device readback and notifications.
During an animation, no uniform color is reported. The light's mode readout may
show **Music mode**, **Custom GIF** or **Unknown effect**; these are status labels,
not additional options in the regular preset list. Brightness stays available.

The standard HA action accepts RGB colors too and converts them to the supported
hue/saturation format:

```yaml
action: light.turn_on
target:
  entity_id: light.your_curtain
data:
  rgb_color: [0, 255, 0]
  brightness_pct: 50
```

Use either a color or a regular effect in one call. A request containing both is
rejected before any device writes.

Native color was verified using this integration's client, coordinator and light
entity over a Mac's Bluetooth: red, green, blue, white, brightness changes,
transitions to/from Rainbow and Music Mode, and on-demand reconnects. The initial
color and brightness were restored afterward. This is separate from actual
HA/ESPHome proxy hardware verification, which is still pending.

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

## Custom GIFs

Import your own animations from **Settings → Devices & services → Yeelight
Curtain BLE → Configure**:

1. Enter a **GIF name** and choose a **GIF file** from your computer or phone.
2. Save. The file is validated and added to this curtain's library; importing does
   not send commands to the curtain. The integration reloads automatically.
3. Choose the animation in **GIF — last requested** on the device page to upload
   and play it. This turns on the light and stops Music Mode.

Repeat to add more animations. Reusing a name replaces its file. To remove
animations, select them under **Remove from library** in the same dialog and save.
Files are stored privately under your HA configuration directory in
`yeelight_curtain_ble/<entry_id>/`, outside the installed component. HACS updates
preserve them. Include this directory and HA's configuration storage in backups.
The library is separate for each curtain and is not served as public web content.

For this first version, prepare a GIF with:

- **19 pixels wide × 25 pixels high**, matching the captured single-curtain files.
- **1–48 frames**, with a maximum file size of **128520 bytes** (255 protocol blocks).
- A valid GIF file, including decodable frames and the closing trailer.

These are conservative integration limits based on our captures and current
transport, not a complete specification of the firmware. Files are checked during
import and before playback. Resizing, cropping and GIF conversion are not included.
Large-packet BLE support is still required: MTU 512 and 509-byte writes.

Use the standard select action in automations; it also works to replay the same file:

```yaml
action: select.select_option
target:
  entity_id: select.your_curtain_gif_last_requested
data:
  option: My animation
```

Replace the entity ID and name with your own. The ordinary 19 presets and their
icon picker remain separate from the custom GIF library and music settings.

**Experimental playback:** transfer and activation use the observed GIF renderer
command, sharing the numeric marker used by Christmas Tree. A separate custom
firmware slot has not been confirmed. Choosing the normal Christmas Tree preset
uploads its original bundled animation again. No bundled file is modified.

The firmware returns a numeric effect marker, not the GIF filename or hash.
**GIF — last requested** therefore shows the last successfully requested library
item while the effect marker is compatible, not a device-read file identity or
proof that it is still playing. When a regular preset or Music Mode is selected,
the GIF selection becomes unknown so you can choose the same file again; its
`last_requested` attribute retains the previous choice. While
the shared marker may represent a custom upload, the regular Preset entity does
not incorrectly label it Christmas Tree. Transfer acknowledgments and state
readback are checked, but arbitrary custom GIF rendering has not yet been visually
verified on hardware.

## Limitations

**Bonfire, Rainbow and Starry sky** are built into the curtain. The other 16
regular presets require an animation file upload; all files are included.
Uploads require large BLE packets: **ATT MTU 512** and support for 509-byte writes
on the adapter or proxy. If a GIF upload fails, check that connection's
capabilities. Power, brightness, built-in effects and Music Mode do not need GIF uploads.

Importing non-GIF images, grouping multiple curtains and firmware updates are not
implemented. Rainbow, the Christmas Tree GIF transfer and switching all
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
