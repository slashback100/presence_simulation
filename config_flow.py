from homeassistant import config_entries
import logging
import voluptuous as vol

DOMAIN="presence_simulation"
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
            vol.Required("delta"): str,
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

