"""Component to integrate with presence_simulation."""

import logging
import time
import asyncio
import pytz
import re
import random
from datetime import datetime,timedelta,timezone
from homeassistant.components.recorder.history import get_significant_states
from homeassistant.components.recorder import get_instance
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.helpers.entity_registry import async_migrate_entries
from .const import (
        DOMAIN,
        SWITCH_PLATFORM,
        SWITCH,
        RESTORE_SCENE,
        SCENE_PLATFORM,
        UNIQUE_ID,
        MY_EVENT
)
_LOGGER = logging.getLogger(__name__)
MIN_DELAY = 1 #time in second for the minimal switch delay

async def async_setup(hass, config):
    """Set up this component using YAML."""
    if config.get(DOMAIN) is None:
        # We get here if the integration is set up using config flow
        return True

async def async_setup_entry(hass, entry):
    """Set up this component using config flow."""
    _LOGGER.debug("async setup entry %s", entry.data["entities"])
    unsub = entry.add_update_listener(update_listener)

    # Add sensor
    # Use `hass.async_create_task` to avoid a circular dependency between the platform and the component
    hass.async_create_task(hass.config_entries.async_forward_entry_setup(entry, SWITCH_PLATFORM))

    previous_attribute = {}

    async def stop_presence_simulation(err=None, restart=False, switch_id=None):
        """Stop the presence simulation, raising a potential error"""
        #get the switch entity
        entity = hass.data[DOMAIN][SWITCH_PLATFORM][switch_id]

        #set the state of the switch to off. Not calling turn_off to avoid calling the stop service again
        entity.internal_turn_off()
        if not restart:
            #empty the start_datetime  attribute
            await entity.reset_start_datetime()
            await entity.reset_entities()
            await entity.reset_delta()
            await entity.reset_random()
            # if the scene exist, turn it on
            # TODO check to improve, won't work if you launch one time is the restore state and then after without it.
            #Can not just take restoreAfterStop cause if it is overriden in the service call, restoreAfterStop is not update
            _LOGGER.debug("entity.restore_states %s", entity.restore)
            scene = hass.states.get(SCENE_PLATFORM+"."+switch_id.replace(".", "_")+"_"+RESTORE_SCENE)
            if scene is not None and entity.restore:
                service_data = {}
                service_data["entity_id"] = SCENE_PLATFORM+"."+switch_id.replace(".", "_")+"_"+RESTORE_SCENE
                _LOGGER.debug("Restoring scene after the simulation")
                try:
                    await hass.services.async_call("scene", "turn_on", service_data, blocking=False)
                except Exception as e:
                    _LOGGER.error("Error when restoring the scene after the simulation")
                    pass
            await entity.reset_restore_states()
        if err is not None:
            _LOGGER.debug("Error in presence simulation, exiting")
            raise e

    async def handle_stop_presence_simulation(call, restart=False, switch_id=None):
        """Stop the presence simulation"""
        _LOGGER.debug("Stopped presence simulation")
        if call is not None: #if we are here, it is a call of the service, or a restart at the end of a cycle
            if "switch_id" in call.data:
                switch_id = call.data.get("switch_id")
            elif len(hass.data[DOMAIN][SWITCH_PLATFORM]) == 1:
                switch_id = list(hass.data[DOMAIN][SWITCH_PLATFORM])[0]
            else:
                _LOGGER.error("Since you have several presence simulation switch, you have to add a switch_id parameter in the service call")
                return
        if is_running(switch_id):
            await stop_presence_simulation(restart=restart, switch_id=switch_id)
        else:
            _LOGGER.warning("Presence simulation switch %s is not on, can't be turned off", switch_id)

    async def async_expand_entities(entities):
        """If the entity is a group, return the list of the entities within, otherwise, return the entity"""
        entities_new = []
        for entity in entities:
            #to make it asyncable, not sure it is needed
            await asyncio.sleep(0)
            if hass.states.get(entity) is None:
                _LOGGER.error("Error when trying to identify entity %s, it seems it doesn't exist. Continuing without this entity", entity)
            else:
                if 'entity_id' in  hass.states.get(entity).attributes:
                    #get the list of the associated entities
                    #the entity_id attribute will be filled for groups or light groups
                    group_entities = hass.states.get(entity).attributes["entity_id"]
                    #and call recursively, in case a group contains a group
                    group_entities_expanded = await async_expand_entities(group_entities)
                    _LOGGER.debug("State %s", group_entities_expanded)
                    entities_new += group_entities_expanded
                else:
                    _LOGGER.debug("Entity %s has no attribute entity_id, it is not a group nor a light group", entity)
                    entities_new.append(entity)
        return entities_new

    async def handle_presence_simulation(call, restart=False, switch_id=None):
        """Start the presence simulation"""
        after_ha_restart=False
        if call is not None: #if we are here, it is a call of the service, or a restart at the end of a cycle, or a restore after a HA restart
            #get the switch entity
            _LOGGER.debug("All Switches: %s", hass.data[DOMAIN][SWITCH_PLATFORM])
            for id in hass.data[DOMAIN][SWITCH_PLATFORM]:
                _LOGGER.debug(hass.data[DOMAIN][SWITCH_PLATFORM][id])
            if "switch_id" in call.data:
                switch_id = call.data.get("switch_id")
                #internal = ("internal" in call.data) and call.data.get("internal")
                entity = hass.data[DOMAIN][SWITCH_PLATFORM][switch_id]
            elif len(hass.data[DOMAIN][SWITCH_PLATFORM]) == 1:
                switch_id = list(hass.data[DOMAIN][SWITCH_PLATFORM])[0]
                entity = hass.data[DOMAIN][SWITCH_PLATFORM][switch_id]
            else:
                _LOGGER.error("Since you have several presence simulation switch, you have to add a switch_id parameter in the service call")
                return
            internal = call.data.get("internal", False) and call.data.get("internal")
            if not is_running(switch_id) and not internal:
                if "entity_id" in call.data:
                    if isinstance(call.data.get("entity_id"), list):
                        await entity.set_entities(call.data.get("entity_id"))
                    else:
                        await entity.set_entities([call.data.get("entity_id")])
                if "delta" in call.data:
                    await entity.set_delta(call.data.get("delta", 7))
                if "restore_states" in call.data:
                    await entity.set_restore(call.data.get("restore_states", False))
                if "random" in call.data:
                    await entity.set_random(call.data.get("random", 0))
                if "after_ha_restart" in call.data:
                    after_ha_restart = call.data.get("after_ha_restart", False)
        else: #if we are it is a call from the toggle service or from the turn_on action of the switch entity
            #get the switch entity
            entity = hass.data[DOMAIN][SWITCH_PLATFORM][switch_id]
            #make sure the initial config of the simulation is used
            await entity.reset_default_values_async()

        _LOGGER.debug("Switch id %s", switch_id)
        _LOGGER.debug("Is already running ? %s", entity.state)
        if is_running(switch_id):
            _LOGGER.warning("Presence simulation already running. Doing nothing")
            return

        current_date = datetime.now(timezone.utc)
        #compute the start date that will be used in the query to get the historic of the entities
        minus_delta = current_date + timedelta(- entity.delta)
        #expand the entities, meaning replace the groups with the entities in it
        try:
            expanded_entities = await async_expand_entities(entity.entities)
        except Exception as e:
            _LOGGER.error("Error during identifing entities: "+entity.entities)
            return

        if len(expanded_entities) == 0:
            _LOGGER.error("Error during identifing entities, no valid entities has been found")
            return

        # turn on the switch. Not calling turn_on() to avoid calling the start
        # service again.  Turn on switch only after setting the important
        # attributes necessary to restore state upon HA restart, so
        # we don't end up in a situation in which the simulation is marked
        # as running, but the necessary attributes aren't set correctly.
        entity.internal_turn_on()
        _LOGGER.debug("Presence simulation started")

        if not restart:
            #set attribute on the switch
            try:
                await entity.set_start_datetime(datetime.now(hass.config.time_zone))
            except Exception as e:
                try:
                    await entity.set_start_datetime(datetime.now(pytz.timezone(hass.config.time_zone)))
                except Exception as e:
                    _LOGGER.warning("Start datetime could not be set to HA timezone: ", e)
                    await entity.set_start_datetime(datetime.now())
            if entity.restore and not after_ha_restart:
                service_data = {}
                service_data["scene_id"] = switch_id.replace(".", "_")+"_"+RESTORE_SCENE
                service_data["snapshot_entities"] = expanded_entities
                _LOGGER.debug("Saving scene before launching the simulation")
                try:
                    await hass.services.async_call("scene", "create", service_data, blocking=True)
                except Exception as e:
                    _LOGGER.error("Scene could not be created, continue without the restore functionality: %s", e)

        _LOGGER.debug("Getting the historic from %s for %s", minus_delta, expanded_entities)
        await get_instance(hass).async_add_executor_job(handle_presence_simulation_sync, hass, call, minus_delta, expanded_entities, switch_id)

    def filter_out_undefined(dic, filter_out_unavailable):
        states_to_remove = ["undefined", "unknown"]
        if filter_out_unavailable:
            states_to_remove += ["unavailable"]
        for hist in dic: #iterate on the entitied
            for state in dic[hist].copy(): #iterate on the historic
                if state.state in states_to_remove:
                    _LOGGER.debug('Deleting state')
                    dic[hist].remove(state)
            #dic[hist] = list(filter(lambda x : x.state not in ["undefined", "unavailable", "unknown"], dic[hist]))
        return dic

    def handle_presence_simulation_sync(hass, call, minus_delta, expanded_entities, switch_id):
        dic = get_significant_states(hass=hass, start_time=minus_delta, entity_ids=expanded_entities, include_start_time_state=True, significant_changes_only=False)
        _LOGGER.debug("history: %s", dic)
        # handle_presence_simulation_sync is called from async_add_executor_job,
        # so may not be running in the event loop, so we can't call hass.async_create_task.
        # instead calling hass.create_task, which is thread_safe.
        # See homeassistant/core.py:create_task
        entity = hass.data[DOMAIN][SWITCH_PLATFORM][switch_id]
        dic = filter_out_undefined(dic, not entity.unavailable_as_off)
        _LOGGER.debug("history after filtering: %s", dic)
        for entity_id in dic:
            _LOGGER.debug('Entity %s', entity_id)
            #launch an async task by entity_id
            hass.create_task(simulate_single_entity(switch_id, entity_id, dic[entity_id], entity.delta, entity.random))

        #launch an async task that will restart the simulation after the delay has passed
        hass.create_task(restart_presence_simulation(call, switch_id=switch_id))
        _LOGGER.debug("All async tasks launched")


    async def handle_toggle_presence_simulation(call):
        """Toggle the presence simulation"""
        if "switch_id" in call.data:
            switch_id = call.data.get("switch_id")
        elif len(hass.data[DOMAIN][SWITCH_PLATFORM]) == 1:
            switch_id = list(hass.data[DOMAIN][SWITCH_PLATFORM])[0]
        else:
            _LOGGER.error("Since you have several presence simulation switch, you have to add a switch_id parameter in the service call")
            return

        if is_running(switch_id):
            await handle_stop_presence_simulation(call, restart=False)
        else:
            await handle_presence_simulation(call, restart=False)


    async def restart_presence_simulation(call, switch_id=None):
        """Make sure that once _delta_ days is passed, relaunch the presence simulation for another _delta_ days"""
        entity = hass.data[DOMAIN][SWITCH_PLATFORM][switch_id]
        await entity.reset_default_values_async()
        _LOGGER.debug("Presence simulation will be relaunched in %i days", entity.delta)
        #compute the moment the presence simulation will have to be restarted
        start_plus_delta = datetime.now(timezone.utc) + timedelta(entity.delta)
        while is_running(switch_id):
            #sleep until the 'delay' is passed
            secs_left = (start_plus_delta - datetime.now(timezone.utc)).total_seconds()
            if secs_left <= 0:
                break
            await asyncio.sleep(min(secs_left, entity.interval))

        if is_running(switch_id):
            _LOGGER.debug("%s has passed, presence simulation is relaunched", entity.delta)
            #Call to stop needed to avoid the start to do nothing since already running
            await handle_stop_presence_simulation(call, restart=True, switch_id=switch_id)
            await handle_presence_simulation(call, restart=True, switch_id=switch_id)

    async def simulate_single_entity(switch_id, entity_id, hist, delta, random_val):
        """This method will replay the historic of one entity received in parameter"""
        _LOGGER.debug("Simulate one entity: %s", entity_id)

        for idx, state in enumerate(hist): #hypothsis: states are ordered chronologically
            _LOGGER.debug("State %s", state.as_dict())
            try:
                _last_updated = state.last_updated_ts
            except:
                _last_updated = state.last_updated
            _LOGGER.debug("Switch of %s foreseen at %s", entity_id, _last_updated+timedelta(delta))
            #get the switch entity
            entity = hass.data[DOMAIN][SWITCH_PLATFORM][switch_id]

            target_time = _last_updated + timedelta(delta)
            # Because we called get_significant_states with include_start_time_state=True
            # the first element in hist should be the state at the start of the
            # simulation (unless HA has restarted recently - see recorder/history.py and RecorderRuns)
            # Do not add jitter to that first state time (which should be now anyways)
            if idx > 0:
                _LOGGER.debug("Randomize the event within a range of +/- %s sec", random_val)
                random_delta = random.uniform(-random_val, random_val) # random number in seconds
                _LOGGER.debug("Randomize the event of %s seconds", random_delta)
                random_delta = random_delta / 60 / 60 / 24 # random number in days
                target_time += timedelta(random_delta)
                initial_secs_left = (target_time - datetime.now(timezone.utc)).total_seconds()
                if initial_secs_left < MIN_DELAY and random_val > 0:
                    _LOGGER.debug("Random feature is used and wait is below min --> wait min time instead. target_time before %s", target_time)
                    # added to avoid too narrowed toggles that could happen because of the random delta
                    target_time = datetime.now(timezone.utc) + timedelta(MIN_DELAY / 60 / 60 / 24)
                    _LOGGER.debug("target_time after %s", target_time)
                else:
                    _LOGGER.debug("initial_secs_left %s, target_time %s", initial_secs_left, target_time)

            await entity.async_add_next_event(target_time, entity_id, state.state)

            # Rather than a single sleep until target_time, periodically check to see if
            # the simulation has been stopped
            while is_running(switch_id):
                #sleep as long as the event is not in the past
                secs_left = (target_time - datetime.now(timezone.utc)).total_seconds()
                if secs_left <= 0:
                    break
                await asyncio.sleep(min(secs_left, entity.interval))
            if not is_running(switch_id):
                return # exit if state is false
            #call service to turn on/off the light
            await update_entity(entity_id, state, entity.unavailable_as_off)
            #and remove this event from the attribute list of the switch entity
            await entity.async_remove_event(entity_id)

    async def update_entity(entity_id, state, unavailable_as_off):
        """ Switch the entity """
        # use service scene.apply ?? https://www.home-assistant.io/integrations/scene/
        """
        service_data = {}
        service_data[entity_id]["state"] = state.state
        if "brightness" in state.attributes:
            service_data[entity_id]["bigthness"] = state.attributes["brigthness"]
        if "rgb_color" in state.attributes:
            service_data[entity_id]["rgb_color"] = state.attributes["rgb_color"]
        if "current_position" in state.attributes:
            service_data[entity_id]["position"] = state.attributes["position"]
        if "current_tilt_position" in state.attributes:
            service_data[entity_id]["tilt_position"] = state.attributes["tilt_position"]
        service_data = {"entities": service_data}
        await hass.services.async_call("scene", "apply", service_data, blocking=False)
        """
        # get the domain of the entity
        domain = entity_id.split('.')[0]
        #prepare the data of the services
        service_data = {"entity_id": entity_id}
        if domain == "light":
            #if it is a light, checking the brigthness & color
            _LOGGER.debug("Switching light %s to %s", entity_id, state.state)
            if "brightness" in state.attributes and state.attributes["brightness"] is not None:
                _LOGGER.debug("Got attribute brightness: %s", state.attributes["brightness"])
                service_data["brightness"] = state.attributes["brightness"]
            # Preserve accurate color information, where applicable
            # see https://developers.home-assistant.io/docs/core/entity/light/#color-modes
            # see https://developers.home-assistant.io/docs/core/entity/light/#turn-on-light-device
            if "color_mode" in state.attributes and state.attributes["color_mode"] is not None:
                _LOGGER.debug("Got attribute color_mode: %s", state.attributes["color_mode"])
                color_mode = state.attributes["color_mode"]
                # color_temp is the only color mode with an attribute that's not color_mode+"_color"
                if color_mode != "color_temp":
                    # Attribute color_mode will be xy, hs, rgb...
                    color_mode = color_mode+"_color"
                if color_mode in state.attributes and state.attributes[color_mode] is not None:
                    service_data[color_mode] = state.attributes[color_mode]
            if state.state == "on" or state.state == "off" or (state.state == "unavailable" and unavailable_as_off):
                s = "on" if state.state == "on" else "off"
                await hass.services.async_call("light", "turn_"+s, service_data, blocking=False)
                event_data = {"entity_id": entity_id, "service": "light.turn_"+s, "service_data": service_data}
            else:
                _LOGGER.debug("State in neither on nor off (is %s), do nothing", state.state)

        elif domain == "cover":
            #if it is a cover, checking the position
            _LOGGER.debug("Switching Cover %s to %s", entity_id, state.state)
            if "current_tilt_position" in state.attributes:
                #Blocking open/close service if the tilt need to be called at the end
                blocking = True
            else:
                blocking = False
            if state.state == "closed" or (state.state == "unavailable" and unavailable_as_off):
                _LOGGER.debug("Closing cover %s", entity_id)
                await hass.services.async_call("cover", "close_cover", service_data, blocking=blocking)
                event_data = {"entity_id": entity_id, "service": "cover.close_cover", "service_data": service_data}
            elif state.state == "open":
                if "current_position" in state.attributes:
                    service_data["position"] = state.attributes["current_position"]
                    _LOGGER.debug("Changing cover %s position to %s", entity_id, state.attributes["current_position"])
                    await hass.services.async_call("cover", "set_cover_position", service_data, blocking=blocking)
                    event_data = {"entity_id": entity_id, "service": "cover.set_cover_position", "service_data": service_data}
                    del service_data["position"]
                else: #no position info, just open it
                    _LOGGER.debug("Opening cover %s", entity_id)
                    await hass.services.async_call("cover", "open_cover", service_data, blocking=blocking)
                    event_data = {"entity_id": entity_id, "service": "cover.open_cover", "service_data": service_data}
            if state.state in ["closed", "open"]: #nothing to do if closing or opening. Wait for the status to be 'stabilized'
                if "current_tilt_position" in state.attributes:
                    service_data["tilt_position"] = state.attributes["current_tilt_position"]
                    _LOGGER.debug("Changing cover %s tilt position to %s", entity_id, state.attributes["current_tilt_position"])
                    await hass.services.async_call("cover", "set_cover_tilt_position", service_data, blocking=False)
                    event_data = {"entity_id": entity_id, "service": "cover.set_cover_tilt_position", "service_data": service_data}
                    del service_data["tilt_position"]
        elif domain == "media_player":
            _LOGGER.debug("Switching media_player %s to %s", entity_id, state.state)
            if state.state == "playing":
                await hass.services.async_call("media_player", "media_play", service_data, blocking=False)
                event_data = {"entity_id": entity_id, "service": "media_player.media_play", "service_data": service_data}
            elif state.state != "unavailable" or unavailable_as_off: #idle, paused, off
                await hass.services.async_call("media_player", "media_stop", service_data, blocking=False)
                event_data = {"entity_id": entity_id, "service": "media_player.media_stop", "service_data": service_data}
            else:
                _LOGGER.debug("State in unavailable, do nothing")

        else:
            _LOGGER.debug("Switching entity %s to %s", entity_id, state.state)
            if state.state == "on" or state.state == "off" or (state.state == "unavailable_as_off" and unavailable_as_off):
                s = "on" if state.state == "on" else "off"
                await hass.services.async_call("homeassistant", "turn_"+s, service_data, blocking=False)
                event_data = {"entity_id": entity_id, "service": "homeassistant.turn_"+s, "service_data": service_data}
            else:
                _LOGGER.debug("State in neither on nor off (is %s), do nothing", state.state)
        try:
            if event_data is not None:
                hass.bus.fire(MY_EVENT, event_data)
        except NameError:
            pass

    def is_running(switch_id):
        """Returns true if the simulation is running"""
        try:
            entity = hass.data[DOMAIN][SWITCH_PLATFORM][switch_id]
        except Exception as e:
            _LOGGER.error("Could not load presence simulation switch %s", switch_id)
            raise e
        return entity.is_on

    async def launch_simulation_after_restart(call):
        for switch_id in hass.data[DOMAIN][SWITCH_PLATFORM]:
            _LOGGER.debug("Launch simulation after restart : switch is %s", switch_id)
            entity = hass.data[DOMAIN][SWITCH_PLATFORM][switch_id]
            #if the switch was on before previous restart
            if entity.is_on:
                _LOGGER.debug("Relaunching simulation %s", switch_id)
                #turn the internal flag to off in order to be able to call the turn on service
                entity.internal_turn_off()
                await entity.turn_on_async()

    hass.services.async_register(DOMAIN, "start", handle_presence_simulation)
    hass.services.async_register(DOMAIN, "stop", handle_stop_presence_simulation)
    hass.services.async_register(DOMAIN, "toggle", handle_toggle_presence_simulation)
    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, launch_simulation_after_restart)

    return True

