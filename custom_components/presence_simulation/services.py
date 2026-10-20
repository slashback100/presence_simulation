"""Service handlers for presence simulation."""

import logging
import asyncio
import random
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

from homeassistant.core import HomeAssistant, Context
from homeassistant.helpers import label_registry as lr, entity_registry as er
from homeassistant.util import dt as dt_util

from .const import DOMAIN, SWITCH_PLATFORM, RESTORE_SCENE, SCENE_PLATFORM, MY_EVENT, MIN_DELAY
from .history import HistoryManager
from .entity_controller import EntityController
from .snapshot import SnapshotStore

_LOGGER = logging.getLogger(__name__)


def _parse_history_end(value: Any, hass: HomeAssistant) -> Optional[datetime]:
    """Parse a configured history cutoff as an aware UTC datetime."""
    if not value:
        return None
    history_end = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if history_end.tzinfo is None:
        history_end = history_end.replace(tzinfo=dt_util.get_default_time_zone())
    return history_end.astimezone(timezone.utc)


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
        # Per-switch generation counter. Every stop and every new dispatch
        # increments it; replay tasks capture the value at dispatch time and
        # abort as soon as it no longer matches. This kills "zombie" tasks that
        # sleep through a stop->start (cycle restart, snapshot replacement,
        # toggle within the poll interval) and would otherwise keep replaying
        # the same entity in parallel with the new run (#125).
        self._run_ids: Dict[str, int] = {}
        # Guards start_simulation against concurrent invocations: the
        # "already running" check happens before several awaits (snapshot load,
        # entity expansion, history fetch), so without this flag a second
        # start call in that window dispatches a duplicate set of tasks.
        self._starting: Dict[str, bool] = {}

    def _next_run_id(self, switch_id: str) -> int:
        """Invalidate every replay task and restart timer of a switch."""
        self._run_ids[switch_id] = self._run_ids.get(switch_id, 0) + 1
        return self._run_ids[switch_id]

    def _is_current_run(self, switch_id: str, run_id: int) -> bool:
        """Return True when no stop/restart happened since run_id was issued."""
        return self._run_ids.get(switch_id) == run_id

    def abort_simulation(self, switch_id: str, update_state: bool = True) -> None:
        """Invalidate every replay task of a switch without restoring the scene.

        Used when the config entry is unloaded or the switch entity is removed:
        the run must stop immediately, but there is no point fetching/resetting
        state or restoring the restore-scene at that point (#170).
        """
        self._next_run_id(switch_id)
        if not update_state:
            return
        entity = self._get_switch_entity().get(switch_id)
        if entity is not None:
            entity.internal_turn_off()

    @staticmethod
    def _get_scene_name(switch_id: str) -> str:
        """Generate scene name for restore."""
        tmp = switch_id.replace(".", "_") + "_" + RESTORE_SCENE
        import re
        return re.sub(r'_+', '_', tmp)

    def _get_entity(self, call: Any) -> tuple[str, Any] | tuple[None, None]:
        """Resolve the selected simulation switch."""
        if call and call.data.get("switch_id"):
            switch_id = call.data["switch_id"]
            return switch_id, self._get_switch_entity().get(switch_id)
        switches = self._get_switch_entity()
        if len(switches) == 1:
            switch_id = next(iter(switches))
            return switch_id, switches[switch_id]
        return None, None

    async def handle_service_snapshot(self, call: Any) -> None:
        """Capture the current recorder history into a small local snapshot."""
        switch_id, entity = self._get_entity(call)
        if entity is None:
            _LOGGER.error("Select a switch_id when more than one simulator exists")
            return
        try:
            history_end = _parse_history_end(call.data.get("history_end"), self._hass) or datetime.now(timezone.utc)
            delta = int(call.data.get("delta", entity.delta))
        except (TypeError, ValueError) as err:
            _LOGGER.error("Invalid snapshot settings: %s", err)
            return
        if delta < 1:
            _LOGGER.error("Snapshot delta must be at least one day")
            return
        entities = list(dict.fromkeys(await self._expand_entities(entity.entities) + await self._expand_labels(entity.labels)))
        if not entities:
            _LOGGER.error("Snapshot was not created: no valid entities")
            return
        history_start = history_end - timedelta(days=delta)
        history = await self._hass.async_add_executor_job(
            HistoryManager.get_history, self._hass, history_start, entities, history_end
        )
        history = HistoryManager.filter_out_undefined(history, not entity.unavailable_as_off)
        history = HistoryManager.remove_redundant_states(history)
        snapshot = await SnapshotStore(self._hass, switch_id).save(
            history, history_start, history_end, entities
        )
        await entity.set_snapshot_metadata(snapshot)
        entity.async_write_ha_state()
        if not snapshot["event_count"]:
            _LOGGER.warning("Snapshot for %s contains no usable events", switch_id)
            await self._hass.services.async_call(
                "persistent_notification", "create",
                {"title": "Presence Simulation", "message": "De opgeslagen historie bevat geen bruikbare gebeurtenissen."},
                blocking=False,
            )

    async def handle_service_demo_snapshot(self, call: Any) -> None:
        """Create a temporary seven-day evening routine for safe testing."""
        switch_id, entity = self._get_entity(call)
        if entity is None:
            return
        end = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        start = end - timedelta(days=7)
        schedule = (
            ("light.lamp_hal", "on", 16, 45), ("light.ledstrip_tv", "on", 17, 30),
            ("light.keuken_spots", "on", 19, 15), ("switch.verlichting_badkamer_l1", "on", 20, 45),
            ("switch.verlichting_badkamer_l1", "off", 21, 0), ("light.keuken_spots", "off", 21, 30),
            ("light.ledstrip_tv", "off", 21, 45), ("light.lamp_hal", "off", 22, 0),
        )
        from .snapshot import SnapshotState
        history: dict[str, list[Any]] = {}
        for day in range(7):
            for entity_id, state, hour, minute in schedule:
                moment = start + timedelta(days=day, hours=hour, minutes=minute)
                history.setdefault(entity_id, []).append(SnapshotState(state, {}, moment))
        snapshot = await SnapshotStore(self._hass, switch_id).save(history, start, end, list(history))
        snapshot["synthetic"] = True
        await SnapshotStore(self._hass, switch_id)._store.async_save(snapshot)
        await entity.set_snapshot_metadata(snapshot)
        entity.async_write_ha_state()

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

            # This option must be applied even when replacing a running simulation.
            if "use_snapshot" in call.data:
                await entity.set_use_snapshot(call.data.get("use_snapshot", False))

            internal = call.data.get("internal", False) and call.data.get("internal")
            # A normal switch turn-on is an internal service call.  When a
            # valid local snapshot exists, prefer it automatically so users
            # do not need to invoke the advanced `start` service manually.
            # An explicit `use_snapshot: false` always remains authoritative.
            if internal and "use_snapshot" not in call.data and not entity.use_snapshot:
                available_snapshot = await SnapshotStore(self._hass, switch_id).load()
                if available_snapshot and available_snapshot.get("event_count"):
                    await entity.set_use_snapshot(True)
                    await entity.set_snapshot_metadata(available_snapshot)
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
                if "history_end" in call.data:
                    await entity.set_history_end(call.data.get("history_end"))
                if "after_ha_restart" in call.data:
                    after_ha_restart = call.data.get("after_ha_restart", False)
        else:
            entity = self._get_switch_entity()[switch_id]
            await entity.reset_default_values_async()

        if self._starting.get(switch_id):
            _LOGGER.warning(
                "Presence simulation %s is already starting. Doing nothing", switch_id
            )
            return
        self._starting[switch_id] = True
        try:
            await self._start_simulation_locked(
                call, restart, switch_id, entity, after_ha_restart
            )
        finally:
            self._starting[switch_id] = False

    async def _start_simulation_locked(
        self,
        call: Optional[Any],
        restart: bool,
        switch_id: str,
        entity: Any,
        after_ha_restart: bool,
    ) -> None:
        """Body of start_simulation, executed with the starting flag held."""
        _LOGGER.debug("Switch id %s", switch_id)
        _LOGGER.debug("Is already running ? %s", entity.state)
        if self._is_running(switch_id):
            if entity.use_snapshot and call is not None:
                # A switch turn-on can reach this point while its restored
                # state is still "on". Replace that stale run so the snapshot
                # is actually dispatched instead of silently returning.
                _LOGGER.info("Replacing the running simulation with its saved snapshot")
                await self._do_stop(switch_id, restart=True)
            else:
                _LOGGER.warning("Presence simulation already running. Doing nothing")
                return

        current_date = datetime.now(timezone.utc)
        try:
            history_end = _parse_history_end(entity.history_end, self._hass)
        except (TypeError, ValueError) as err:
            _LOGGER.error("Invalid history_end value %r: %s", entity.history_end, err)
            return
        snapshot = None
        if entity.use_snapshot:
            snapshot = await SnapshotStore(self._hass, switch_id).load()
            await entity.set_snapshot_metadata(snapshot)
            if not snapshot or not snapshot.get("event_count"):
                _LOGGER.error("No usable Presence Simulation snapshot is available")
                await self._hass.services.async_call(
                    "persistent_notification", "create",
                    {"title": "Presence Simulation", "message": "Geen bruikbare opgeslagen historie. De simulatie is niet gestart."},
                    blocking=False,
                )
                return
            history_start = datetime.fromisoformat(snapshot["history_start"])
            history_end = datetime.fromisoformat(snapshot["history_end"])
            cycle_seconds = (history_end - history_start).total_seconds()
            cycle = max(0, int((current_date - history_end).total_seconds() // cycle_seconds))
            replay_offset = timedelta(seconds=cycle_seconds * (cycle + 1))
        elif history_end is None:
            history_start = current_date - timedelta(days=entity.delta)
            replay_offset = timedelta(days=entity.delta)
        else:
            history_start = history_end - timedelta(days=entity.delta)
            cycle_seconds = timedelta(days=entity.delta).total_seconds()
            cycle = max(0, int((current_date - history_end).total_seconds() // cycle_seconds))
            replay_offset = timedelta(days=entity.delta * (cycle + 1))

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
        # Dedup while preserving order: an entity can be referenced multiple times
        # (direct + via group + via label). Without dedup, _simulate_single_entity
        # runs in parallel for the same entity_id and fires turn_on/off in a race,
        # causing the flicker reported in #174, #193 and the stuck-on state in #179.
        expanded_entities = list(dict.fromkeys(expanded_entities))
        _LOGGER.debug("Deduplicated entities: %s", expanded_entities)

        if len(expanded_entities) == 0:
            _LOGGER.error("Error during identifying entities, no valid entities has been found")
            return

        await entity.set_simulated_entities(expanded_entities)
        await entity.set_history_window(history_start, history_end or current_date)
        entity.internal_turn_on()
        _LOGGER.debug("Presence simulation started")

        if not restart:
            await entity.set_start_datetime(dt_util.now())

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

        _LOGGER.debug("Getting the historic from %s to %s for %s", history_start, history_end, expanded_entities)

        from homeassistant.components.recorder import get_instance

        if snapshot:
            self._dispatch_history(
                SnapshotStore.deserialize(snapshot),
                switch_id,
                call,
                replay_offset,
                history_end,
                self._next_run_id(switch_id),
            )
        else:
            # Fetching history is blocking, but scheduling entity tasks must
            # return to Home Assistant's event loop.  Await the executor job
            # here instead of creating tasks from its worker thread.
            history = await get_instance(self._hass).async_add_executor_job(
                HistoryManager.get_history,
                self._hass,
                history_start,
                expanded_entities,
                history_end,
            )
            self._dispatch_history(
                history,
                switch_id,
                call,
                replay_offset,
                history_end,
                self._next_run_id(switch_id),
            )

    def _dispatch_history(
        self,
        history,
        switch_id: str,
        call: Optional[Any],
        replay_offset: timedelta,
        history_end: Optional[datetime],
        run_id: int,
    ) -> None:
        """Start replay tasks from recorder history or a persisted snapshot."""
        entity = self._get_switch_entity()[switch_id]
        filtered_history = HistoryManager.filter_out_undefined(history, not entity.unavailable_as_off)
        filtered_history = HistoryManager.remove_redundant_states(filtered_history)
        _LOGGER.debug("history after filtering: %s", filtered_history)

        for entity_id in filtered_history:
            _LOGGER.debug("Entity %s", entity_id)
            # We are on Home Assistant's event loop here.
            self._hass.async_create_task(
                self._simulate_single_entity(
                    switch_id,
                    entity_id,
                    filtered_history[entity_id],
                    replay_offset,
                    entity.random,
                    run_id,
                )
            )

        self._hass.async_create_task(
            self._schedule_restart(
                call, switch_id=switch_id, history_end=history_end, run_id=run_id
            )
        )
        _LOGGER.debug("All async tasks launched")

    async def _simulate_single_entity(
        self,
        switch_id: str,
        entity_id: str,
        hist: List[Any],
        replay_offset: timedelta,
        random_val: int,
        run_id: int,
    ) -> None:
        """Replay the historic of one entity."""
        _LOGGER.debug("Simulate one entity: %s", entity_id)

        entity = self._get_switch_entity()[switch_id]
        is_running = self._is_running
        is_current_run = self._is_current_run
        event_fire = self._hass.bus.fire

        last_past_state = None
        prev_target = None
        for idx, state in enumerate(hist):
            if not is_running(switch_id) or not is_current_run(switch_id, run_id):
                # The simulation was stopped or replaced by a newer run.
                return
            _LOGGER.debug("State %s", state.as_dict())
            try:
                last_updated = state.last_updated_ts
            except AttributeError:
                last_updated = state.last_updated

            target_time = last_updated + replay_offset
            _LOGGER.debug("Switch of %s foreseen at %s", entity_id, target_time)

            if idx > 0 and random_val > 0:
                _LOGGER.debug("Randomize the event within a range of +/- %s sec", random_val)
                random_delta = random.uniform(-random_val, random_val)
                _LOGGER.debug("Randomize the event of %s seconds", random_delta)
                target_time += timedelta(seconds=random_delta)

            if prev_target is not None:
                # Keep events ordered and at least MIN_DELAY apart, whatever
                # the random shifts: without this, random could bring an event
                # before its predecessor and MIN_DELAY was only measured
                # against "now", letting several events collapse onto
                # now+MIN_DELAY and flicker the entity (#125).
                min_target = prev_target + timedelta(seconds=MIN_DELAY)
                if target_time < min_target:
                    _LOGGER.debug(
                        "Event of %s would break the min delay with previous event --> shift to %s",
                        entity_id,
                        min_target,
                    )
                    target_time = min_target
            prev_target = target_time

            if target_time <= datetime.now(timezone.utc):
                last_past_state = state
                continue
            if last_past_state is not None:
                event_data = await self._entity_controller.update_entity(
                    entity_id,
                    last_past_state,
                    entity.unavailable_as_off,
                    entity.brightness,
                    False,
                    event_fire,
                    MY_EVENT,
                )
                if event_data:
                    await entity.set_last_event(event_data)
                last_past_state = None
            await entity.async_add_next_event(target_time, entity_id, state.state)

            while is_running(switch_id) and is_current_run(switch_id, run_id):
                secs_left = (target_time - datetime.now(timezone.utc)).total_seconds()
                if secs_left <= 0:
                    break
                await asyncio.sleep(min(secs_left, entity.interval))

            if not is_running(switch_id) or not is_current_run(switch_id, run_id):
                return

            event_data = await self._entity_controller.update_entity(
                entity_id,
                state,
                entity.unavailable_as_off,
                entity.brightness,
                idx > 0,
                event_fire,
                MY_EVENT,
            )
            if event_data:
                await entity.set_last_event(event_data)
            await entity.async_remove_event(entity_id)

        if last_past_state is not None and is_running(switch_id) and is_current_run(
            switch_id, run_id
        ):
            event_data = await self._entity_controller.update_entity(
                entity_id,
                last_past_state,
                entity.unavailable_as_off,
                entity.brightness,
                False,
                event_fire,
                MY_EVENT,
            )
            if event_data:
                await entity.set_last_event(event_data)

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
            # The switch already reports "off" but a previous run may still
            # have replay tasks alive (they only notice a stop at their next
            # poll). Invalidate them so the simulation can really be stopped
            # and does not keep switching entities on its own (#170).
            self._next_run_id(switch_id)
            _LOGGER.warning(
                "Presence simulation switch %s is not on, can't be turned off", switch_id
            )

    async def _do_stop(self, switch_id: str, restart: bool = False) -> None:
        """Actually perform the stop operation."""
        # Invalidate the replay tasks and the restart timer of this run: they
        # would otherwise only notice the stop at their next poll, and keep
        # running if the simulation is started again within the interval.
        self._next_run_id(switch_id)
        entity = self._get_switch_entity()[switch_id]
        entity.internal_turn_off()

        if not restart:
            await entity.reset_start_datetime()
            await entity.reset_entities()
            await entity.reset_labels()
            await entity.reset_delta()
            await entity.reset_random()
            await entity.reset_history_end()

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

    async def _schedule_restart(
        self,
        call: Any,
        switch_id: str,
        history_end: Optional[datetime] = None,
        run_id: Optional[int] = None,
    ) -> None:
        """Make sure that once delta days is passed, relaunch the simulation."""
        entity = self._get_switch_entity()[switch_id]
        use_snapshot = entity.use_snapshot
        await entity.reset_default_values_async()
        if use_snapshot:
            # A snapshot must survive cycle restarts and Home Assistant restarts.
            await entity.set_use_snapshot(True)
        _LOGGER.debug("Presence simulation will be relaunched in %i days", entity.delta)

        if history_end is None:
            start_plus_delta = datetime.now(timezone.utc) + timedelta(days=entity.delta)
        else:
            cycle_seconds = timedelta(days=entity.delta).total_seconds()
            cycle = max(0, int((datetime.now(timezone.utc) - history_end).total_seconds() // cycle_seconds))
            start_plus_delta = history_end + timedelta(days=entity.delta * (cycle + 1))

        while self._is_running(switch_id) and (
            run_id is None or self._is_current_run(switch_id, run_id)
        ):
            secs_left = (start_plus_delta - datetime.now(timezone.utc)).total_seconds()
            if secs_left <= 0:
                break
            await asyncio.sleep(min(secs_left, entity.interval))

        if self._is_running(switch_id) and (
            run_id is None or self._is_current_run(switch_id, run_id)
        ):
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
        try:
            await self.start_simulation(call, False, None)
        except Exception:
            _LOGGER.exception("Presence Simulation start failed")
            raise

    async def handle_service_stop(self, call: Any) -> None:
        """Service handler for stop."""
        await self.stop_simulation(call, False, None)

    async def handle_service_toggle(self, call: Any) -> None:
        """Service handler for toggle."""
        await self.toggle_simulation(call)
