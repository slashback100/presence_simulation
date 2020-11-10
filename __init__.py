"""Component to integrate with presence_simulation."""

import logging
import time
import asyncio
from datetime import datetime,timedelta,timezone
from homeassistant.components import history

_LOGGER = logging.getLogger(__name__)
DOMAIN = "presence_simulation"

async def async_setup_entry(hass, entry):
    _LOGGER.debug("async setup entry %s", entry.data["entities"])
    return await async_mysetup(hass, [entry.data["entities"]], entry.data["delta"])

async def async_setup(hass, config):
    return await async_mysetup(hass, config[DOMAIN].get("entity_id",[]), config[DOMAIN].get('delta', "7"))

async def async_mysetup(hass, entities, deltaStr):
    """Set up this component using YAML."""
    hass.states.async_set(DOMAIN+".running", "false")
    #entities = config[DOMAIN].get("entity_id",[])
    #delta = config[DOMAIN].get("delta",7)
    delta = int(deltaStr)
    _LOGGER.debug("Entities for presence simulation: %s", entities)

    async def stop_presence_simulation(err=None):
        hass.states.async_set(DOMAIN+".running", "false")
        if err is not None:
            _LOGGER.debug("Error in presence simulation, exiting")
            raise e

    async def handle_stop_presence_simulation(call):
        """Handle the service call."""
        _LOGGER.debug("Stopped presence simulation")
        await stop_presence_simulation()

    async def async_expand_entities(entities):
        entities_new = []
        for entity in entities:
            await asyncio.sleep(0)
            if entity[0:5] == "group":
                try:
                    group_entities = hass.states.get(entity).as_dict()["attributes"]["entity_id"]
                except Exception as e:
                    _LOGGER.error("Error when trying to identify entity %s: %s", entity, e)
                else:
                    #await stop_presence_simulation(e)
                    group_entities_expanded = await async_expand_entities(group_entities)
                    _LOGGER.debug("State %s", group_entities_expanded)
                    for tmp in group_entities_expanded:
                        entities_new.append(tmp)
            else:
                try:
                    hass.states.get(entity)
                except Exception as e:
                    _LOGGER.error("Error when trying to identify entity %s: %s", entity, e)
                else:
                    entities_new.append(entity)
        return entities_new
    
    async def handle_presence_simulation(call):
        """Handle the service call."""
        _LOGGER.debug("Is alreay running ? %s", hass.states.get(DOMAIN+'.running').state)
        if hass.states.get(DOMAIN+'.running').state == "true":
            _LOGGER.warning("Presence simulation already running")
            return
        running = True
        hass.states.async_set(DOMAIN+".running", "true")
        _LOGGER.debug("Started presence simulation")
        #while hass.states.get(DOMAIN+'.running').state == "true": # an infinite loop to keep the simulator running forever

        current_date = datetime.now(timezone.utc)
        minus_delta = current_date + timedelta(-delta)
        expanded_entities = await async_expand_entities(entities)
        _LOGGER.debug("Getting the historic from %s for %s", minus_delta, expanded_entities)
        dic = history.get_significant_states(hass=hass, start_time=minus_delta, entity_ids=expanded_entities)
        _LOGGER.debug("history: %s", dic)
        for entity_id in dic:
            _LOGGER.debug('Entity %s', entity_id)
            #launch a thread by entity_id
            #put the tasks in a tab to be able to kill them when the service stops
            hass.async_create_task(simulate_single_entity(entity_id, dic[entity_id])) #coroutine

        hass.async_create_task(restart_presence_simulation())
        _LOGGER.debug("All async tasks launched")
    
    async def handle_toggle_presence_simulation(call):
        if hass.states.get(DOMAIN+'.running').state == "true":
            handle_stop_presence_simulation(call)
        else:
            await handle_presence_simulation(call)


    async def restart_presence_simulation():
        _LOGGER.debug("Presence simulation will be relaunched in %i days", delta)
        start_plus_delta = datetime.now(timezone.utc) + timedelta(delta)
        while hass.states.get(DOMAIN+'.running').state == "true": 
            await asyncio.sleep(60) 
            now = datetime.now(timezone.utc) 
            if now > start_plus_delta:
                break
        
        if hass.states.get(DOMAIN+'.running').state == "true": 
            await handle_presence_simulation(None)

    async def simulate_single_entity(entity_id, hist):
        _LOGGER.debug("Simulate one entity: %s", entity_id)
        for state in hist: #hypothsis: states are ordered chronologically
            _LOGGER.debug("State %s", state.as_dict())
            _LOGGER.debug("Switch of %s foreseen at %s", entity_id, state.last_changed+timedelta(delta))
            while hass.states.get(DOMAIN+'.running').state == "true": 
                minus_delta = datetime.now(timezone.utc) + timedelta(-delta)
                #_LOGGER.debug("%s <= %s", state.last_changed, minus_delta)
                if state.last_changed <= minus_delta:
                    break
                #_LOGGER.debug("%s: will retry in 30 sec", entity_id)
                await asyncio.sleep(30)
            if hass.states.get(DOMAIN+'.running').state == "false":
                return # exit if state is false
            #call service to turn on/off the light
            _LOGGER.debug("Switching entity %s to %s", entity_id, state.state)
            await hass.services.async_call("homeassistant", "turn_"+state.state, {"entity_id": entity_id}, blocking=False)


    hass.services.async_register(DOMAIN, "start", handle_presence_simulation)
    hass.services.async_register(DOMAIN, "stop", handle_stop_presence_simulation)
    hass.services.async_register(DOMAIN, "toggle", handle_toggle_presence_simulation)

    return True

