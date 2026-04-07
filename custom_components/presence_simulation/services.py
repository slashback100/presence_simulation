"""Service handlers for presence simulation."""

import logging
import asyncio
import pytz
import random
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

from homeassistant.core import HomeAssistant, Context
from homeassistant.helpers import label_registry as lr, entity_registry as er

from .const import DOMAIN, SWITCH_PLATFORM, RESTORE_SCENE, SCENE_PLATFORM, MY_EVENT, MIN_DELAY
from .history import HistoryManager
from .entity_controller import EntityController

_LOGGER = logging.getLogger(__name__)


class PresenceSimulationServices:
    """Service handlers for presence simulation."""

    def __init__(
        self,
        hass: HomeAssistant,
        get_switch_entity: Callable[[], Dict[str, Any]],
        is_running: Callable[[str], bool],
        system_user: Optional[Any],
    ):
        self._hass = hass
        self._get_switch_entity = get_switch_entity
        self._is_running = is_running
        self._system_user = system_user
        self._entity_controller = EntityController(
            hass, system_user.id if system_user else None
        )

    @staticmethod
    def _get_scene_name(switch_id: str) -> str:
        """Generate scene name for restore."""
        tmp = switch_id.replace(".", "_") + "_" + RESTORE_SCENE
        import re
        return re.sub(r'_+', '_', tmp)

    async def start_simulation(
        self,
        call: Optional[Any],
        restart: bool = False,
        switch_id: Optional[str] = None,
    ) -> None:
        """Start the presence simulation."""
        after_ha_restart = False
        if call is not None:
            switches = self._get_switch_entity()
            _LOGGER.debug("All Switches: %s", switches)
            for sid in switches:
                _LOGGER.debug(switches[sid])

            if "switch_id" in call.data:
                switch_id = call.data.get("switch_id")
                entity = self._get_switch_entity()[switch_id]
            elif len(self._get_switch_entity()) == 1:
                switch_id = list(self._get_switch_entity())[0]
                entity = self._get_switch_entity()[switch_id]
            else:
                _LOGGER.error(
                    "Since you have several presence simulation switch, you have to add a switch_id parameter in the service call"
                )
                return

            internal = call.data.get("internal", False) and call.data.get("internal")
            if not self._is_running(switch_id) and not internal:
                if "entity_id" in call.data:
                    if isinstance(call.data.get("entity_id"), list):
                        await entity.set_entities(call.data.get("entity_id"))
                    else:
                        await entity.set_entities([call.data.get("entity_id")])
                if "labels" in call.data:
                    await entity.set_labels(call.data.get("labels"))
                if "delta" in call.data:
                    await entity.set_delta(call.data.get("delta", 7))
                if "restore_states" in call.data:
                    await entity.set_restore(call.data.get("restore_states", False))
                if "random" in call.data:
                    await entity.set_random(call.data.get("random", 0))
                if "unavailable_as_off" in call.data:
                    await entity.set_unavailable_as_off(call.data.get("unavailable_as_off", 0))
                if "brightness" in call.data:
                    await entity.set_brightness(call.data.get("brightness", 0))
                if "after_ha_restart" in call.data:
                    after_ha_restart = call.data.get("after_ha_restart", False)
        else:
            entity = self._get_switch_entity()[switch_id]
            await entity.reset_default_values_async()

        _LOGGER.debug("Switch id %s", switch_id)
        _LOGGER.debug("Is already running ? %s", entity.state)
        if self._is_running(switch_id):
            _LOGGER.warning("Presence simulation already running. Doing nothing")
            return

        current_date = datetime.now(timezone.utc)
        minus_delta = current_date + timedelta(-entity.delta)

        try:
            expanded_entities = await self._expand_entities(entity.entities)
        except Exception as e:
            _LOGGER.error("Error during identifying entities: " + str(entity.entities))
            return

        try:
            expanded_labels = await self._expand_labels(entity.labels)
        except Exception as e:
            _LOGGER.error("Error during identifying labels: " + str(entity.labels))
            return

        expanded_entities += expanded_labels

        if len(expanded_entities) == 0:
            _LOGGER.error("Error during identifying entities, no valid entities has been found")
            return

        entity.internal_turn_on()
        _LOGGER.debug("Presence simulation started")

        if not restart:
            try:
                await entity.set_start_datetime(datetime.now(self._hass.config.time_zone))
            except Exception as e:
                try:
                    presence_timezone = await asyncio.get_event_loop().run_in_executor(
                        None, pytz.timezone, self._hass.config.time_zone
                    )
                    await entity.set_start_datetime(datetime.now(presence_timezone))
                except Exception as e:
                    _LOGGER.warning("Start datetime could not be set to HA timezone: %s", e)
                    await entity.set_start_datetime(datetime.now())

            if entity.restore and not after_ha_restart:
                service_data: Dict[str, Any] = {}
                service_data["scene_id"] = self._get_scene_name(switch_id)
                service_data["snapshot_entities"] = expanded_entities
                _LOGGER.debug("Saving scene before launching the simulation")
                try:
                    context = Context(
                        user_id=self._system_user.id if self._system_user else None
                    )
                    await self._hass.services.async_call(
                        "scene", "create", service_data, blocking=True, context=context
                    )
                except Exception as e:
                    _LOGGER.error(
                        "Scene could not be created, continue without the restore functionality: %s",
                        e,
                    )

        _LOGGER.debug("Getting the historic from %s for %s", minus_delta, expanded_entities)

        from homeassistant.components.recorder import get_instance

        get_instance(self._hass).async_add_executor_job(
            self._fetch_and_handle_history,
            self._hass,
            minus_delta,
            expanded_entities,
            switch_id,
            call,
        )

    def _fetch_and_handle_history(
        self,
        hass: HomeAssistant,
        minus_delta: datetime,
        expanded_entities: List[str],
        switch_id: str,
        call: Optional[Any],
    ) -> None:
        """Fetch history and dispatch to entity simulators."""
        history = HistoryManager.get_history(hass, minus_delta, expanded_entities)
        entity = self._get_switch_entity()[switch_id]
        filtered_history = HistoryManager.filter_out_undefined(
            history, not entity.unavailable_as_off
        )
        _LOGGER.debug("history after filtering: %s", filtered_history)

        for entity_id in filtered_history:
            _LOGGER.debug("Entity %s", entity_id)
            # Use create_task (thread-safe version) instead of async_create_task
            hass.create_task(
                self._simulate_single_entity(
                    switch_id,
                    entity_id,
                    filtered_history[entity_id],
                    entity.delta,
                    entity.random,
                )
            )

        hass.create_task(self._schedule_restart(call, switch_id=switch_id))
        _LOGGER.debug("All async tasks launched")

    async def _simulate_single_entity(
        self,
        switch_id: str,
        entity_id: str,
        hist: List[Any],
        delta: int,
        random_val: int,
    ) -> None:
        """Replay the historic of one entity."""
        _LOGGER.debug("Simulate one entity: %s", entity_id)

        entity = self._get_switch_entity()[switch_id]
        is_running = self._is_running
        event_fire = self._hass.bus.fire

        for idx, state in enumerate(hist):
            _LOGGER.debug("State %s", state.as_dict())
            try:
                last_updated = state.last_updated_ts
            except AttributeError:
                last_updated = state.last_updated

            target_time = last_updated + timedelta(delta)
            _LOGGER.debug("Switch of %s foreseen at %s", entity_id, target_time + timedelta(delta))

            if idx > 0:
                _LOGGER.debug("Randomize the event within a range of +/- %s sec", random_val)
                random_delta = random.uniform(-random_val, random_val)
                _LOGGER.debug("Randomize the event of %s seconds", random_delta)
                random_delta = random_delta / 60 / 60 / 24
                target_time += timedelta(random_delta)
                initial_secs_left = (target_time - datetime.now(timezone.utc)).total_seconds()

                if initial_secs_left < MIN_DELAY and random_val > 0:
                    _LOGGER.debug(
                        "Random feature is used and wait is below min --> wait min time instead. target_time before %s",
                        target_time,
                    )
                    target_time = datetime.now(timezone.utc) + timedelta(seconds=MIN_DELAY)
                    _LOGGER.debug("target_time after %s", target_time)
                else:
                    _LOGGER.debug(
                        "initial_secs_left %s, target_time %s", initial_secs_left, target_time
                    )

            await entity.async_add_next_event(target_time, entity_id, state.state)

            while is_running(switch_id):
                secs_left = (target_time - datetime.now(timezone.utc)).total_seconds()
                if secs_left <= 0:
                    break
                await asyncio.sleep(min(secs_left, entity.interval))

            if not is_running(switch_id):
                return

            await self._entity_controller.update_entity(
                entity_id,
                state,
                entity.unavailable_as_off,
                entity.brightness,
                idx > 0,
                event_fire,
                MY_EVENT,
            )
            await entity.async_remove_event(entity_id)

    async def stop_simulation(
        self,
        call: Optional[Any],
        restart: bool = False,
        switch_id: Optional[str] = None,
    ) -> None:
        """Stop the presence simulation."""
        _LOGGER.debug("Stopped presence simulation")
        if call is not None:
            if "switch_id" in call.data:
                switch_id = call.data.get("switch_id")
            elif len(self._get_switch_entity()) == 1:
                switch_id = list(self._get_switch_entity())[0]
            else:
                _LOGGER.error(
                    "Since you have several presence simulation switch, you have to add a switch_id parameter in the service call"
                )
                return

        if self._is_running(switch_id):
            await self._do_stop(switch_id, restart)
        else:
            _LOGGER.warning(
                "Presence simulation switch %s is not on, can't be turned off", switch_id
            )

    async def _do_stop(self, switch_id: str, restart: bool = False) -> None:
        """Actually perform the stop operation."""
        entity = self._get_switch_entity()[switch_id]
        entity.internal_turn_off()

        if not restart:
            await entity.reset_start_datetime()
            await entity.reset_entities()
            await entity.reset_labels()
            await entity.reset_delta()
            await entity.reset_random()

            scene = self._hass.states.get(
                SCENE_PLATFORM + "." + self._get_scene_name(switch_id)
            )
            if scene is not None and entity.restore:
                service_data: Dict[str, Any] = {}
                service_data["entity_id"] = (
                    SCENE_PLATFORM + "." + self._get_scene_name(switch_id)
                )
                _LOGGER.debug("Restoring scene after the simulation")
                try:
                    context = Context(
                        user_id=self._system_user.id if self._system_user else None
                    )
                    await self._hass.services.async_call(
                        "scene", "turn_on", service_data, blocking=False, context=context
                    )
                except Exception as e:
                    _LOGGER.error(
                        "Error when restoring the scene after the simulation: %s", e
                    )

            await entity.reset_restore_states()

    async def toggle_simulation(self, call: Any) -> None:
        """Toggle the presence simulation."""
        if "switch_id" in call.data:
            switch_id = call.data.get("switch_id")
        elif len(self._get_switch_entity()) == 1:
            switch_id = list(self._get_switch_entity())[0]
        else:
            _LOGGER.error(
                "Since you have several presence simulation switch, you have to add a switch_id parameter in the service call"
            )
            return

        if self._is_running(switch_id):
            await self.stop_simulation(call, restart=False)
        else:
            await self.start_simulation(call, restart=False)

    async def _schedule_restart(self, call: Any, switch_id: str) -> None:
        """Make sure that once delta days is passed, relaunch the simulation."""
        entity = self._get_switch_entity()[switch_id]
        await entity.reset_default_values_async()
        _LOGGER.debug("Presence simulation will be relaunched in %i days", entity.delta)

        start_plus_delta = datetime.now(timezone.utc) + timedelta(entity.delta)

        while self._is_running(switch_id):
            secs_left = (start_plus_delta - datetime.now(timezone.utc)).total_seconds()
            if secs_left <= 0:
                break
            await asyncio.sleep(min(secs_left, entity.interval))

        if self._is_running(switch_id):
            _LOGGER.debug("%s has passed, presence simulation is relaunched", entity.delta)
            await self.stop_simulation(call, restart=True, switch_id=switch_id)
            await self.start_simulation(call, restart=True, switch_id=switch_id)

    async def _expand_entities(self, entities: List[str]) -> List[str]:
        """Expand group entities to their member entities."""
        entities_new: List[str] = []
        for entity in entities:
            await asyncio.sleep(0)
            if self._hass.states.get(entity) is None:
                _LOGGER.error(
                    "Error when trying to identify entity %s, it seems it doesn't exist. Continuing without this entity",
                    entity,
                )
            else:
                if "entity_id" in self._hass.states.get(entity).attributes:
                    group_entities = self._hass.states.get(entity).attributes["entity_id"]
                    group_entities_expanded = await self._expand_entities(group_entities)
                    _LOGGER.debug("State %s", group_entities_expanded)
                    entities_new.extend(group_entities_expanded)
                else:
                    _LOGGER.debug(
                        "Entity %s has no attribute entity_id, it is not a group nor a light group",
                        entity,
                    )
                    entities_new.append(entity)
        return entities_new

    async def _expand_labels(self, labels: List[str]) -> List[str]:
        """Expand labels to entity IDs."""
        labels_new: List[str] = []
        _LOGGER.debug("expand labels %s", labels)
        label_reg = lr.async_get(self._hass)
        entity_reg = er.async_get(self._hass)
        for label_str in labels:
            _LOGGER.debug("expand label %s", label_str)
            await asyncio.sleep(0)
            if label := label_reg.async_get_label(label_str):
                _LOGGER.debug("expand label_id %s", label.label_id)
                for entry in er.async_entries_for_label(entity_reg, label.label_id):
                    _LOGGER.debug("expand entry %s", entry.entity_id)
                    labels_new.append(entry.entity_id)
        return labels_new

    async def handle_service_start(self, call: Any) -> None:
        """Service handler for start."""
        await self.start_simulation(call, False, None)

    async def handle_service_stop(self, call: Any) -> None:
        """Service handler for stop."""
        await self.stop_simulation(call, False, None)

    async def handle_service_toggle(self, call: Any) -> None:
        """Service handler for toggle."""
        await self.toggle_simulation(call)
