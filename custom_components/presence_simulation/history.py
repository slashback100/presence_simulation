import logging
from typing import Any, Dict, List
from datetime import datetime
from homeassistant.core import HomeAssistant
from homeassistant.components.recorder.history import get_significant_states
from homeassistant.components.recorder import get_instance

_LOGGER = logging.getLogger(__name__)


class HistoryManager:
    """Handles history fetching and filtering."""

    @staticmethod
    def filter_out_undefined(
        history: Dict[str, List[Any]], filter_out_unavailable: bool
    ) -> Dict[str, List[Any]]:
        """Remove undefined, unknown, and optionally unavailable states."""
        states_to_remove = ["undefined", "unknown"]
        if filter_out_unavailable:
            states_to_remove.append("unavailable")

        filtered: Dict[str, List[Any]] = {}
        for entity_id, states in history.items():
            filtered_states = [
                state for state in states if state.state not in states_to_remove
            ]
            if filtered_states:
                filtered[entity_id] = filtered_states
                _LOGGER.debug('Filtered states for %s: removed %d states', entity_id, len(states) - len(filtered_states))

        return filtered

    @staticmethod
    def get_history(
        hass: HomeAssistant,
        start_time: datetime,
        entity_ids: List[str],
    ) -> Dict[str, List[Any]]:
        """Fetch significant states for the given entities and time range."""
        _LOGGER.debug("Getting history from %s for %s", start_time, entity_ids)
        history = get_significant_states(
            hass=hass,
            start_time=start_time,
            entity_ids=entity_ids,
            include_start_time_state=True,
            significant_changes_only=False,
        )
        _LOGGER.debug("Raw history: %s", history)
        return history

    @staticmethod
    def fetch_history_sync(
        hass: HomeAssistant,
        start_time: datetime,
        entity_ids: List[str],
    ) -> Dict[str, List[Any]]:
        """Fetch history synchronously (for use in executor)."""
        return get_instance(hass).async_add_executor_job(
            HistoryManager.get_history, hass, start_time, entity_ids
        )
