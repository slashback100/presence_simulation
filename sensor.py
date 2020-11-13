from homeassistant.helpers.entity import ToggleEntity
from datetime import datetime, timezone, timedelta
import math
import logging
from .const import (
        DOMAIN,
        SENSOR_PLATFORM,
        SENSOR
)
SCAN_INTERVAL = timedelta(seconds=5)
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
        self.attr={}
        self.attr["friendly_name"] = "Presence Simulation Toggle"
        self._next_events = []
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
        self._next_events = []

    async def async_update(self):
        if len(self._next_events) > 0:
            self.attr["next_event_datetime"], self.attr["next_entity_id"], self.attr["next_entity_state"] = sorted(self._next_events)[0]
        else:
            for prop in ("next_event_datetime", "next_entity_id", "next_entity_state"):
                if prop in self.attr:
                    del self.attr[prop]

    def update(self):
        if len(self._next_events) > 0:
            self.attr["next_event_datetime"], self.attr["next_entity_id"], self.attr["next_entity_state"] = sorted(self._next_events)[0]
        else:
            for prop in ("next_event_datetime", "next_entity_id", "next_entity_state"):
                if prop in self.attr:
                    del self.attr[prop]

    @property
    def device_state_attributes(self):
        return self.attr

    async def async_added_to_hass(self):
        """When sensor is added to hassio."""
        await super().async_added_to_hass()
        if DOMAIN not in self.hass.data:
            self.hass.data[DOMAIN] = {}
        if SENSOR_PLATFORM not in self.hass.data[DOMAIN]:
            self.hass.data[DOMAIN][SENSOR_PLATFORM] = {}
        self.hass.data[DOMAIN][SENSOR_PLATFORM][SENSOR] = self

    async def async_add_next_event(self, next_datetime, entity_id, state):
        self._next_events.append((next_datetime, entity_id, state))

    async def async_remove_event(self, entity_id):
        i=0
        for e in self._next_events:
            if e[1] == entity_id:
                del self._next_events[i]
            i += 1
