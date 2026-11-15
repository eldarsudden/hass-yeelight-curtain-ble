# Yeelight Curtain BLE development

This file contains development instructions and technical findings. User-facing
documentation belongs in `README.md`; the standalone installation guide shipped
in the component archive is `INSTALL.md`. Keep packet analysis, capture history
and development commands out of the README.

## Supported device and verification

- Model: Yeelight Curtain Lights YLYDD-0053, product ID 16787461.
- Architecture: custom integration → Home Assistant Bluetooth API → local
  adapter or ESPHome Bluetooth Proxy with active GATT connections → curtain.
- Independent connection, state reads and power off were verified on a real
  device from a Mac. Power off was confirmed by an `ok` response, a `power: off`
  notification, a subsequent read and the user's observation.
- The integration transport was separately verified by reading the device with
  Bleak 3.0.2.
- After the user's factory reset on 2026-11-15, the same `CurtainClient` over Mac
  Bluetooth verified reads, power on/off, brightness at 10/50/100%, Rainbow,
  Christmas Tree GIF transfer, all six music effects with the Tranquil palette,
  Music Mode off and a new BLE connection. All 16 JSON state-changing commands
  returned `ok`; 18 steps were confirmed by reads. This tested unit did not need
  binary initialization, explicit pairing, an account or the app. Visual response
  to sound was not assessed.
- Following a physical power cycle, five more responses were received without
  initialization; power remained `off`, brightness 100% and the preset ID matched
  Christmas Tree. This verifies reads after a cold start, not visual persistence
  of the GIF or sound response.
- Component loading, config flow, entities, errors and GIF transfer were checked
  in HA 2026.11.1 using a simulated peripheral. These tests do not verify a proxy.
- Actual HA/ESPHome proxy operation still needs verification. Other regular
  presets and music palettes are supported by stock-app captures, but have not
  been individually tested on the device with the new client.
- OTA, grouping curtains and Pure Color Mode are not implemented.

Keep capture evidence, simulated tests and hardware verification distinct in the
documentation. Do not claim support for other models or HA versions without testing.

## Project layout

- `custom_components/yeelight_curtain_ble/`: installable integration.
- `client.py`: BLE session, JSON requests, notifications and file transfer.
- `coordinator.py`: adapter selection through HA, serialized operations, state
  verification and polling.
- `light.py`, `switch.py`, `select.py`: HA entities.
- `protocol.py`: JSON and file-block encoding.
- `catalog.json`, `presets/`: effect catalog, music palettes and 16 GIFs.
- `frontend.py`, `www/`: exact public static routes and optional presets card.
- `brand/`: original curtain artwork for the integration. Do not replace it with
  the Yeelight app logo. `www/curtain.png` is the same artwork for the card and light.
- `tests/`: protocol, client, coordinator, config flow, HA loading and asset-route tests.
- `tools/build_release.py`: installable component archive.
- `tools/prepare_hacs_repo.py`: allowlisted export to `dist/hacs-repository` and
  a repository archive for publication.

The research workspace may also contain `analysis/`, `ble_probe.py`,
`decode_capture.py`, `requirements.txt` and `.captures/`. These are excluded from
the public export. Their absence in a GitHub clone must not prevent installation,
normal tests or packaging.

## HA integration and state

Use the HA Bluetooth API and `bleak-retry-connector`. Select devices through
`bluetooth.async_ble_device_from_address(..., connectable=True)`; advertisements
from a proxy that cannot connect are insufficient. The proxy IP is not an
integration option. A Mac CoreBluetooth UUID cannot replace the BLE address in HA.

Default to a persistent BLE session for notifications and commands. The
`persistent_connection` option defaults to true for existing and new entries.
When false, release the connection in `finally` after each coordinator poll or
complete command plus readback, including errors and cancellation, while still
holding the operation lock. Keep a GIF upload, activation and readback in one
session. Do not disconnect after individual JSON requests. Polling remains every
30 seconds; notifications are unavailable between on-demand sessions.
The options flow reloads the entry when saved; music preference updates must not
trigger reloads or overwrite this option. Preserve current preferences when
submitting the options form. Serialize all operations,
including state reads and GIF uploads. On disconnect, fail pending requests;
a stale client's callback must not reset a newer session. Do not automatically
retry state-changing commands.

Verify the response and actual state after a command. Do not replace observed
state with the requested value. Current behavior uses readback after changes,
notifications and polling every 30 seconds. An update failure makes entities
unavailable; the next update attempts to reconnect.

The music palette is a saved preference because the device does not return its
colors. Do not present it as observed state. With Music Mode off, save effect
and palette choices without sending a command. Apply changes while music is on.
Do not substitute a known effect for an unknown music effect. Enabling Music
Mode does not itself turn on the light; a regular effect stops Music Mode.

Regular animations are exposed by a separate Preset `select` entity and the
light's effects. Both show the same confirmed preset from device state. The
regular preset is unknown while music is active. Keep the 19 regular presets
separate from the six music effects and 40 palettes.

