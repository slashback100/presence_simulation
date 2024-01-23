"""Component to integrate with presence_simulation."""

import logging
import time
import asyncio
import json
import pytz
import random
import json
from datetime import datetime,timedelta,timezone
from homeassistant.components.recorder.history import get_significant_states
from homeassistant.components.recorder import get_instance
import homeassistant.util.dt as dt_util
from homeassistant.const import EVENT_HOMEASSISTANT_START
try:
    from homeassistant.components.recorder.db_schema import States, StateAttributes, StatesMeta
except ImportError:
    from homeassistant.components.recorder.models import States, StateAttributes
from homeassistant.components.recorder.const import DATA_INSTANCE
from .const import (
        DOMAIN,
        SWITCH_PLATFORM,
        SWITCH,
        RESTORE_SCENE,
        SCENE_PLATFORM,
        MY_EVENT
)
_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, entry):
    """Set up this component using config flow."""
    _LOGGER.debug("async setup entry %s", entry.data["entities"])
    unsub = entry.add_update_listener(update_listener)

    # Use `hass.async_create_task` to avoid a circular dependency between the platform and the component
    hass.async_create_task(hass.config_entries.async_forward_entry_setup(entry, SWITCH_PLATFORM))
    if 'interval' in entry.data:
        interval = entry.data['interval']
    else:
        interval = 30
    if 'restore' in entry.data:
        restore = entry.data['restore']
    else:
        restore = False
    if 'random' in entry.data:
        random = entry.data['random']
    else:
        random = 0
    elms = []
    for elm in entry.data["entities"].split(","):
        elms += [elm.strip()]
    return await async_mysetup(hass, elms, entry.data["delta"], interval, restore, random)

async def async_setup(hass, config):
    """Set up this component using YAML."""
    if config.get(DOMAIN) is None:
        # We get here if the integration is set up using config flow
        return True
    return await async_mysetup(hass, config[DOMAIN].get("entity_id",[]), config[DOMAIN].get('delta', "7"), config[DOMAIN].get('interval', '30'), config[DOMAIN].get('restore', False), config[DOMAIN].get('random', '0'))


