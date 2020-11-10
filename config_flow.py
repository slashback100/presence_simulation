from homeassistant import config_entries
import voluptuous as vol

DOMAIN="presence_simulation"

class ExampleConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Example config flow."""
    VERSION = 1
    data = None
    async def async_create_flow(handler, context, data):
            """Create flow."""
    async def async_finish_flow(flow, result):
            """Finish flow."""
    async def async_step_user(self, info=None):
        if not info:
            data_schema = {
                vol.Required("entities"): str,
                vol.Required("delta"): str,
            }
            return self.async_show_form(
                step_id="user", data_schema=vol.Schema(data_schema)
            )
        self.data = info
        return self.async_create_entry(title="Simulation Presence", data=self.data)