Each regular preset's semantic MDI icon lives in `catalog.json`. The Preset
entity shows the confirmed animation's icon, or a generic animation icon for
Music Mode or an unknown preset. Preserve option values and preset names: users
may already depend on them in automations.

## Optional dashboard card

The native HA select dropdown does not render per-option icons. The separate
`custom:yeelight-curtain-presets-card` renders them without changing entity
options. It calls `select.select_option` through HA, never BLE directly. The
selected value must follow HA state, including after errors. Disable controls
while a command is pending or the entity is unavailable. Reject music selectors.
Preserve keyboard navigation, focus handling and English/Russian localization.

`frontend.py` registers only the card JS, catalog and curtain PNG as exact public
static paths. Do not expose component directories or private research files.
All runtime assets are local; do not add remote scripts or CDN dependencies.
Frontend asset changes require a new version in the documented resource URL.
Users register the dashboard resource once; setup does not edit their dashboards.

## Reconstructed protocol

Characteristics use the base UUID `0000xxxx-0000-1000-8000-00805f9b34fb`:

| Short UUID | Purpose |
| --- | --- |
| AE3B | JSON command writes |
| AE3C | JSON responses and notifications |
| AE3D | File-block writes |
| AE3E | File-transfer acknowledgments |

JSON is UTF-8, ends with CRLF and contains a request ID. Handle partial messages
and multiple messages in one notification; match responses to pending requests by ID.

Confirmed methods:

| Action | Method and parameters |
| --- | --- |
| Power | `set_power`, `["on" / "off", "smooth", 500]` |
| Brightness | `set_scene`, `["bright", percent, 0]` |
| Regular effect | `set_fx_effect`, `[effect_id, custom_id, 1, options]` |
| Music | `set_ps`, `["mic_music_mode", json_string]` |

`json_string` contains nested JSON. Disabling music uses `{"on":0}`; enabling
uses `on`, `effect_id` and `palatte`, an array of 16 ARGB colors. Preserve the
spelling **`palatte`**: this is the actual protocol field.
Music IDs: Sound Wave 87, Shine 85, Spectrum 86, Converge 83, Bounce 88, Breath 84.
Use `catalog.json` for complete regular-effect parameters and palettes; commands
from other Yeelight models are not evidence for this protocol.

Bonfire, Rainbow and Starry sky use built-in effects. The other 16 presets need
a GIF upload before activation. Verify each file's SHA-256 against the catalog.
Do not activate an effect if its transfer did not complete successfully.

Each file block is 509 bytes: `01`, block number, block number XOR `FF`, 504 data
bytes and CRC-16/CCITT initialized to `FFFF`, in big endian. Pad the final block
with `1A`. End the transfer with `04`. Expect `06` on AE3E after every block and
at the end. ATT MTU ≥ 512 and write-without-response size ≥ 509 bytes are required.
Arbitrary splitting, retransmission and block-number overflow are not supported
by the captures; do not silently introduce them.

Binary FE88/FE89 initialization was observed on Android, but independent Mac
commands worked without it, including after a factory reset. The current JSON
transport needs no additional initialization for the tested unit. Do not add
pairing/reset or replay captured binary packets based on assumptions; other
units and firmware versions have not been verified separately.

## Checks and packaging

Development was checked on Python 3.14 and HA 2026.11.1. Use an isolated
environment and the dependencies in `requirements-dev.txt`:

```sh
python3.14 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
.venv/bin/ruff check custom_components tests tools
.venv/bin/python tools/build_release.py
```

Capture reconstruction tests are optional when local recordings are available;
they may be skipped in a public clone. Do not make personal logs a test dependency.

Match verification to the change. For Markdown edits, check links, consistency
with behavior and the export. Packaging changes require an archive-content
check. Test command handling, errors and connections with relevant tests; record
hardware verification separately. For the dashboard card, check browser behavior,
keyboard navigation, errors, state readback and light/dark appearance.

`build_release.py` creates the manifest version's archive and SHA-256 in `dist/`.
It includes the component, catalog, GIFs, brand images, local card assets and
`INSTALL.md`. Tests, research materials and development environments are excluded.

## HACS versions and releases

The version source is `custom_components/yeelight_curtain_ble/manifest.json`.
Use stable `MAJOR.MINOR.PATCH` numbers without a `v` prefix: fixes increment PATCH,
new features increment MINOR, incompatible changes increment MAJOR. Retain the
experimental-support notice before 1.0. Never rewrite published tags or replace
published release assets. Release descriptions may be corrected or translated
when the user requests it; keep the historical behavior accurate.

For each release, update the manifest and add `## X.Y.Z — YYYY-MM-DD` to
`CHANGELOG.md`. Keep public documentation and release notes in English; retain
localized HA interface files. Run the checks, then build against the exact tag:

```sh
.venv/bin/python tools/build_release.py --tag 0.2.0
```

Here `0.2.0` is an example; use the new version for the next release. The build
fails on a tag/manifest mismatch or missing changelog notes. Loading tests must
not require manual version edits. Packaging tests also run without HA:

```sh
python3 -m unittest discover -s tests -p test_release.py -v
```

