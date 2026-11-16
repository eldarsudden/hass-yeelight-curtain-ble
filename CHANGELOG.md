# Changelog

## 0.6.3 — 2026-11-16

- Check reported Bluetooth slot allocations before every connection attempt,
  including retries inside the connection helper. Do not open a session while
  any scanner still reports this curtain address as allocated.
- After disconnect, wait for this address to disappear from reported allocations;
  another free slot is not evidence that this curtain was released. Keep cleanup
  pending and block reconnects if the allocation remains.
- Cover the real HA Bluetooth wrapper failure path: it can drop its low-level
  backend after a failed connect, making a later disconnect a no-op. The new
  allocation check prevents retrying over the retained proxy slot.
- Add tests for duplicate allocations after restart, delayed allocation updates
  and the actual HA wrapper with a simulated leaking peripheral backend.

This prevents new attempts over a reported retained allocation; it cannot reclaim
slots already orphaned in proxy firmware. Disable the integration and restart the
affected proxy once to clear existing stuck slots. Scanners without allocation
reporting retain the backend cleanup checks. Physical ESPHome verification is
still pending; the tests do not establish the cause of every firmware slot leak.

## 0.6.2 — 2026-11-15

- Keep a disconnected backend until its resource cleanup completes. A link-down
  callback or `is_connected == false` is not treated as proof of proxy-slot release.
- Stop JSON and GIF notifications before disconnecting, and still call backend
  disconnect after unsolicited link loss or partially completed notification setup.
- Give teardown its own 35-second wait instead of the 10-second JSON request
  timeout. Shield in-progress cleanup from caller cancellation and retain it
  across timeouts; do not open another connection until it completes successfully.
- Track backends before connection setup awaits. Clean a failed attempt before
  the retry connector can reuse it; stop internal retries if cleanup is unconfirmed.
- Allow one active integration owner per device address across config flows,
  coordinator startup and reloads. Retain stopped owners with pending cleanup
  so setup retries cannot abandon them and allocate another session.
- Close the connection gate on shutdown, cancel an in-flight connect, ignore
  stale-session notifications and register cleanup on Home Assistant stop.
- Add regression coverage for late callbacks, queued commands, cancellation,
  partial setup and disconnect failures that falsely report a closed local link.
- Verify nine real on-demand sessions over Mac Bluetooth: initial read, red at
  10/50/100%, green, blue, Rainbow, power off and restoration. All nine backends
  reported disconnected. Observed advertisements were identical across those
  brightness/color changes, so passive reception cannot replace full state reads.

These changes address integration-side resource leaks; they cannot prove that
a proxy released a slot when its backend reports success incorrectly. Existing
orphaned slots may require a proxy restart with the integration disabled.
A full passive advertisement decoder is not established for YLYDD-0053, so state
reads at startup and the 30-second polling interval are retained. Actual HA/ESPHome
proxy hardware verification remains pending.

## 0.6.1 — 2026-11-15

- Keep the BLE client reference if disconnect times out or the client still
  reports a live connection. Later operations reuse that client instead of
  opening another connection and potentially consuming another proxy slot.
- Log disconnect failures and clients that remain connected, making proxy
  disconnect problems visible in the Home Assistant log.

## 0.6.0 — 2026-11-15

- Add local initial setup without a Yeelight account or app. New and reset curtains
  prompt for the controller mounting side before any setup writes.
- Preserve placement on already configured curtains. Add a **Mounting side**
  configuration entity to change sides or initialize an existing entry after reset.
- Read setup status and placement from the device. Verify initialization by
  readback; a successful acknowledgment alone is insufficient. An explicit retry
  avoids rewriting a setup that the device has already confirmed.
- Keep setup changes serialized with other operations and support persistent or
  on-demand BLE connections without losing music or custom GIF preferences.
- Verify a fresh factory reset followed by the actual setup flow over Mac BLE,
  without opening Yeelight: initially unset, Right selected, entry created, red
  with brightness adjustment, green, blue, Rainbow and power off confirmed.
  Reconnection confirms that the right-side setup is retained.

Actual HA/ESPHome proxy hardware operation and other firmware remain unverified.

## 0.5.0 — 2026-11-15

- Add a native color picker to the existing light entity using HA's hue/saturation
  color mode. Standard HA RGB action parameters are converted to HSV by HA.
- Implement the captured `set_hsv [hue, saturation, "smooth", 0]` command. A color
  request turns on the light and stops Music Mode; regular presets remain separate.
- Read `color_mode`, `hue` and `sat` from the device and process color notifications.
  Reject invalid values and unconfirmed changes instead of publishing a requested color.
- Preserve brightness in both solid-color and animation modes. Report descriptive
  status labels for music, custom GIFs and unknown effects without adding them to
  the 19 selectable regular presets.
- Support native color with persistent connections enabled or disabled. No GIF
  upload, MTU 512 or new dashboard resource is required for the color picker.
- Verify red, green, blue and RGB white through direct Mac BLE commands and RGB
  readback. Verify ten operations through the integration's client, coordinator
  and light entity: color/brightness, presets, music and on-demand reconnects.
  Restore the initial device color and brightness after testing.

Actual HA/ESPHome proxy hardware operation still needs verification. White is
mixed RGB, not white color-temperature control. Simultaneous color and preset
requests are rejected before sending commands.

## 0.4.0 — 2026-11-15

- Add a private custom GIF library per curtain, imported using HA's native file
  selector in the Configure dialog. Support named imports, replacement and removal.
  Importing a file does not send device commands.
- Validate 19×25-pixel GIFs with 1–48 frames and at most 128520 bytes. Decode all
  frames, use content-addressed storage and revalidate checksums before playback.
- Keep user files outside the HACS component so updates preserve them. Remove
  unused managed files when the integration reloads after library changes.
- Add a separate **GIF — last requested** selector. Selecting an item uploads and
  activates it; automations use the standard `select.select_option` action.
- Keep the entire transfer, activation and readback in one serialized BLE session,
  including when persistent connections are disabled. Never activate after a
  failed upload or report a rejected command as successful.
- Reuse the observed GIF renderer marker instead of inventing a custom firmware
  slot. Avoid identifying a custom upload as the regular Christmas Tree preset.
  The GIF selector explicitly reports the last request, not a readable file identity.
- Preserve the existing regular preset picker, music settings and connection option.
  Add English/Russian UI text and documentation.

Custom GIF rendering is experimental and has not been visually verified on the
curtain. Transfer acknowledgments and numeric effect readback do not prove file
identity or correct animation. Limits are conservative integration bounds based
on captured single-curtain files; MTU 512 and 509-byte writes are required.

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
