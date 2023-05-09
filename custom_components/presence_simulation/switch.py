#from homeassistant.helpers.entity import ToggleEntity
from homeassistant.components.switch import SwitchEntity
from datetime import datetime, timezone, timedelta
import math
import logging
import pytz
from .const import (
        DOMAIN,
        SWITCH_PLATFORM,
        SWITCH,
        UNIQUE_ID
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

class PresenceSimulationSwitch(SwitchEntity):
    instances = 0

    def __init__(self, hass):
        self.hass = hass
        self.attr={}
        self.attr["friendly_name"] = "Presence Simulation Toggle"
        self._attr_name = "Presence Simulation"
        # As HA is starting, we don't know the running state of the simulation
        # until restore_state() runs.
        self._attr_available = False
        # State is represented by _attr_is_on, which is initialzied
        # to None by homeassistant/helpers/entity.py:ToggleEntity.
        # State will be initialized when restore_state() runs.
        self._next_events = []
        PresenceSimulationSwitch.instances += 1

    @property
    def unique_id(self):
      return UNIQUE_ID

    def internal_turn_on(self, **kwargs):
        """Turn on the presence simulation flag. Does not launch the simulation, this is for the calls from the services, to avoid a loop"""
        self._attr_available = True
        self._attr_is_on = True
        self.async_write_ha_state()

    def internal_turn_off(self, **kwargs):
        """Turn off the presence simulation flag. Does not launch the stop simulation service, this is for the calls from the services, to avoid a loop"""
        self._attr_available = True
        self._attr_is_on = False
        self._next_events = []
        self.async_write_ha_state()

    def turn_on(self, **kwargs):
        """Turn on the presence simulation"""
        _LOGGER.debug("Turn on of the presence simulation through the switch")
        self.hass.services.call(DOMAIN, "start")

    def turn_off(self, **kwargs):
        """Turn off the presence simulation"""
        _LOGGER.debug("Turn off of the presence simulation through the switch")
        self.hass.services.call(DOMAIN, "stop")

    async def async_update(self):
        """Update the attributes in regards to the list of next events"""
        if len(self._next_events) > 0:
            self.attr["next_event_datetime"], self.attr["next_entity_id"], self.attr["next_entity_state"] = self._next_events[0] #list is sorted
            try:
                self.attr["next_event_datetime"] = self.attr["next_event_datetime"].astimezone(self.hass.config.time_zone).strftime("%d/%m/%Y %H:%M:%S")
            except Exception as e:
                try:
                    self.attr["next_event_datetime"] = self.attr["next_event_datetime"].astimezone(pytz.timezone(self.hass.config.time_zone)).strftime("%d/%m/%Y %H:%M:%S")
                except Exception as e:
                    _LOGGER.warning("Exception while trying to convert utc to local time: %s",e)
        else:
            for prop in ("next_event_datetime", "next_entity_id", "next_entity_state"):
                if prop in self.attr:
                    del self.attr[prop]

    def update(self):
        """Update the attributes in regards to the list of next events"""
        if len(self._next_events) > 0:
            self.attr["next_event_datetime"], self.attr["next_entity_id"], self.attr["next_entity_state"] = self._next_events[0] #list is sorted
            try:
                self.attr["next_event_datetime"] = self.attr["next_event_datetime"].astimezone(self.hass.config.time_zone).strftime("%d/%m/%Y %H:%M:%S")
            except Exception as e:
                try:
                    self.attr["next_event_datetime"] = self.attr["next_event_datetime"].astimezone(pytz.timezone(self.hass.config.time_zone)).strftime("%d/%m/%Y %H:%M:%S")
                except Exception as e:
                    _LOGGER.warning("Exception while trying to convert utc to local time: %s",e)
        else:
            for prop in ("next_event_datetime", "next_entity_id", "next_entity_state"):
                if prop in self.attr:
                    del self.attr[prop]

    #def device_state_attributes(self):
    @property
    def extra_state_attributes(self):
        """Returns the attributes list"""
        return self.attr

    async def async_added_to_hass(self):
        """When sensor is added to hassio."""
        await super().async_added_to_hass()
        if DOMAIN not in self.hass.data:
            self.hass.data[DOMAIN] = {}
        if SWITCH_PLATFORM not in self.hass.data[DOMAIN]:
            self.hass.data[DOMAIN][SWITCH_PLATFORM] = {}
        self.hass.data[DOMAIN][SWITCH_PLATFORM][SWITCH] = self

    async def async_add_next_event(self, next_datetime, entity_id, state):
        """Add the next event in the the events list and sort them"""
        self._next_events.append((next_datetime, entity_id, state))
        #sort so that the firt element is the next one
        self._next_events = sorted(self._next_events)

    async def async_remove_event(self, entity_id):
        """Remove the next event of an entity"""
        self._next_events = [e for e in self._next_events if e[1] != entity_id]

    async def set_start_datetime(self, start_datetime):
        self.attr["simulation_start"] = start_datetime

    async def set_delta(self, delta):
        self.attr["delta"] = delta

    async def set_entities(self, entities):
        self.attr["entity_id"] = entities

    async def set_restore_states(self, restore_states):
        self.attr["restore_states"] = restore_states

    async def restore_states(self):
        if 'restore_states' in self.attr:
            return self.attr['restore_states']
        else:
            return False

    async def set_random(self, random):
        self.attr["random"] = random
    async def random(self):
        if 'random' in self.attr:
            return self.attr['random']
        else:
            return 0


    async def reset_start_datetime(self):
        if "simulation_start" in self.attr:
            del self.attr["simulation_start"]

    async def reset_delta(self):
        if "delta" in self.attr:
            del self.attr["delta"]

    async def reset_entities(self):
        if "entity_id" in self.attr:
            del self.attr["entity_id"]

    async def reset_restore_states(self):
        if "restore_states" in self.attr:
            del self.attr["restore_states"]

    async def reset_random(self):
        if "random" in self.attr:
            del self.attr["random"]