After exporting and committing in the public repository, push main, then create
and push the matching version tag:

```sh
git push origin main
git tag -a 0.2.0 -m 'Release 0.2.0'
git push origin 0.2.0
```

`.github/workflows/release.yml` runs on tags, validates packaging and publishes a
GitHub Release with notes, ZIP and SHA-256. It uses the built-in `GITHUB_TOKEN`;
no separate PAT is needed. Verify workflow success, matching tag/manifest,
release files and checksum. A Git tag alone does not create a HACS release.

`.github/workflows/release-notes.yml` synchronizes existing release descriptions
from their matching English changelog sections when the changelog changes on
main. It changes descriptions only, preserving tags and assets. Verify the
published descriptions and unchanged asset digests after a translation.

HACS installs the component from the repository at the selected tag.
`zip_release` is not enabled: the attached ZIP with `custom_components/...`
paths is intended for manual installation. `hide_default_branch` hides the
development branch from version selection; `render_readme` displays the README.

## Export and publication

```sh
.venv/bin/python tools/prepare_hacs_repo.py
```

The export copies canonical `README.md`, `AGENTS.md`, `INSTALL.md`, metadata,
code, assets, tests and packaging tools using an explicit allowlist. The README
is not generated from the installation guide. Before publishing, inspect
`dist/publication-review.json` and the exported Git diff. An existing `.git`
directory is preserved. Do not publish raw Bluetooth logs, bugreports, APKs,
videos, screenshots, device addresses or phone data. Do not bulk-add files from
the research workspace.

Public repository: `eldarsudden/hass-yeelight-curtain-ble`.
In a normal clone, commit there. In the research workspace, export and commit in
`dist/hacs-repository`. The user prefers local Git. Check the remote and diff;
use a normal push without rewriting history. Do not change global Git settings;
set author identity for an individual commit when necessary.

## Additional research on a computer

These commands apply only to a workspace containing `ble_probe.py` and
`requirements.txt`. The script uses the computer's Bluetooth, not a proxy.
On macOS, grant Bluetooth access to the terminal. Close Yeelight and other BLE
clients. Create a separate environment for research dependencies to avoid changing
HA's pinned dependencies:

```sh
python3.14 -m venv .venv-probe
.venv-probe/bin/python -m pip install -r requirements.txt
.venv-probe/bin/python ble_probe.py scan --output scan.json
.venv-probe/bin/python ble_probe.py inspect --address 'ADDRESS_FROM_SCAN_JSON' --output gatt.json
```

Find the curtain in the scan; compare scans with power on and off if necessary.
On a Mac, the address is a UUID specific to that computer. `inspect` discovers
services and disconnects: it sends no control commands, enables no notifications
and does not explicitly pair. A `gatt.json` alone does not reveal control commands.

## Android BLE capture

1. Enable **Bluetooth HCI snoop log** in Developer options, choosing full logging
   if available. Restart Bluetooth.
2. Start recording before connecting Yeelight to include the session beginning.
3. Perform actions about five seconds apart and note the times: off, on,
   brightness 10/50/100%, several effects and music on/off. Record effect and
   palette names, or record the app screen, to build the catalog.
4. Reconnect and repeat power and one effect to check a fresh session.
5. Extract the full HCI log from a bugreport or the manufacturer's log.
   AOSP `btsnooz.py` only helps when its data is present. On OnePlus, Feedback
   logs containing ACL packets proved more useful than cached HCI data.
6. Disable logging afterward. Keep original data local; prefer an extracted
   BLE log over a full bugreport for analysis.

`decode_capture.py` parses btsnoop/H4 and reassembles fragmented ACL packets.
Match screen recordings to commands using the action sequence; check the OEM
log's time zone and timestamps separately. Sound response stopping after phone
disconnection does not by itself prove the absence of a microphone: the device
may exit Music Mode when the connection closes.

Local findings, when `analysis/` is available: `2026-11-14-capture.md`,
`2026-11-14-logkit.md`, `2026-11-15-recording.md`, `2026-11-15-music.md`,
`2026-11-15-mac-connection.md` and `2026-11-15-factory-reset.md`.
Private research files must not become dependencies of public documentation.

## Sources

- [Home Assistant Bluetooth API](https://contributors.home-assistant.io/core/integrations/bluetooth/)
- [ESPHome Bluetooth Proxy](https://esphome.io/components/bluetooth_proxy/)
- [Bleak Retry Connector](https://github.com/Bluetooth-Devices/bleak-retry-connector)
- [Bleak scanning](https://bleak.readthedocs.io/en/latest/api/scanner.html)
- [Bleak connections and GATT](https://bleak.readthedocs.io/en/latest/api/client.html)
- [Android HCI snoop logging](https://source.android.com/docs/core/connect/bluetooth/verifying_debugging)
- [Bedside/Candela driver](https://github.com/hcoohb/hass-yeelightbt/blob/master/custom_components/yeelight_bt/yeelightbt.py)
  targets other devices; its commands do not establish the YLYDD-0053 protocol.