async def async_mysetup(hass, entities, deltaStr, refreshInterval, restoreParam, randomParam):
    """Set up this component (YAML or UI)."""
    #delta is the size in days of the historic to get from the DB
    delta = int(deltaStr)
    #interval is the number of seconds the component will wait before checking if the entity need to be switch
    interval = int(refreshInterval)
    restoreAfterStop = restoreParam
    addRandomTime = randomParam
    previous_attribute = {}
    _LOGGER.debug("Config: Entities for presence simulation: %s", entities)
    _LOGGER.debug("Config: Cycle of %s days", delta)
    _LOGGER.debug("Config: Scan interval of %s seconds", interval)
    _LOGGER.debug("Config: Restore state: %s", restoreAfterStop)
    _LOGGER.debug("Config: Add random time (s): %s", addRandomTime)
    _LOGGER.debug("Config: Timezone that will be used to display datetime: %s", hass.config.time_zone)

    async def stop_presence_simulation(err=None, restart=False):
        """Stop the presence simulation, raising a potential error"""
        #get the switch entity
        entity = hass.data[DOMAIN][SWITCH_PLATFORM][SWITCH]
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
            _LOGGER.debug("entity.restore_states %s", await entity.restore_states())
            scene = hass.states.get(SCENE_PLATFORM+"."+RESTORE_SCENE)
            if scene is not None and await entity.restore_states():
                service_data = {}
                service_data["entity_id"] = SCENE_PLATFORM+"."+RESTORE_SCENE
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

    async def handle_stop_presence_simulation(call, restart=False):
        """Stop the presence simulation"""
        _LOGGER.debug("Stopped presence simulation")
        await stop_presence_simulation(restart=restart)

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

    async def handle_presence_simulation(call, restart=False, entities_after_restart=None, delta_after_restart=None, random_after_restart=None):
        """Start the presence simulation"""
        if call is not None: #if we are here, it is a call of the service, or a restart at the end of a cycle
            if isinstance(call.data.get("entity_id", entities), list):
                overridden_entities = call.data.get("entity_id", entities)
            else:
                overridden_entities = [call.data.get("entity_id", entities)]
            overridden_delta = call.data.get("delta", delta)
            overridden_restore = call.data.get("restore_states", restoreAfterStop)
            overridden_random = call.data.get("random", addRandomTime)
        else: #if we are it is a call from the toggle service or from the turn_on action of the switch entity
              # or this is a restart and the simulation was launched after a restart of HA
            if entities_after_restart is not None:
                overridden_entities = entities_after_restart
            else:
                overridden_entities = entities
            if delta_after_restart is not None:
                overridden_delta = delta_after_restart
            else:
                overridden_delta = delta
            if random_after_restart is not None:
                overridden_random = random_after_restart
            else:
                overridden_random = addRandomTime
            overridden_restore = restoreAfterStop

        #get the switch entity
        entity = hass.data[DOMAIN][SWITCH_PLATFORM][SWITCH]
        _LOGGER.debug("Is already running ? %s", entity.state)
        if is_running():
            _LOGGER.warning("Presence simulation already running. Doing nothing")
            return

        current_date = datetime.now(timezone.utc)
        #compute the start date that will be used in the query to get the historic of the entities
        minus_delta = current_date + timedelta(-overridden_delta)
        #expand the entities, meaning replace the groups with the entities in it
        try:
            expanded_entities = await async_expand_entities(overridden_entities)
        except Exception as e:
            _LOGGER.error("Error during identifing entities: "+overridden_entities)
            return

        if len(expanded_entities) == 0:
            _LOGGER.error("Error during identifing entities, no valid entities has been found")
            return

        _LOGGER.debug("setting restore states %s", overridden_restore)
        await entity.set_restore_states(overridden_restore)
        await entity.set_random(overridden_random)
        await entity.set_entities(expanded_entities)
        await entity.set_delta(overridden_delta)
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
            if overridden_restore:
                service_data = {}
                service_data["scene_id"] = RESTORE_SCENE
                service_data["snapshot_entities"] = expanded_entities
                _LOGGER.debug("Saving scene before launching the simulation")
                try:
                    await hass.services.async_call("scene", "create", service_data, blocking=True)
                except Exception as e:
                    _LOGGER.error("Scene could not be created, continue without the restore functionality: %s", e)

        _LOGGER.debug("Getting the historic from %s for %s", minus_delta, expanded_entities)
        await get_instance(hass).async_add_executor_job(handle_presence_simulation_sync, hass, call, minus_delta, expanded_entities, overridden_delta, overridden_random, entities_after_restart, delta_after_restart)

    def handle_presence_simulation_sync(hass, call, minus_delta, expanded_entities, overridden_delta, overridden_random, entities_after_restart, delta_after_restart):
        dic = get_significant_states(hass=hass, start_time=minus_delta, entity_ids=expanded_entities, include_start_time_state=True, significant_changes_only=False)
        _LOGGER.debug("history: %s", dic)
        # handle_presence_simulation_sync is called from async_add_executor_job,
        # so may not be running in the event loop, so we can't call hass.async_create_task.
        # instead calling hass.create_task, which is thread_safe.
        # See homeassistant/core.py:create_task
        for entity_id in dic:
            _LOGGER.debug('Entity %s', entity_id)
            #launch an async task by entity_id
            hass.create_task(simulate_single_entity(entity_id, dic[entity_id], overridden_delta, overridden_random))

        #launch an async task that will restart the simulation after the delay has passed
        hass.create_task(restart_presence_simulation(call, entities_after_restart=entities_after_restart, delta_after_restart=delta_after_restart, random_after_restart=overridden_random))
        _LOGGER.debug("All async tasks launched")


    async def handle_toggle_presence_simulation(call):
        """Toggle the presence simulation"""
        if is_running():
            await handle_stop_presence_simulation(call, restart=False)
        else:
            await handle_presence_simulation(call, restart=False)


    async def restart_presence_simulation(call, entities_after_restart=None, delta_after_restart=None, random_after_restart=None):
        """Make sure that once _delta_ days is passed, relaunch the presence simulation for another _delta_ days"""
        if call is not None: #if we are here, it is a call of the service, or a restart at the end of a cycle
            overridden_delta = call.data.get("delta", delta)
        else:
            if delta_after_restart is None:
                overridden_delta = delta
            else:
                overridden_delta = delta_after_restart
        _LOGGER.debug("Presence simulation will be relaunched in %i days", overridden_delta)
        #compute the moment the presence simulation will have to be restarted
        start_plus_delta = datetime.now(timezone.utc) + timedelta(overridden_delta)
        while is_running():
            #sleep until the 'delay' is passed
            secs_left = (start_plus_delta - datetime.now(timezone.utc)).total_seconds()
            if secs_left <= 0:
                break
            await asyncio.sleep(min(secs_left, interval))

        if is_running():
            _LOGGER.debug("%s has passed, presence simulation is relaunched", overridden_delta)
            #Call to stop needed to avoid the start to do nothing since already running
            await handle_stop_presence_simulation(call, restart=True)
            await handle_presence_simulation(call, restart=True, entities_after_restart=entities_after_restart, delta_after_restart=delta_after_restart, random_after_restart=random_after_restart)

    async def simulate_single_entity(entity_id, hist, overridden_delta, overridden_random):
        """This method will replay the historic of one entity received in parameter"""
        _LOGGER.debug("Simulate one entity: %s", entity_id)

        for idx, state in enumerate(hist): #hypothsis: states are ordered chronologically
            _LOGGER.debug("State %s", state.as_dict())
            try:
                _last_updated = state.last_updated_ts
            except:
                _last_updated = state.last_updated
            _LOGGER.debug("Switch of %s foreseen at %s", entity_id, _last_updated+timedelta(overridden_delta))
            #get the switch entity
            entity = hass.data[DOMAIN][SWITCH_PLATFORM][SWITCH]
            await entity.async_add_next_event(_last_updated+timedelta(overridden_delta), entity_id, state.state)

            target_time = _last_updated + timedelta(overridden_delta)
            # Because we called get_significant_states with include_start_time_state=True
            # the first element in hist should be the state at the start of the
            # simulation (unless HA has restarted recently - see recorder/history.py and RecorderRuns)
            # Do not add jitter to that first state time (which should be now anyways)
            if idx > 0:
                random_delta = random.uniform(-overridden_random, overridden_random) # random number in seconds
                _LOGGER.debug("Randomize the event of %s seconds", random_delta)
                random_delta = random_delta / 60 / 60 / 24 # random number in days
                target_time += timedelta(random_delta)

            # Rather than a single sleep until target_time, periodically check to see if
            # the simulation has been stopped.
            while is_running():
                #sleep as long as the event is not in the past
                secs_left = (target_time - datetime.now(timezone.utc)).total_seconds()
                if secs_left <= 0:
                    break
                await asyncio.sleep(min(secs_left, interval))
            if not is_running():
                return # exit if state is false
            #call service to turn on/off the light
            await update_entity(entity_id, state)
            #and remove this event from the attribute list of the switch entity
            await entity.async_remove_event(entity_id)

    async def update_entity(entity_id, state):
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
                if color_mode in state.attributes:
                    service_data[color_mode] = state.attributes[color_mode]
            if state.state == "on" or state.state == "off":
                await hass.services.async_call("light", "turn_"+state.state, service_data, blocking=False)
                event_data = {"entity_id": entity_id, "service": "light.turn_"+ state.state, "service_data": service_data}
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
            if state.state == "closed":
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
            elif state.state != "unavailable": #idle, paused, off
                await hass.services.async_call("media_player", "media_stop", service_data, blocking=False)
                event_data = {"entity_id": entity_id, "service": "media_player.media_stop", "service_data": service_data}
            else:
                _LOGGER.debug("State in unavailable, do nothing")

        else:
            _LOGGER.debug("Switching entity %s to %s", entity_id, state.state)
            if state.state == "on" or state.state == "off":
                await hass.services.async_call("homeassistant", "turn_"+state.state, service_data, blocking=False)
                event_data = {"entity_id": entity_id, "service": "homeassistant.turn_"+state.state, "service_data": service_data}
            else:
                _LOGGER.debug("State in neither on nor off (is %s), do nothing", state.state)
        if event_data is not None:
            hass.bus.fire(MY_EVENT, event_data)

    def is_running():
        """Returns true if the simulation is running"""
        entity = hass.data[DOMAIN][SWITCH_PLATFORM][SWITCH]
        return entity.is_on

    async def restore_state(call):
        """Restore states."""
        _LOGGER.debug("Restoring states after HA start")

        """ retrieve the last status after last shutdown and restore it """
        previous_attribute = {}
        await get_instance(hass).async_add_executor_job(_restore_state_sync, previous_attribute)

        _LOGGER.debug("Previous attribute is "+json.dumps(previous_attribute))
        if previous_attribute["was_running"]:
          # do not try to restore the previous state after the restart cause the scene has been lost during the restart
          await handle_presence_simulation(call = None,
              entities_after_restart = previous_attribute['entity_id'],
              delta_after_restart = previous_attribute["delta"],
              random_after_restart = previous_attribute["random"])
        else:
            _LOGGER.debug("Setting switch to off")
            # Finish initializing switch state
            entity = hass.data[DOMAIN][SWITCH_PLATFORM][SWITCH]
            entity.internal_turn_off()

    def _restore_state_sync(previous_attribute):
        _LOGGER.debug("In restore State Sync")

        session = hass.data[DATA_INSTANCE].get_session()
        result = session.query(States.state, StateAttributes.shared_attrs).join(StatesMeta).filter(States.attributes_id == StateAttributes.attributes_id).filter(States.metadata_id == StatesMeta.metadata_id).filter(StatesMeta.entity_id == SWITCH_PLATFORM+"."+SWITCH).order_by(States.last_updated_ts.desc()).limit(1)

        # result[0] is a tuple of (state, attributes-json)
        if result.count() > 0 and result[0][0] == "on":
          previous_attribute["was_running"] = True
          _LOGGER.debug("Simulation was on before last shutdown, restarting it.")

          resultJson = json.loads(result[0][1])
          if 'delta' in resultJson:
            previous_attribute['delta'] = resultJson['delta']
          else:
            previous_attribute['delta'] = delta
          if 'random' in resultJson:
            previous_attribute['random'] = resultJson['random']
          else:
            previous_attribute['random'] = addRandomTime
          if 'entity_id' in resultJson:
              previous_attribute['entity_id'] = resultJson['entity_id']
          else:
              _LOGGER.error("In _restore_state_sync, entity_id attribute missing")
              previous_attribute["was_running"] = False
        else:
          previous_attribute["was_running"] = False

    hass.services.async_register(DOMAIN, "start", handle_presence_simulation)
    hass.services.async_register(DOMAIN, "stop", handle_stop_presence_simulation)
    hass.services.async_register(DOMAIN, "toggle", handle_toggle_presence_simulation)
    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_START, restore_state)

    return True

async def update_listener(hass, entry):
    """Update listener after an update in the UI"""
    _LOGGER.debug("Updating listener");
    # The OptionsFlow saves data to options.
    if len(entry.options) > 0:
        entry.data = entry.options
        entry.options = {}
        elms = []
        for elm in entry.data["entities"].split(","):
            elms += [elm.strip()]
        await async_mysetup(hass, elms, entry.data["delta"], entry.data["interval"], entry.data["restore"], entry.data["random"])
