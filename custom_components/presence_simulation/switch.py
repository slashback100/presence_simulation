#from homeassistant.helpers.entity import ToggleEntity
from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.restore_state import RestoreEntity
from datetime import datetime, timezone, timedelta
import re
import logging
import pytz
from .const import (
        DOMAIN,
        SWITCH_PLATFORM,
)
SCAN_INTERVAL = timedelta(seconds=5)
_LOGGER = logging.getLogger(__name__)
_MAX_VISIBLE_NEXT_EVENTS = 10
_ACTIVE_STATES = {"on", "open", "opening", "playing"}


async def async_setup_entry(hass, config_entry, async_add_devices):
    _LOGGER.debug("async_setup_entry")

    """Create presence simulation entities defined in config_flow and add them to HA."""
    async_add_devices([PresenceSimulationSwitch(hass, config_entry)], True)

class PresenceSimulationSwitch(SwitchEntity,RestoreEntity):

    def __init__(self, hass, config=None):
        _LOGGER.debug("In init of switch")
        self.update_config(config)

        self.hass = hass
        self.attr={}
        self._attr_name = config.data["switch"]
        self.attr["friendly_name"] =  config.data["switch"] + " Toggle"
        # As HA is starting, we don't know the running state of the simulation
        # until restore_state() runs.
        self._attr_available = False
        # State is represented by _attr_is_on, which is initialzied
        # to None by homeassistant/helpers/entity.py:ToggleEntity.
        # State will be initialized when restore_state() runs.
        self._next_events = []
        self._simulated_entities = []
        self.id = SWITCH_PLATFORM+"."+re.sub("[^0-9a-zA-Z]", "_", config.data["switch"].lower())
        _LOGGER.debug("In init of switch - end")

    def update_config(self, config):
        #self.config = config
        _LOGGER.debug("Config data & options %s, %s", config.data, config.options)

        conf = config.data
        if config.options:
            conf = config.options

        _LOGGER.debug("Config %s", conf["switch"])
        elms = []
        for elm in conf["entities"].split(","):
            elms += [elm.strip()]
        self._entities = elms
        if "labels" in conf:
            self._labels = conf["labels"]
        else:
            self._labels = []
        self._random = int(conf["random"])
        self._interval = int(conf["interval"])
        self._delta = conf["delta"]
        self._restore = conf["restore"]
        self._unavailable_as_off = conf.get("unavailable_as_off", False)
        self._brightness = conf.get("brightness", 0)
        self._history_end = conf.get("history_end", "")
        self._use_snapshot = False
        self.reset_default_values()
        _LOGGER.debug("entities %s", conf["entities"])

    @property
    def unique_id(self):
      return self.id #UNIQUE_ID + "_" + str(self.instance)

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

    async def turn_on_async(self, after_ha_restart=False, **kwargs):
        """Turn on the presence simulation"""
        _LOGGER.debug("Turn on of the presence simulation through the switch")
        await self.hass.services.async_call(
            DOMAIN,
            "start",
            {
                "switch_id": self.id,
                "internal": True,
                "after_ha_restart": after_ha_restart,
            },
            blocking=True,
        )

    async def async_turn_on(self, **kwargs):
        """Use the event-loop-safe start route used by Home Assistant."""
        await self.turn_on_async(**kwargs)

    async def async_turn_off(self, **kwargs):
        """Use the event-loop-safe stop route used by Home Assistant."""
        await self.hass.services.async_call(
            DOMAIN,
            "stop",
            {"switch_id": self.id, "internal": True},
            blocking=True,
        )

    def turn_on(self, **kwargs):
        """Turn on the presence simulation"""
        _LOGGER.debug("Turn on of the presence simulation through the switch")
        self.hass.services.call(DOMAIN, "start", {"switch_id": self.id, "internal": True})

    def turn_off(self, **kwargs):
        """Turn off the presence simulation"""
        _LOGGER.debug("Turn off of the presence simulation through the switch")
        self.hass.services.call(DOMAIN, "stop", {"switch_id": self.id, "internal": True})

    async def async_update(self):
        """Update the attributes in regards to the list of next events"""
        self._update_attributes()

    def update(self):
        """Update the attributes in regards to the list of next events"""
        self._update_attributes()

    def _update_attributes(self):
        """Common method to update attributes from next events."""
        if len(self._next_events) > 0:
            self.attr["next_event_datetime"], self.attr["next_entity_id"], self.attr["next_entity_state"] = self._next_events[0]
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

        self.attr["scheduled_event_count"] = len(self._next_events)
        self.attr["next_events"] = [
            {
                "datetime": self._format_datetime(next_datetime),
                "entity_id": entity_id,
                "state": state,
            }
            for next_datetime, entity_id, state in self._next_events[
                :_MAX_VISIBLE_NEXT_EVENTS
            ]
        ]
        current_entities = []
        active_entities = []
        for entity_id in self._simulated_entities:
            current_state = self.hass.states.get(entity_id)
            if current_state is None:
                continue
            current = {"entity_id": entity_id, "state": current_state.state}
            current_entities.append(current)
            if current_state.state in _ACTIVE_STATES:
                active_entities.append(current)
        self.attr["current_entities"] = current_entities
        self.attr["active_entities"] = active_entities
        self.attr["active_entity_count"] = len(active_entities)

    def _format_datetime(self, value):
        """Format a scheduled datetime in the configured Home Assistant zone."""
        try:
            return value.astimezone(pytz.timezone(self.hass.config.time_zone)).isoformat()
        except (AttributeError, TypeError, pytz.UnknownTimeZoneError):
            return str(value)

    @property
    def labels(self):
        return self._labels_overriden
    @property
    def entities(self):
        return self._entities_overriden
    @property
    def random(self):
        return self._random_overriden
    @property
    def delta(self):
        return self._delta_overriden
    @property
    def restore(self):
        return self._restore_overriden
    @property
    def unavailable_as_off(self):
        return self._unavailable_as_off_overriden
    @property
    def brightness(self):
        return self._brightness_overriden
    @property
    def interval(self):
        return self._interval
    @property
    def history_end(self):
        return self._history_end_overriden
    @property
    def use_snapshot(self):
        return self._use_snapshot_overriden

    async def reset_default_values_async(self):
        self._entities_overriden = self._entities
        self._labels_overriden = self._labels
        self._random_overriden = self._random
        self._restore_overriden = self._restore
        self._delta_overriden = self._delta
        self._unavailable_as_off_overriden = self._unavailable_as_off
        self._brightness_overriden = self._brightness
        self._history_end_overriden = self._history_end
        self._use_snapshot_overriden = self._use_snapshot

    def reset_default_values(self):
        self._entities_overriden = self._entities
        self._labels_overriden = self._labels
        self._random_overriden = self._random
        self._restore_overriden = self._restore
        self._delta_overriden = self._delta
        self._unavailable_as_off_overriden = self._unavailable_as_off
        self._brightness_overriden = self._brightness
        self._history_end_overriden = self._history_end
        self._use_snapshot_overriden = self._use_snapshot


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

        #restore stored state
        _LOGGER.debug("Adding %s to %s", self.id, SWITCH_PLATFORM)
        self.hass.data[DOMAIN][SWITCH_PLATFORM][self.id] = self
        if(state := await self.async_get_last_state()) is not None:
            _LOGGER.debug("restore stored state")
            if state.state == "on":
                _LOGGER.debug("State was on")
                if "entity_id" in state.attributes:
                    self._entities_overriden = state.attributes["entity_id"]
                if "labels" in state.attributes:
                    self._labels_overriden = state.attributes["labels"]
                if "random" in state.attributes:
                    self._random_overriden = state.attributes["random"]
                if "delta" in state.attributes:
                    self._delta_overriden = state.attributes["delta"]
                if "restore_states" in state.attributes:
                    self._restore_overriden = state.attributes["restore_states"]
                if "unavailable_as_off" in state.attributes:
                    self._unavailable_as_off_overriden = state.attributes["unavailable_as_off"]
                if "brightness" in state.attributes:
                    self._brightness_overriden = state.attributes["brightness"]
                if "history_end" in state.attributes:
                    self._history_end_overriden = state.attributes["history_end"]
                if "use_snapshot" in state.attributes:
                    self._use_snapshot_overriden = state.attributes["use_snapshot"]
                #just set internally to on, the simulation service will be called later once the HA Start event is fired
                self.internal_turn_on()
            else:
                _LOGGER.debug("State was off")
                self.internal_turn_off()
        else:
          self.internal_turn_off()


    async def async_add_next_event(self, next_datetime, entity_id, state):
        """Add the next event in the the events list and sort them"""
        self._next_events.append((next_datetime, entity_id, state))
        #sort so that the firt element is the next one
        self._next_events = sorted(self._next_events)
        self._update_attributes()
        self.async_write_ha_state()

    async def async_remove_event(self, entity_id):
        """Remove the next event of an entity"""
        self._next_events = [e for e in self._next_events if e[1] != entity_id]
        self._update_attributes()
        self.async_write_ha_state()

    async def set_simulated_entities(self, entities):
        """Store the resolved entities so their current state is visible."""
        self._simulated_entities = list(entities)
        self._update_attributes()
        self.async_write_ha_state()

    async def set_history_window(self, history_start, history_end):
        """Expose the exact source history window used for this run."""
        self.attr["history_start"] = self._format_datetime(history_start)
        self.attr["source_history_end"] = self._format_datetime(history_end)

    async def set_use_snapshot(self, use_snapshot):
        self.attr["use_snapshot"] = bool(use_snapshot)
        self._use_snapshot_overriden = bool(use_snapshot)

    async def set_snapshot_metadata(self, snapshot):
        """Expose cache diagnostics without exposing its full contents."""
        if not snapshot:
            self.attr["snapshot_status"] = "missing"
            return
        self.attr["snapshot_status"] = "ready"
        self.attr["snapshot_captured_at"] = snapshot.get("captured_at")
        self.attr["snapshot_history_start"] = snapshot.get("history_start")
        self.attr["snapshot_history_end"] = snapshot.get("history_end")
        self.attr["snapshot_entity_count"] = len(snapshot.get("events", {}))
        self.attr["snapshot_event_count"] = snapshot.get("event_count", 0)

    async def set_last_event(self, event_data):
        """Expose the latest action actually sent by the simulator."""
        self.attr["last_event"] = {
            "datetime": self._format_datetime(datetime.now(timezone.utc)),
            "entity_id": event_data["entity_id"],
            "service": event_data["service"],
        }
        self._update_attributes()
        self.async_write_ha_state()

    async def set_start_datetime(self, start_datetime):
        self.attr["simulation_start"] = start_datetime

    async def set_delta(self, delta):
        self.attr["delta"] = delta
        self._delta_overriden = delta

    async def set_labels(self, labels):
        _LOGGER.debug("overidding labels %s", labels)
        self.attr["labels"] = labels
        self._labels_overriden = labels

    async def set_entities(self, entities):
        _LOGGER.debug("overidding entities %s", entities)
        self.attr["entity_id"] = entities
        self._entities_overriden = entities

    async def set_restore(self, restore_states):
        self.attr["restore_states"] = restore_states
        self._restore_overriden = restore_states

    async def set_random(self, random):
        self.attr["random"] = random
        self._random_overriden = random

    async def set_unavailable_as_off(self, unavailable_as_off):
        self.attr["unavailable_as_off"] = unavailable_as_off
        self._unavailable_as_off_overriden = unavailable_as_off

    async def set_brightness(self, brightness):
        self.attr["brightness"] = brightness
        self._brightness_overriden = brightness

    async def set_history_end(self, history_end):
        self.attr["history_end"] = history_end
        self._history_end_overriden = history_end

    async def set_interval(self, interval):
        self._interval = interval


    async def reset_start_datetime(self):
        if "simulation_start" in self.attr:
            del self.attr["simulation_start"]

    async def reset_delta(self):
        if "delta" in self.attr:
            del self.attr["delta"]

    async def reset_labels(self):
        if "labels" in self.attr:
            del self.attr["labels"]

    async def reset_entities(self):
        if "entity_id" in self.attr:
            del self.attr["entity_id"]

    async def reset_restore_states(self):
        if "restore_states" in self.attr:
            del self.attr["restore_states"]

    async def reset_random(self):
        if "random" in self.attr:
            del self.attr["random"]

    async def reset_unavailable_as_off(self):
        if "unavailable_as_off" in self.attr:
            del self.attr["unavailable_as_off"]

    async def reset_brightness(self):
        if "brightness" in self.attr:
            del self.attr["brightness"]

    async def reset_history_end(self):
        if "history_end" in self.attr:
            del self.attr["history_end"]
