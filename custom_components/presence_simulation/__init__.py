"""Component to integrate with presence_simulation."""

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from homeassistant.helpers.entity_registry import async_migrate_entries
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED

from .const import (
    DOMAIN,
    SWITCH_PLATFORM,
    UNIQUE_ID,
)
from .services import (
    PresenceSimulationServices,
)

_LOGGER = logging.getLogger(__name__)
_INTEGRATION_NAME = "Presence Simulation"


async def async_setup(hass: HomeAssistant, config: Dict[str, Any]) -> bool:
    """Set up this component using YAML."""
    if config.get(DOMAIN) is None:
        return True
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up this component using config flow."""
    _LOGGER.debug("async setup entry %s", entry.data["entities"])

    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = {}

        system_user = await _get_or_create_system_user(hass)

        hass.data[DOMAIN]["system_user"] = system_user

        services = PresenceSimulationServices(
            hass,
            lambda: hass.data[DOMAIN].get(SWITCH_PLATFORM, {}),
            lambda sid: is_running(hass, sid),
            system_user,
        )
        hass.data[DOMAIN]["services"] = services

        hass.services.async_register(DOMAIN, "start", services.handle_service_start)
        hass.services.async_register(DOMAIN, "stop", services.handle_service_stop)
        hass.services.async_register(DOMAIN, "toggle", services.handle_service_toggle)
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _launch_simulation_after_restart)

    entry.add_update_listener(update_listener)

    hass.async_create_task(hass.config_entries.async_forward_entry_setups(entry, [SWITCH_PLATFORM]))

    return True


async def _get_or_create_system_user(hass: HomeAssistant) -> Any:
    """Get or create system user for presence simulation."""
    users = await hass.auth.async_get_users()
    for user in users:
        if user.system_generated and user.name == _INTEGRATION_NAME:
            return user

    system_user = await hass.auth.async_create_system_user(
        _INTEGRATION_NAME,
        group_ids=["system-admin"]
    )
    _LOGGER.debug("Created system user for presence simulation: %s", system_user.id)
    return system_user


def is_running(hass: HomeAssistant, switch_id: str) -> bool:
    """Returns true if the simulation is running."""
    try:
        entity = hass.data[DOMAIN][SWITCH_PLATFORM][switch_id]
    except Exception as e:
        _LOGGER.error("Could not load presence simulation switch %s", switch_id)
        raise e
    return entity.is_on


async def _launch_simulation_after_restart(event: Any) -> None:
    """Launch simulation after HA restart if it was running."""
    hass = event.hass
    for switch_id in hass.data[DOMAIN][SWITCH_PLATFORM]:
        _LOGGER.debug("Launch simulation after restart : switch is %s", switch_id)
        entity = hass.data[DOMAIN][SWITCH_PLATFORM][switch_id]
        if entity.is_on:
            _LOGGER.debug("Relaunching simulation %s", switch_id)
            entity.internal_turn_off()
            await entity.turn_on_async()


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle removal of an entry."""
    try:
        await hass.config_entries.async_forward_entry_unload(entry, SWITCH_PLATFORM)
        _LOGGER.info("Successfully removed switch from the presence simulation integration")

        remaining_entries: List[ConfigEntry] = [
            e for e in hass.config_entries.async_entries(DOMAIN)
            if e.entry_id != entry.entry_id
        ]

        if not remaining_entries and DOMAIN in hass.data:
            system_user = hass.data[DOMAIN].get("system_user")
            if system_user:
                try:
                    await hass.auth.async_remove_user(system_user)
                    _LOGGER.debug("Removed system user for presence simulation: %s", system_user.id)
                except Exception as e:
                    _LOGGER.warning("Failed to remove system user: %s", e)

            hass.services.async_remove(DOMAIN, "start")
            hass.services.async_remove(DOMAIN, "stop")
            hass.services.async_remove(DOMAIN, "toggle")
            _LOGGER.debug("Removed services")

            del hass.data[DOMAIN]

    except ValueError:
        pass


async def update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Update listener after an update in the UI."""
    _LOGGER.debug("Updating listener entry id %s, %s, %s", entry.entry_id, entry.data, entry.options)

    if len(entry.options) > 0:
        switch_id = SWITCH_PLATFORM + "." + re.sub("[^0-9a-zA-Z]", "_", entry.data["switch"].lower())
        try:
            entity = hass.data[DOMAIN][SWITCH_PLATFORM][switch_id]
        except Exception as e:
            _LOGGER.debug("Switch with id %s not known", switch_id)
            return
        entity.update_config(entry)


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Migrate config entry from older versions."""
    _LOGGER.debug("Migrating from version %s", config_entry.version)

    if config_entry.version == 1:
        _LOGGER.debug("Will migrate to version 2")
        new_data = {**config_entry.data}
        new_data["switch"] = "Presence simulation"
        old_unique_id = UNIQUE_ID
        new_unique_id = "switch.presence_simulation"

        def update_unique_id(entity_entry: Any) -> Dict[str, str]:
            _LOGGER.debug("Updating unique id")
            return {"new_unique_id": entity_entry.unique_id.replace(old_unique_id, new_unique_id)}

        await async_migrate_entries(hass, config_entry.entry_id, update_unique_id)
        _LOGGER.debug("Entries migrated")

        hass.config_entries.async_update_entry(
            config_entry, data=new_data, unique_id=new_unique_id, version=2
        )

    if config_entry.version == 2:
        _LOGGER.debug("Will migrate to version 3")
        new_data = {**config_entry.data}
        new_data["unavailable_as_off"] = False
        hass.config_entries.async_update_entry(config_entry, data=new_data, version=3)

    if config_entry.version == 3:
        _LOGGER.debug("Will migrate to version 4")
        new_data = {**config_entry.data}
        new_data["brightness"] = 0
        hass.config_entries.async_update_entry(config_entry, data=new_data, version=4)

    if config_entry.version == 4:
        _LOGGER.debug("Will migrate to version 5")
        new_data = {**config_entry.data}
        new_data["labels"] = []
        hass.config_entries.async_update_entry(config_entry, data=new_data, version=5)

    return True