async def async_remove_entry(hass, entry):
    """Handle removal of an entry."""
    try:
        await hass.config_entries.async_forward_entry_unload(
            entry, SWITCH_PLATFORM
        )
        _LOGGER.info(
            "Successfully removed switch from the presence simulation integration"
        )
    except ValueError:
        pass

async def update_listener(hass, entry):
    """Update listener after an update in the UI"""
    _LOGGER.debug("Updating listener");
    # The OptionsFlow saves data to options.
    if len(entry.options) > 0:
        entry.data = entry.options
        entry.options = {}
        switch_id = SWITCH_PLATFORM+"."+re.sub("[^0-9a-zA-Z]", "_", entry.data["switch"].lower())
        try:
            entity = hass.data[DOMAIN][SWITCH_PLATFORM][switch_id]
        except Exception as e:
            _LOGGER.debug("Switch with id %s not known", switch_id);
            return
        entity.update_config(entry)

async def async_migrate_entry(hass, config_entry) -> bool:
    _LOGGER.debug("Migrating from version %s", config_entry.version)
    if config_entry.version == 1:
        _LOGGER.debug("Will migrate to version 2")
        new = {**config_entry.data}
        new["switch"] = "Presence simulation"
        old_unique_id = UNIQUE_ID
        new_unique_id = "switch.presence_simulation"

        def update_unique_id(entity_entry):
            _LOGGER.debug("Updating unique id")
            return {"new_unique_id": entity_entry.unique_id.replace(old_unique_id, new_unique_id)}
        await async_migrate_entries(hass, config_entry.entry_id, update_unique_id)
        _LOGGER.debug("Entries migrated")

        hass.config_entries.async_update_entry(config_entry, data=new, unique_id=new_unique_id)
        config_entry.version = 2
    if config_entry.version == 2:
        _LOGGER.debug("Will migrate to version 3")
        new = {**config_entry.data}
        new["unavailable_as_off"] = False
        hass.config_entries.async_update_entry(config_entry, data=new)
        config_entry.version = 3
    return True
