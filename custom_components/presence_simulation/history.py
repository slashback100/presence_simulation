import logging
from typing import Any, Dict, List, Optional
from datetime import datetime
from homeassistant.core import HomeAssistant
from homeassistant.components.recorder.history import get_significant_states
from homeassistant.components.recorder import get_instance

_LOGGER = logging.getLogger(__name__)

# Attributes the replay actually uses to rebuild a state (see entity_controller).
# Two consecutive history rows are considered redundant when the state and all
# of these attributes are unchanged, even if other attributes (e.g. linkquality)
# differ. This removes the noise rows that caused the flicker in issue #125.
SIGNIFICANT_ATTRIBUTES = {
    "brightness",
    "color_mode",
    "color_temp",
    "color_temp_kelvin",
    "rgb_color",
    "hs_color",
    "xy_color",
    "current_position",
    "current_tilt_position",
}


class HistoryManager:
    """Handles history fetching and filtering."""

    @staticmethod
    def remove_redundant_states(
        history: Dict[str, List[Any]],
    ) -> Dict[str, List[Any]]:
        """Drop consecutive states with same state and same significant attributes."""
        filtered: Dict[str, List[Any]] = {}
        for entity_id, states in history.items():
            kept: List[Any] = []
            for state in states:
                if kept:
                    prev = kept[-1]
                    if state.state == prev.state and all(
                        state.attributes.get(attr) == prev.attributes.get(attr)
                        for attr in SIGNIFICANT_ATTRIBUTES
                    ):
                        continue
                kept.append(state)
            if kept:
                filtered[entity_id] = kept
                removed = len(states) - len(kept)
                if removed:
                    _LOGGER.debug(
                        "Removed %d redundant states for %s", removed, entity_id
                    )
        return filtered

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
        end_time: Optional[datetime] = None,
    ) -> Dict[str, List[Any]]:
        """Fetch significant states for the given entities and time range."""
        _LOGGER.debug("Getting history from %s to %s for %s", start_time, end_time, entity_ids)
        history = get_significant_states(
            hass=hass,
            start_time=start_time,
            end_time=end_time,
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
