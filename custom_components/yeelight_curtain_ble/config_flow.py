"""Discover the curtain through HA and verify a read before creating an entry."""

import logging
from functools import partial

try:
    import probatio as schema
except ImportError:  # HA releases before the schema migration.
    import voluptuous as schema

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigFlow
from homeassistant.const import CONF_ADDRESS

from .client import CurtainClient
from .const import DOMAIN, NAME_PREFIX
from .coordinator import ERRORS, connect

_LOGGER = logging.getLogger(__name__)


class CurtainConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self):
        self._devices = {}
        self._discovered_address = None

    async def async_step_bluetooth(self, discovery_info):
        if not discovery_info.connectable or not discovery_info.name.startswith(NAME_PREFIX):
            return self.async_abort(reason="not_supported")
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        self._devices[discovery_info.address] = discovery_info.name
        self._discovered_address = discovery_info.address
        self.context["title_placeholders"] = {"name": discovery_info.name}
        return await self.async_step_confirm()

    async def _validate(self, address):
        client = CurtainClient(partial(connect, self.hass, address))
        try:
            await client.read_state()
        finally:
            await client.disconnect()

    async def _create(self, address):
        await self.async_set_unique_id(address)
        self._abort_if_unique_id_configured()
        await self._validate(address)
        return self.async_create_entry(title=self._devices[address], data={CONF_ADDRESS: address})

    async def async_step_confirm(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                return await self._create(self._discovered_address)
            except ERRORS:
                errors["base"] = "cannot_connect"
        return self.async_show_form(
            step_id="confirm",
            data_schema=schema.Schema({}),
            errors=errors,
            description_placeholders={"name": self._devices[self._discovered_address]},
        )

    async def async_step_user(self, user_input=None):
        errors = {}
        existing = self._async_current_ids()
        for info in bluetooth.async_discovered_service_info(self.hass, connectable=True):
            if info.name.startswith(NAME_PREFIX) and info.address not in existing:
                self._devices[info.address] = info.name
        if not self._devices:
            return self.async_abort(reason="no_devices_found")
        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            if address not in self._devices:
                errors["base"] = "cannot_connect"
            else:
                try:
                    return await self._create(address)
                except ERRORS:
                    errors["base"] = "cannot_connect"
        return self.async_show_form(
            step_id="user",
            data_schema=schema.Schema(
                {
                    schema.Required(CONF_ADDRESS): schema.In(
                        {address: f"{name} ({address})" for address, name in self._devices.items()}
                    ),
                }
            ),
            errors=errors,
        )
