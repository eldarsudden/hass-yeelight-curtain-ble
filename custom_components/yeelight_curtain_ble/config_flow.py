"""Discover the curtain and verify state or explicitly chosen initial placement."""

import logging

try:
    import probatio as schema
except ImportError:  # HA releases before the schema migration.
    import voluptuous as schema

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigFlow, OptionsFlowWithReload
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    DEFAULT_PERSISTENT_CONNECTION,
    DOMAIN,
    MOUNTING_SIDES,
    NAME_PREFIX,
    OPT_PERSISTENT_CONNECTION,
)
from .coordinator import ERRORS, create_client
from .custom_gif import OPT_CUSTOM_GIFS, OPT_LAST_CUSTOM_GIF, import_uploaded_gif

_LOGGER = logging.getLogger(__name__)


class CurtainConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return CurtainOptionsFlow()

    def __init__(self):
        self._devices = {}
        self._discovered_address = None
        self._pending_address = None

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
        client = create_client(self.hass, address)
        try:
            return await client.read_state()
        finally:
            await client.close()

    async def _create(self, address):
        await self.async_set_unique_id(address)
        self._abort_if_unique_id_configured()
        state = await self._validate(address)
        if not state["adapter_set"]:
            self._pending_address = address
            return await self.async_step_placement()
        return self.async_create_entry(title=self._devices[address], data={CONF_ADDRESS: address})

    async def async_step_placement(self, user_input=None):
        """Initialize an unconfigured curtain only after an explicit placement choice."""
        if self._pending_address is None:
            return self.async_abort(reason="no_devices_found")
        errors = {}
        if user_input is not None:
            side = user_input["mounting_side"]
            if side not in MOUNTING_SIDES:
                errors["base"] = "setup_failed"
            else:
                address = self._pending_address
                client = create_client(self.hass, address)
                try:
                    await self.async_set_unique_id(address)
                    self._abort_if_unique_id_configured()
                    await client.configure_mounting(side)
                    await client.read_state()
                except ERRORS:
                    errors["base"] = "setup_failed"
                else:
                    return self.async_create_entry(title=self._devices[address], data={CONF_ADDRESS: address})
                finally:
                    await client.close()
        return self.async_show_form(
            step_id="placement",
            data_schema=schema.Schema({
                schema.Required("mounting_side"): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=list(MOUNTING_SIDES), translation_key="mounting_side"
                    )
                ),
            }),
            errors=errors,
        )

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


class CurtainOptionsFlow(OptionsFlowWithReload):
    """Choose connection lifetime without losing saved music preferences."""

    async def async_step_init(self, user_input=None):
        errors = {}
        if user_input is not None:
            name = user_input.get("gif_name", "").strip()
            file_id = user_input.get("gif_file")
            imported = None
            if bool(name) != bool(file_id):
                errors["base"] = "gif_name_and_file"
            elif file_id:
                try:
                    imported = await self.hass.async_add_executor_job(
                        import_uploaded_gif, self.hass, self.config_entry.entry_id, file_id, name
                    )
                except (ValueError, OSError):
                    errors["base"] = "invalid_gif"
            if not errors:
                options = dict(self.config_entry.options)
                library = dict(options.get(OPT_CUSTOM_GIFS, {}))
                for removed in user_input.get("remove_gifs", []):
                    library.pop(removed, None)
                if imported is not None:
                    previous = library.get(imported["name"], {})
                    if (
                        options.get(OPT_LAST_CUSTOM_GIF) == imported["name"]
                        and previous.get("sha256") != imported["sha256"]
                    ):
                        options.pop(OPT_LAST_CUSTOM_GIF, None)
                    library[imported["name"]] = imported
                if library or OPT_CUSTOM_GIFS in options:
                    options[OPT_CUSTOM_GIFS] = library
                if options.get(OPT_LAST_CUSTOM_GIF) not in library:
                    options.pop(OPT_LAST_CUSTOM_GIF, None)
                options[OPT_PERSISTENT_CONNECTION] = user_input[OPT_PERSISTENT_CONNECTION]
                return self.async_create_entry(title="", data=options)
        fields = {
            schema.Required(
                OPT_PERSISTENT_CONNECTION,
                default=self.config_entry.options.get(
                    OPT_PERSISTENT_CONNECTION, DEFAULT_PERSISTENT_CONNECTION
                ),
            ): bool,
            schema.Optional("gif_name"): selector.TextSelector(),
            schema.Optional("gif_file"): selector.FileSelector(
                selector.FileSelectorConfig(accept=".gif,image/gif")
            ),
        }
        if library := self.config_entry.options.get(OPT_CUSTOM_GIFS):
            fields[schema.Optional("remove_gifs")] = selector.SelectSelector(
                selector.SelectSelectorConfig(options=list(library), multiple=True)
            )
        return self.async_show_form(
            step_id="init",
            data_schema=schema.Schema(fields),
            errors=errors,
        )
