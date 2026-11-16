"""Coordinate reads and serialized control operations through HA Bluetooth."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
from copy import deepcopy
from datetime import timedelta
from functools import partial
from pathlib import Path

from bleak.exc import BleakError
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection
from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .client import CurtainClient, CurtainError
from .const import (
    DEFAULT_MUSIC_EFFECT,
    DEFAULT_MUSIC_PALETTE,
    DEFAULT_PERSISTENT_CONNECTION,
    DOMAIN,
    MOUNTING_SIDES,
    OPT_MUSIC_EFFECT,
    OPT_MUSIC_PALETTE,
    OPT_PERSISTENT_CONNECTION,
)
from .custom_gif import (
    GIF_EFFECT,
    OPT_CUSTOM_GIFS,
    OPT_CUSTOM_SLOT,
    OPT_LAST_CUSTOM_GIF,
    read_custom_gif,
)

_LOGGER = logging.getLogger(__name__)
_ROOT = Path(__file__).parent
ERRORS = (CurtainError, BleakError, TimeoutError, OSError)
SLOT_RELEASE_TIMEOUT = 5.0
SLOT_CHECK_INTERVAL = 0.1
ADAPTER_IDLE_TIMEOUT = 30.0


def allocated_curtain_slots(hass: HomeAssistant, address: str) -> list[str]:
    """Inspect reported allocations, not free-slot counts or local link state."""
    key = address.upper()
    return [
        scanner.name
        for scanner in bluetooth.async_current_scanners(hass)
        if (allocation := scanner.get_allocations()) is not None
        and any(item.upper() == key for item in allocation.allocated)
    ]


async def wait_for_slot_release(hass: HomeAssistant, address: str) -> None:
    """Do not allocate another session while a proxy still reports this address."""
    try:
        async with asyncio.timeout(SLOT_RELEASE_TIMEOUT):
            while sources := allocated_curtain_slots(hass, address):
                await asyncio.sleep(SLOT_CHECK_INTERVAL)
    except TimeoutError as error:
        raise CurtainError(
            "Curtain still occupies a reported Bluetooth slot on "
            f"{', '.join(sources)}; reconnect blocked until the allocation clears. "
            "If it remains stuck, disable this integration and restart that proxy"
        ) from error


async def wait_for_idle_adapter(hass: HomeAssistant, address: str) -> None:
    """Defer when every reachable adapter is establishing another connection.

    Established persistent connections are allowed. This does not reserve an
    adapter or coordinate other integrations; HA still selects the connection.
    """
    waiting = False
    try:
        async with asyncio.timeout(ADAPTER_IDLE_TIMEOUT):
            while True:
                paths = bluetooth.async_scanner_devices_by_address(hass, address, True)
                if not paths or any(path.scanner.connections_in_progress() == 0 for path in paths):
                    return
                if not waiting:
                    _LOGGER.debug("Deferring curtain connection: reachable Bluetooth adapters are connecting other devices")
                    waiting = True
                await asyncio.sleep(SLOT_CHECK_INTERVAL)
    except TimeoutError as error:
        raise CurtainError(
            "Reachable Bluetooth adapters are still connecting other devices; "
            "curtain connection deferred without allocating another slot"
        ) from error


def load_catalog() -> dict:
    """Load bundled metadata off the HA event loop."""
    return json.loads((_ROOT / "catalog.json").read_text(encoding="utf-8"))


async def connect(hass: HomeAssistant, address: str, disconnected_callback, *, client_created=None, client_cleanup=None):
    """Use the connectable adapter/proxy chosen by Home Assistant."""
    lookup = partial(bluetooth.async_ble_device_from_address, hass, address, connectable=True)
    device = lookup()
    if device is None:
        raise CurtainError("No connectable Bluetooth adapter/proxy can currently reach the curtain")
    client_class = BleakClientWithServiceCache
    if client_created is not None:
        class TrackedClient(BleakClientWithServiceCache):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                client_created(self)

            async def connect(self, *args, **kwargs):
                # A HA wrapper may discard its failed low-level backend. Its
                # disconnect can then return without releasing the proxy slot.
                # Inspect allocations before *every* connector retry as well.
                await wait_for_slot_release(hass, address)
                await wait_for_idle_adapter(hass, address)
                # Allocation reports may have changed while waiting.
                await wait_for_slot_release(hass, address)
                client_created(self)
                try:
                    return await super().connect(*args, **kwargs)
                except BaseException as error:
                    if not isinstance(error, asyncio.CancelledError):
                        _LOGGER.warning(
                            "Curtain BLE connect failed before cleanup (%s): %s",
                            type(error).__name__, str(error), exc_info=True,
                        )
                    # establish_connection reuses a client for internal retries.
                    # Do not let its next attempt run over an unclean backend.
                    if client_cleanup is not None:
                        await client_cleanup()
                    raise

            async def disconnect(self):
                await super().disconnect()
                # A free slot for another address is not proof of our release.
                await wait_for_slot_release(hass, address)

        client_class = TrackedClient
    return await establish_connection(
        client_class,
        device,
        device.name or address,
        disconnected_callback=disconnected_callback,
        ble_device_callback=lookup,
        max_attempts=3,
    )


def create_client(hass: HomeAssistant, address: str, on_props=None) -> CurtainClient:
    """One live owner per address, including config flows and setup retries.

    Retain stopped owners with unconfirmed cleanup across integration reloads.
    This registry contains no proxy credentials and uses only HA's BLE backend.
    """
    registry = hass.data.setdefault(f"{DOMAIN}_connections", {"owners": {}, "locks": {}})
    key = address.upper()
    lock = registry["locks"].setdefault(key, asyncio.Lock())

    async def connector(disconnected):
        async with lock:
            previous = registry["owners"].get(key)
            if previous is not None and previous is not client:
                if not previous.closed:
                    raise CurtainError("Another curtain session already owns this device")
                # A failed setup/reload must not abandon a backend that could
                # still own a proxy slot, even if it locally reports link down.
                await previous.disconnect()
            registry["owners"][key] = client
            return await connect(
                hass, address, disconnected, client_created=client.track_client,
                client_cleanup=client.cleanup_failed_connect,
            )

    client = CurtainClient(connector, on_props)
    return client


class CurtainCoordinator(DataUpdateCoordinator[dict]):
    """Only publish actual device state; preferences are stored separately."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, catalog: dict) -> None:
        super().__init__(
            hass, _LOGGER, name=DOMAIN, config_entry=entry, update_interval=timedelta(seconds=30)
        )
        self.entry = entry
        self.persistent_connection = entry.options.get(
            OPT_PERSISTENT_CONNECTION, DEFAULT_PERSISTENT_CONNECTION
        )
        self.address = entry.data["address"]
        self.catalog = catalog
        self.presets = {p["display_name"]: p for p in catalog["presets"]}
        self.client = create_client(hass, self.address, self._props)
        self._closing = False
        self._operation_lock = asyncio.Lock()

    @property
    def preset(self) -> str | None:
        """Return the observed regular preset only while music is inactive."""
        if not self.data or self.data["music"].get("on"):
            return None
        if self.entry.options.get(OPT_CUSTOM_SLOT) and self.data["effect"][:2] == GIF_EFFECT:
            # Firmware reports a numeric GIF marker, not a filename or content hash.
            return None
        return next(
            (
                name
                for name, preset in self.presets.items()
                if self.data["effect"][:2] == [preset["effect_id"], preset["custom_id"]]
            ),
            None,
        )

    @property
    def music_effect(self) -> str | None:
        if self.data and self.data["music"].get("on"):
            effect_id = self.data["music"].get("effect_id")
            return next(
                (k for k, v in self.catalog["music_effects"].items() if v == effect_id),
                None,
            )
        return self.entry.options.get(OPT_MUSIC_EFFECT, DEFAULT_MUSIC_EFFECT)

    @property
    def music_palette(self) -> str:
        # Device responses omit palatte: this is a preference, not an observed color state.
        return self.entry.options.get(OPT_MUSIC_PALETTE, DEFAULT_MUSIC_PALETTE)

    @callback
    def _props(self, props: dict) -> None:
        if self._closing or not self.data or not self.last_update_success:
            return
        state = deepcopy(self.data)
        try:
            if props.get("power") in ("on", "off"):
                state["power"] = props["power"]
            if "bright" in props and 0 <= int(props["bright"]) <= 100:
                state["bright"] = int(props["bright"])
            for name in ("adapter_set", "adapter_side"):
                if name in props:
                    if isinstance(props[name], bool) or str(props[name]) not in ("0", "1"):
                        raise ValueError("Invalid mounting state")
                    state[name] = int(props[name])
            if "mic_music_mode" in props:
                music = json.loads(props["mic_music_mode"])
                if isinstance(music, dict) and music.get("on") in (0, 1):
                    state["music"] = music
            if "fx_effect" in props:
                effect = json.loads(props["fx_effect"])
                if all(isinstance(effect.get(k), int) for k in ("effect_id", "custom_id")):
                    state["effect"] = [effect["effect_id"], effect["custom_id"]]
            if "color_mode" in props:
                mode = int(props["color_mode"])
                if not 0 <= mode <= 255:
                    raise ValueError("Invalid color mode")
                state["color_mode"] = mode
                if mode != 3:
                    state.pop("hs_color", None)
            if state.get("color_mode") == 3 and ("hue" in props or "sat" in props):
                previous = state.get("hs_color", (None, None))
                hue = props.get("hue", previous[0])
                saturation = props.get("sat", previous[1])
                if hue is not None and saturation is not None:
                    if any(isinstance(value, bool) or not isinstance(value, (str, int)) for value in (hue, saturation)):
                        raise ValueError("Invalid HSV color")
                    hs = (int(hue), int(saturation))
                    if not 0 <= hs[0] < 360 or not 0 <= hs[1] <= 100:
                        raise ValueError("Invalid HSV color")
                    state["hs_color"] = hs
        except (ValueError, TypeError, AttributeError):
            _LOGGER.debug("Ignoring malformed properties notification")
            return
        self.async_set_updated_data(state)

    async def _async_update_data(self) -> dict:
        async with self._operation_lock:
            if self._closing:
                raise UpdateFailed("Curtain coordinator is stopping")
            try:
                return await self.client.read_state()
            except ERRORS as error:
                _LOGGER.debug("Curtain state read failed before cleanup", exc_info=True)
                self.client.invalidate()
                raise UpdateFailed(str(error)) from error
            finally:
                if not self.persistent_connection or self.client.cleanup_required:
                    try:
                        await self.client.disconnect()
                    except CurtainError as error:
                        raise UpdateFailed(str(error)) from error

    async def _execute(self, operation, verify) -> None:
        async with self._operation_lock:
            if self._closing:
                raise HomeAssistantError("Curtain coordinator is stopping")
            try:
                await operation()
                state = await self.client.read_state()
            except ERRORS as error:
                _LOGGER.debug("Curtain command failed before cleanup", exc_info=True)
                self.client.invalidate()
                self.async_set_update_error(UpdateFailed(str(error)))
                raise HomeAssistantError(str(error)) from error
            finally:
                if not self.persistent_connection or self.client.cleanup_required:
                    try:
                        await self.client.disconnect()
                    except CurtainError as error:
                        self.async_set_update_error(UpdateFailed(str(error)))
                        raise HomeAssistantError(str(error)) from error
            self.async_set_updated_data(state)
            if not verify(state):
                raise HomeAssistantError("Curtain did not confirm the requested state")

    async def async_power(self, enabled: bool) -> None:
        target = "on" if enabled else "off"

        async def operation():
            await self.client.set("set_power", [target, "smooth", 500])
            await asyncio.sleep(0.6)

        await self._execute(operation, lambda state: state["power"] == target)

    async def async_mounting_side(self, side: str) -> None:
        if side not in MOUNTING_SIDES:
            raise HomeAssistantError("Unknown mounting side")
        await self._execute(
            lambda: self.client.configure_mounting(side),
            lambda state: state["adapter_set"] == 1 and state["adapter_side"] == MOUNTING_SIDES[side],
        )

    async def async_light_on(
        self, brightness: int | None, effect: str | None, hs_color: tuple | None = None
    ) -> None:
        if hs_color is not None:
            if effect is not None:
                raise HomeAssistantError("Choose either a color or a preset")
            if (
                not isinstance(hs_color, (tuple, list))
                or len(hs_color) != 2
                or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in hs_color)
                or not 0 <= hs_color[0] <= 360
                or not 0 <= hs_color[1] <= 100
            ):
                raise HomeAssistantError("Invalid hue or saturation")
            hs_color = (round(hs_color[0]) % 360, round(hs_color[1]))
        if effect is not None and effect not in self.presets:
            raise HomeAssistantError(f"Unknown effect: {effect}")
        preset = self.presets.get(effect)
        gif = None
        if preset is not None and "file" in preset:
            gif = await self.hass.async_add_executor_job(
                (_ROOT / "presets" / preset["file"]).read_bytes
            )
            if hashlib.sha256(gif).hexdigest() != preset["sha256"]:
                raise HomeAssistantError("Preset GIF is missing or corrupted")

        async def operation():
            await self.client.set("set_power", ["on", "smooth", 500])
            if brightness is not None:
                await self.client.set("set_scene", ["bright", brightness, 0])
            if hs_color is not None:
                await self.client.set("set_ps", ["mic_music_mode", '{"on":0}'])
                await self.client.set("set_hsv", [*hs_color, "smooth", 0])
            if preset is not None:
                if self.data and self.data["music"].get("on"):
                    await self.client.set("set_ps", ["mic_music_mode", '{"on":0}'])
                if gif is not None:
                    await self.client.upload(gif)
                    if [preset["effect_id"], preset["custom_id"]] == GIF_EFFECT:
                        self.hass.config_entries.async_update_entry(
                            self.entry, options={**self.entry.options, OPT_CUSTOM_SLOT: False}
                        )
                await self.client.set(
                    "set_fx_effect",
                    [preset["effect_id"], preset["custom_id"], 1, preset["options"]],
                )
            await asyncio.sleep(0.6)

        def verify(state):
            return (
                state["power"] == "on"
                and (brightness is None or state["bright"] == brightness)
                and (
                    hs_color is None
                    or (
                        not state["music"].get("on")
                        and state.get("color_mode") == 3
                        and state["effect"][:2] == [0, 0]
                        and state.get("hs_color") is not None
                        and state["hs_color"][1] == hs_color[1]
                        and (hs_color[1] == 0 or state["hs_color"][0] == hs_color[0])
                    )
                )
                and (
                    preset is None
                    or (
                        not state["music"].get("on")
                        and state["effect"][:2] == [preset["effect_id"], preset["custom_id"]]
                    )
                )
            )

        await self._execute(operation, verify)

    async def async_custom_gif(self, name: str) -> None:
        """Upload a library GIF using the observed GIF renderer activation command."""
        metadata = self.entry.options.get(OPT_CUSTOM_GIFS, {}).get(name)
        if metadata is None:
            raise HomeAssistantError("Unknown custom GIF")
        try:
            gif = await self.hass.async_add_executor_job(
                read_custom_gif, self.hass, self.entry.entry_id, metadata
            )
        except (ValueError, OSError) as error:
            raise HomeAssistantError(f"Cannot read custom GIF: {error}") from error

        async def operation():
            await self.client.set("set_power", ["on", "smooth", 500])
            await self.client.set("set_ps", ["mic_music_mode", '{"on":0}'])
            # Mark ambiguity before touching the shared renderer, even if upload fails.
            self.hass.config_entries.async_update_entry(
                self.entry, options={**self.entry.options, OPT_CUSTOM_SLOT: True}
            )
            await self.client.upload(gif)
            await self.client.set("set_fx_effect", [*GIF_EFFECT, 1, {}])
            await asyncio.sleep(0.6)

        await self._execute(
            operation,
            lambda state: state["power"] == "on"
            and not state["music"].get("on")
            and state["effect"][:2] == GIF_EFFECT,
        )
        self.hass.config_entries.async_update_entry(
            self.entry, options={**self.entry.options, OPT_LAST_CUSTOM_GIF: name}
        )
        self.async_update_listeners()

    async def async_music(
        self, enabled: bool, effect: str | None = None, palette: str | None = None
    ) -> None:
        selection = {}

        async def operation():
            # Resolve unspecified preferences after acquiring the operation lock.
            # Rapid changes of effect and palette must not overwrite one another.
            selected_effect = effect or self.music_effect or DEFAULT_MUSIC_EFFECT
            selected_palette = palette or self.music_palette
            if (
                selected_effect not in self.catalog["music_effects"]
                or selected_palette not in self.catalog["palettes"]
            ):
                raise HomeAssistantError("Unknown music effect or palette")
            selection.update(
                effect=selected_effect,
                palette=selected_palette,
                effect_id=self.catalog["music_effects"][selected_effect],
            )
            params = {"on": int(enabled)}
            if enabled:
                params.update(
                    effect_id=selection["effect_id"],
                    palatte=self.catalog["palettes"][selected_palette],
                )
            await self.client.set(
                "set_ps", ["mic_music_mode", json.dumps(params, separators=(",", ":"))]
            )

        await self._execute(
            operation,
            lambda state: (
                state["music"].get("on") == int(enabled)
                and (not enabled or state["music"].get("effect_id") == selection["effect_id"])
            ),
        )
        if enabled:
            self._save_music_preferences(selection["effect"], selection["palette"])

    def _save_music_preferences(self, effect: str, palette: str) -> None:
        self.hass.config_entries.async_update_entry(
            self.entry,
            options={
                **self.entry.options,
                OPT_MUSIC_EFFECT: effect,
                OPT_MUSIC_PALETTE: palette,
            },
        )
        self.async_update_listeners()

    async def async_music_preference(self, key: str, value: str) -> None:
        effect = value if key == OPT_MUSIC_EFFECT else self.music_effect or DEFAULT_MUSIC_EFFECT
        palette = value if key == OPT_MUSIC_PALETTE else self.music_palette
        if effect not in self.catalog["music_effects"] or palette not in self.catalog["palettes"]:
            raise HomeAssistantError("Unknown music effect or palette")
        if self.data and self.data["music"].get("on"):
            await self.async_music(
                True,
                effect=value if key == OPT_MUSIC_EFFECT else None,
                palette=value if key == OPT_MUSIC_PALETTE else None,
            )
        else:
            self._save_music_preferences(effect, palette)

    async def async_shutdown(self) -> None:
        self._closing = True
        self.client.stop()
        await super().async_shutdown()
        async with self._operation_lock:
            try:
                await self.client.close()
            except CurtainError:
                # The per-address registry retains the owner and blocks the next
                # setup until its cleanup is confirmed. Do not break HA unload.
                _LOGGER.warning("Curtain shutdown left an unconfirmed BLE cleanup")
