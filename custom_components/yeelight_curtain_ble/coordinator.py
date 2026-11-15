"""Coordinate reads and serialized control operations through HA Bluetooth."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
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
    OPT_MUSIC_EFFECT,
    OPT_MUSIC_PALETTE,
    OPT_PERSISTENT_CONNECTION,
)

_LOGGER = logging.getLogger(__name__)
_ROOT = Path(__file__).parent
ERRORS = (CurtainError, BleakError, TimeoutError, OSError)


def load_catalog() -> dict:
    """Load bundled metadata off the HA event loop."""
    return json.loads((_ROOT / "catalog.json").read_text(encoding="utf-8"))


async def connect(hass: HomeAssistant, address: str, disconnected_callback):
    """Use the connectable adapter/proxy chosen by Home Assistant."""
    lookup = partial(bluetooth.async_ble_device_from_address, hass, address, connectable=True)
    device = lookup()
    if device is None:
        raise CurtainError("No connectable Bluetooth adapter/proxy can currently reach the curtain")
    return await establish_connection(
        BleakClientWithServiceCache,
        device,
        device.name or address,
        disconnected_callback=disconnected_callback,
        ble_device_callback=lookup,
        max_attempts=3,
    )


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
        self.client = CurtainClient(partial(connect, hass, self.address), self._props)
        self._operation_lock = asyncio.Lock()

    @property
    def preset(self) -> str | None:
        """Return the observed regular preset only while music is inactive."""
        if not self.data or self.data["music"].get("on"):
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
        if not self.data or not self.last_update_success:
            return
        state = deepcopy(self.data)
        try:
            if props.get("power") in ("on", "off"):
                state["power"] = props["power"]
            if "bright" in props and 0 <= int(props["bright"]) <= 100:
                state["bright"] = int(props["bright"])
            if "mic_music_mode" in props:
                music = json.loads(props["mic_music_mode"])
                if isinstance(music, dict) and music.get("on") in (0, 1):
                    state["music"] = music
            if "fx_effect" in props:
                effect = json.loads(props["fx_effect"])
                if all(isinstance(effect.get(k), int) for k in ("effect_id", "custom_id")):
                    state["effect"] = [effect["effect_id"], effect["custom_id"]]
        except (ValueError, TypeError, AttributeError):
            _LOGGER.debug("Ignoring malformed properties notification")
            return
        self.async_set_updated_data(state)

    async def _async_update_data(self) -> dict:
        async with self._operation_lock:
            try:
                return await self.client.read_state()
            except ERRORS as error:
                await self.client.disconnect()
                raise UpdateFailed(str(error)) from error
            finally:
                if not self.persistent_connection:
                    await self.client.disconnect()

    async def _execute(self, operation, verify) -> None:
        async with self._operation_lock:
            try:
                await operation()
                state = await self.client.read_state()
            except ERRORS as error:
                await self.client.disconnect()
                self.async_set_update_error(UpdateFailed(str(error)))
                raise HomeAssistantError(str(error)) from error
            finally:
                if not self.persistent_connection:
                    await self.client.disconnect()
            self.async_set_updated_data(state)
            if not verify(state):
                raise HomeAssistantError("Curtain did not confirm the requested state")

    async def async_power(self, enabled: bool) -> None:
        target = "on" if enabled else "off"

        async def operation():
            await self.client.set("set_power", [target, "smooth", 500])
            await asyncio.sleep(0.6)

        await self._execute(operation, lambda state: state["power"] == target)

    async def async_light_on(self, brightness: int | None, effect: str | None) -> None:
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
            if preset is not None:
                if self.data and self.data["music"].get("on"):
                    await self.client.set("set_ps", ["mic_music_mode", '{"on":0}'])
                if gif is not None:
                    await self.client.upload(gif)
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
                    preset is None
                    or (
                        not state["music"].get("on")
                        and state["effect"][:2] == [preset["effect_id"], preset["custom_id"]]
                    )
                )
            )

        await self._execute(operation, verify)

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
        await super().async_shutdown()
        async with self._operation_lock:
            await self.client.disconnect()
