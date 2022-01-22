from homeassistant import config_entries
import logging
import voluptuous as vol
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

class PresenceSimulationConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Example config flow."""
    VERSION = 1
    data = None
    async def async_create_flow(handler, context, data):
            """Create flow."""
    async def async_finish_flow(flow, result):
            """Finish flow."""
    async def async_step_user(self, info=None):
        data_schema = {
            vol.Required("entities"): str,
            vol.Required("delta", default=7): int,
            vol.Required("interval", default=30): int,
            vol.Required("restore", default=False): bool,
            vol.Required("random", default=0): int,
        }
        if not info:
            return self.async_show_form(
                step_id="user", data_schema=vol.Schema(data_schema)
            )
        self.data = info
        try:
            _LOGGER.debug("info.entities %s",info['entities'])
            #check if entity exist
            #hass.states.get(info['entities'])
        except Exception as e:
            _LOGGER.debug("Exception %s", e)
            return self.async_show_form(
                step_id="user", data_schema=vol.Schema(data_schema)
            )
        else:
            return self.async_create_entry(title="Simulation Presence", data=self.data)

    #@callback
    @staticmethod
    def async_get_options_flow(entry):
        _LOGGER.debug("entry %s", entry)
        return OptionsFlowHandler(entry)

class OptionsFlowHandler(config_entries.OptionsFlow):
    def __init__(self, config_entry):
        self.config_entry = config_entry
    async def async_step_init(self, info=None):
        """Manage the options."""
        if not info:
            if "interval" in self.config_entry.data:
                interval = self.config_entry.data["interval"]
            else:
                interval = 30
            if "restore" in self.config_entry.data:
                restore = self.config_entry.data["restore"]
            else:
                restore = 0
            if "random" in self.config_entry.data:
                random = self.config_entry.data["random"]
            else:
                random = 0

            data_schema = {
                vol.Required("entities", default=self.config_entry.data["entities"]): str,
                vol.Required("delta", default=self.config_entry.data["delta"]): int,
                vol.Required("interval", default=interval): int,
                vol.Required("restore", default=restore): bool,
                vol.Required("random", default=random): int,
            }
            return self.async_show_form(
                step_id="init", data_schema=vol.Schema(data_schema)
            )
        return self.async_create_entry(title="Simulation Presence", data=info)
