from typing import Dict
from homeassistant import config_entries
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    LabelSelector,
    LabelSelectorConfig
)
import re
import logging
import voluptuous as vol
from .const import DOMAIN
from .const import (
        SWITCH_PLATFORM
)

_LOGGER = logging.getLogger(__name__)

class PresenceSimulationConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 5

    def __init__(self):
        super().__init__()
        self.data: dict = {}

    async def async_step_user(self, info=None):
        errors: Dict[str, str] = {}
        all_entities = self.hass.states.async_entity_ids()
        _LOGGER.debug("all_entities %s", all_entities)
        data_schema = {
            vol.Required("switch", description={"suggested_value": "Choose a unique name"}): str,
            vol.Required("entities"): SelectSelector(SelectSelectorConfig(options=all_entities, multiple=True, mode=SelectSelectorMode.DROPDOWN)),
            vol.Required("labels"): LabelSelector(LabelSelectorConfig(multiple=True)),
            vol.Required("delta", default=7): int,
            vol.Required("interval", default=30): int,
            vol.Required("restore", default=False): bool,
            vol.Required("random", default=0): int,
            vol.Required("unavailable_as_off", default=False): bool,
            vol.Required("brightness", default=0): int,
        }
        if not info:
            return self.async_show_form(
                step_id="user", data_schema=vol.Schema(data_schema)
            )
        #if the name match with an already existing entity, ask to change it
        all_entities = self.hass.states.async_entity_ids()
        switch_id = SWITCH_PLATFORM+"."+re.sub("[^0-9a-zA-Z]", "_", info["switch"].lower())
        if switch_id in all_entities:
            _LOGGER.error("Entity name is already taken, please change the name of the switch")
            errors["base"] = "not_unique_name"
            return self.async_show_form(
                step_id="user", data_schema=vol.Schema(data_schema), errors=errors
            )
        self.data = info
        try:
            _LOGGER.debug("info.entities %s",info['entities'])
            _LOGGER.debug("info.labels %s",info['labels'])
            #check if entity exist
            #hass.states.get(info['entities'])
        except Exception as e:
            _LOGGER.debug("Exception %s", e)
            return self.async_show_form(
                step_id="user", data_schema=vol.Schema(data_schema)
            )
        else:
            self.data["entities"] = ",".join(self.data["entities"])
            return self.async_create_entry(title="Simulation Presence", data=self.data)

    @staticmethod
    def async_get_options_flow(entry):
        return OptionsFlowHandler()


class OptionsFlowHandler(config_entries.OptionsFlow):

    async def async_step_init(self, info=None):
        errors: Dict[str, str] = {}
        _LOGGER.debug("config flow init %s", info)
        all_entities = self.hass.states.async_entity_ids()

        if "interval" in self.config_entry.options:
            interval = self.config_entry.options["interval"]
        else:
            interval = 30
        if "restore" in self.config_entry.options:
            restore = self.config_entry.options["restore"]
        else:
            restore = 0
        if "random" in self.config_entry.options:
            random = self.config_entry.options["random"]
        else:
            random = 0
        if "unavailable_as_off" in self.config_entry.options:
            unavailable_as_off = self.config_entry.options["unavailable_as_off"]
        else:
            unavailable_as_off = False
        if "brightness" in self.config_entry.options:
            brightness = self.config_entry.options["brightness"]
        else:
            brightness = 0

        switch_val = self.config_entry.options.get("switch", self.config_entry.data["switch"])
        entities_val = self.config_entry.options.get("entities", self.config_entry.data["entities"])
        labels_val = self.config_entry.options.get("labels", self.config_entry.data.get("labels", []))
        delta_val = self.config_entry.options.get("delta", self.config_entry.data["delta"])

        data_schema = {
            vol.Required("switch", default=switch_val): str,
            vol.Required("entities", default=entities_val.split(",")): SelectSelector(SelectSelectorConfig(options=all_entities, multiple=True, mode=SelectSelectorMode.DROPDOWN)),
            vol.Required("labels", default=labels_val): LabelSelector(LabelSelectorConfig(multiple=True)),
            vol.Required("delta", default=delta_val): int,
            vol.Required("interval", default=interval): int,
            vol.Required("restore", default=restore): bool,
            vol.Required("random", default=random): int,
            vol.Required("unavailable_as_off", default=unavailable_as_off): bool,
            vol.Required("brightness", default=brightness): int,
        }
        _LOGGER.debug("switch %s", self.config_entry.data["switch"])
        _LOGGER.debug("config_entry data %s", self.config_entry.data)
        _LOGGER.debug("config_entry options %s", self.config_entry.options)

        if not info:
            return self.async_show_form(
                step_id="init", data_schema=vol.Schema(data_schema)
            )

        #if pop-up is saved but the name has changed, log an error and ask again
        if info["switch"] != self.config_entry.data["switch"]:
            _LOGGER.error("Presence Simulation Switch name can't be changed")
            errors["base"] = "cannot_change_name"
            return self.async_show_form(
                step_id="init", data_schema=vol.Schema(data_schema), errors=errors
            )

        info["entities"] = ",".join(info["entities"])
        self.hass.config_entries.async_update_entry(self.config_entry, options=info)
        return self.async_abort(reason="")
