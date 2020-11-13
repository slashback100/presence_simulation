from homeassistant.helpers.entity import ToggleEntity
import logging
from .const import (
        DOMAIN,
        SENSOR_PLATFORM,
        SENSOR
)

_LOGGER = logging.getLogger(__name__)

async def async_setup_platform(hass, _, async_add_entities, discovery_info=None):
    """Create presence simulation entity defined in YAML and add them to HA."""
    _LOGGER.debug("async_setup_platform")
    if PresenceSimulationSwitch.instances == 0:
        async_add_entities([PresenceSimulationSwitch(hass)], True)


async def async_setup_entry(hass, config_entry, async_add_devices):
    _LOGGER.debug("async_setup_entry")
    """Create presence simulation entities defined in config_flow and add them to HA."""
    if PresenceSimulationSwitch.instances == 0:
        async_add_devices([PresenceSimulationSwitch(hass)], True)

class PresenceSimulationSwitch(ToggleEntity):
    instances = 0
    def __init__(self, hass):
        self.turn_off()
        self.hass = hass
        PresenceSimulationSwitch.instances += 1
        pass

    @property
    def name(self):
        return "Presence Simulation"

    @property
    def is_on(self):
        return self._state == "on"

    @property
    def state(self):
        return self._state

    def turn_on(self, **kwargs):
        self._state = "on"

    def turn_off(self, **kwargs):
        self._state = "off"

    async def async_update(self):
        pass

    def update(self):
        pass

    @property
    def device_state_attributes(self):
        attr={}
        attr["friendly_name"] = "Presence Simulation Toggle"
        return attr

    async def async_added_to_hass(self):
        """When sensor is added to hassio."""
        await super().async_added_to_hass()
        if DOMAIN not in self.hass.data:
            self.hass.data[DOMAIN] = {}
        if SENSOR_PLATFORM not in self.hass.data[DOMAIN]:
            self.hass.data[DOMAIN][SENSOR_PLATFORM] = {}
        self.hass.data[DOMAIN][SENSOR_PLATFORM][SENSOR] = self
