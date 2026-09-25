"""Small, persistent history snapshots for Presence Simulation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

SNAPSHOT_VERSION = 1


@dataclass(slots=True)
class SnapshotState:
    """Minimal State-compatible object used while replaying a snapshot."""

    state: str
    attributes: dict[str, Any]
    last_updated: datetime

    def as_dict(self) -> dict[str, Any]:
        """Provide the small State interface used by the replay logger."""
        return {
            "state": self.state,
            "attributes": self.attributes,
            "last_updated": self.last_updated.isoformat(),
        }


class SnapshotStore:
    """Persist only the relevant state changes, not the complete recorder history."""

    def __init__(self, hass: HomeAssistant, switch_id: str) -> None:
        safe_id = switch_id.replace(".", "_")
        self._store = Store(hass, SNAPSHOT_VERSION, f"{safe_id}_presence_snapshot")

    async def load(self) -> dict[str, Any] | None:
        data = await self._store.async_load()
        if not isinstance(data, dict) or data.get("version") != SNAPSHOT_VERSION:
            return None
        return data

    async def save(
        self,
        history: dict[str, list[Any]],
        history_start: datetime,
        history_end: datetime,
        entities: list[str],
    ) -> dict[str, Any]:
        events: dict[str, list[dict[str, Any]]] = {}
        for entity_id, states in history.items():
            serialized: list[dict[str, Any]] = []
            for state in states:
                last_updated = getattr(state, "last_updated", None)
                if last_updated is None:
                    continue
                serialized.append(
                    {
                        "state": state.state,
                        "attributes": dict(state.attributes),
                        "last_updated": last_updated.isoformat(),
                    }
                )
            if serialized:
                events[entity_id] = serialized

        data = {
            "version": SNAPSHOT_VERSION,
            "captured_at": datetime.now(history_end.tzinfo).isoformat(),
            "history_start": history_start.isoformat(),
            "history_end": history_end.isoformat(),
            "entities": entities,
            "events": events,
            "event_count": sum(len(items) for items in events.values()),
        }
        await self._store.async_save(data)
        return data

    @staticmethod
    def deserialize(data: dict[str, Any]) -> dict[str, list[SnapshotState]]:
        history: dict[str, list[SnapshotState]] = {}
        for entity_id, events in data.get("events", {}).items():
            restored: list[SnapshotState] = []
            for event in events:
                try:
                    restored.append(
                        SnapshotState(
                            state=str(event["state"]),
                            attributes=dict(event.get("attributes", {})),
                            last_updated=datetime.fromisoformat(event["last_updated"]),
                        )
                    )
                except (KeyError, TypeError, ValueError):
                    continue
            if restored:
                history[entity_id] = restored
        return history
