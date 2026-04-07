import logging
from homeassistant.core import HomeAssistant, Context
from typing import Any, Optional

_LOGGER = logging.getLogger(__name__)


class EntityController:
    """Handles state updates for different entity types."""

    def __init__(self, hass: HomeAssistant, system_user_id: Optional[str]):
        self._hass = hass
        self._system_user_id = system_user_id

    def _create_context(self) -> Context:
        """Create context with system user for proper attribution."""
        return Context(user_id=self._system_user_id)

    async def update_entity(
        self,
        entity_id: str,
        state: Any,
        unavailable_as_off: bool,
        brightness: int,
        should_send_event: bool,
        event_fire_callback: Any,
        event_name: str,
    ) -> Optional[dict]:
        """Switch the entity to the given state."""
        domain = entity_id.split(".")[0]
        context = self._create_context()
        event_data = None

        if domain == "light":
            event_data = await self._handle_light(
                entity_id, state, unavailable_as_off, brightness, context
            )
        elif domain == "cover":
            event_data = await self._handle_cover(entity_id, state, unavailable_as_off, context)
        elif domain == "media_player":
            event_data = await self._handle_media_player(
                entity_id, state, unavailable_as_off, context
            )
        elif domain == "input_select":
            event_data = await self._handle_input_select(entity_id, state, context)
        else:
            event_data = await self._handle_generic(
                entity_id, state, unavailable_as_off, context
            )

        if event_data is not None and should_send_event:
            event_fire_callback(event_name, event_data)

        return event_data

    async def _handle_light(
        self,
        entity_id: str,
        state: Any,
        unavailable_as_off: bool,
        brightness: int,
        context: Context,
    ) -> Optional[dict]:
        """Handle light entity state changes."""
        _LOGGER.debug("Switching light %s to %s", entity_id, state.state)

        service_data: dict = {}

        if "brightness" in state.attributes and state.attributes["brightness"] is not None:
            _LOGGER.debug("Got attribute brightness: %s", state.attributes["brightness"])
            service_data["brightness"] = state.attributes["brightness"]

        if state.state == "on" and brightness > 0:
            service_data["brightness_pct"] = brightness

        if "color_mode" in state.attributes and state.attributes["color_mode"] is not None:
            _LOGGER.debug("Got attribute color_mode: %s", state.attributes["color_mode"])
            color_mode = state.attributes["color_mode"]
            if color_mode != "color_temp":
                color_mode = color_mode + "_color"
            else:
                color_mode = "color_temp_kelvin"
            if color_mode in state.attributes and state.attributes[color_mode] is not None:
                service_data[color_mode] = state.attributes[color_mode]

        if state.state == "on" or state.state == "off" or (
            state.state == "unavailable" and unavailable_as_off
        ):
            service = "turn_on" if state.state == "on" else "turn_off"
            _LOGGER.debug(
                "calling service %s with target %s and data %s",
                service,
                {"entity_id": entity_id},
                service_data,
            )
            await self._hass.services.async_call(
                "light",
                service,
                service_data=service_data,
                blocking=False,
                target={"entity_id": entity_id},
                context=context,
            )
            return {"entity_id": entity_id, "service": f"light.{service}", "service_data": service_data}

        _LOGGER.debug("State in neither on nor off (is %s), do nothing", state.state)
        return None

    async def _handle_cover(
        self,
        entity_id: str,
        state: Any,
        unavailable_as_off: bool,
        context: Context,
    ) -> Optional[dict]:
        """Handle cover entity state changes."""
        _LOGGER.debug("Switching Cover %s to %s", entity_id, state.state)

        service_data: dict = {}
        blocking = "current_tilt_position" in state.attributes

        if state.state == "closed" or (state.state == "unavailable" and unavailable_as_off):
            _LOGGER.debug("Closing cover %s", entity_id)
            await self._hass.services.async_call(
                "cover",
                "close_cover",
                service_data,
                blocking=blocking,
                target={"entity_id": entity_id},
                context=context,
            )
            return {"entity_id": entity_id, "service": "cover.close_cover", "service_data": service_data}

        if state.state == "open":
            if "current_position" in state.attributes:
                service_data["position"] = state.attributes["current_position"]
                _LOGGER.debug(
                    "Changing cover %s position to %s",
                    entity_id,
                    state.attributes["current_position"],
                )
                await self._hass.services.async_call(
                    "cover",
                    "set_cover_position",
                    service_data,
                    blocking=blocking,
                    target={"entity_id": entity_id},
                    context=context,
                )
                event_data = {
                    "entity_id": entity_id,
                    "service": "cover.set_cover_position",
                    "service_data": service_data.copy(),
                }
                del service_data["position"]
                if "current_tilt_position" in state.attributes:
                    service_data["tilt_position"] = state.attributes["current_tilt_position"]
                    await self._hass.services.async_call(
                        "cover",
                        "set_cover_tilt_position",
                        service_data,
                        blocking=False,
                        target={"entity_id": entity_id},
                        context=context,
                    )
                return event_data
            else:
                _LOGGER.debug("Opening cover %s", entity_id)
                await self._hass.services.async_call(
                    "cover",
                    "open_cover",
                    service_data,
                    blocking=blocking,
                    target={"entity_id": entity_id},
                    context=context,
                )
                event_data = {"entity_id": entity_id, "service": "cover.open_cover", "service_data": service_data}
                if "current_tilt_position" in state.attributes:
                    service_data["tilt_position"] = state.attributes["current_tilt_position"]
                    await self._hass.services.async_call(
                        "cover",
                        "set_cover_tilt_position",
                        service_data,
                        blocking=False,
                        target={"entity_id": entity_id},
                        context=context,
                    )
                return event_data

        if state.state in ["closed", "open"] and "current_tilt_position" in state.attributes:
            service_data["tilt_position"] = state.attributes["current_tilt_position"]
            _LOGGER.debug(
                "Changing cover %s tilt position to %s",
                entity_id,
                state.attributes["current_tilt_position"],
            )
            await self._hass.services.async_call(
                "cover",
                "set_cover_tilt_position",
                service_data,
                blocking=False,
                target={"entity_id": entity_id},
                context=context,
            )
            return {
                "entity_id": entity_id,
                "service": "cover.set_cover_tilt_position",
                "service_data": service_data,
            }

        return None

    async def _handle_media_player(
        self,
        entity_id: str,
        state: Any,
        unavailable_as_off: bool,
        context: Context,
    ) -> Optional[dict]:
        """Handle media_player entity state changes."""
        _LOGGER.debug("Switching media_player %s to %s", entity_id, state.state)
        service_data: dict = {}

        if state.state == "playing":
            await self._hass.services.async_call(
                "media_player",
                "media_play",
                service_data,
                blocking=False,
                target={"entity_id": entity_id},
                context=context,
            )
            return {"entity_id": entity_id, "service": "media_player.media_play", "service_data": service_data}

        if state.state != "unavailable" or unavailable_as_off:
            await self._hass.services.async_call(
                "media_player",
                "media_stop",
                service_data,
                blocking=False,
                target={"entity_id": entity_id},
                context=context,
            )
            return {"entity_id": entity_id, "service": "media_player.media_stop", "service_data": service_data}

        _LOGGER.debug("State in unavailable, do nothing")
        return None

    async def _handle_input_select(
        self,
        entity_id: str,
        state: Any,
        context: Context,
    ) -> Optional[dict]:
        """Handle input_select entity state changes."""
        _LOGGER.debug("Setting input select option %s to %s", entity_id, state.state)

        service_data = {"entity_id": entity_id, "option": state.state}
        await self._hass.services.async_call(
            "input_select",
            "select_option",
            service_data,
            blocking=False,
            context=context,
        )
        return {
            "entity_id": entity_id,
            "service": "input_select.select_option",
            "service_data": service_data,
        }

    async def _handle_generic(
        self,
        entity_id: str,
        state: Any,
        unavailable_as_off: bool,
        context: Context,
    ) -> Optional[dict]:
        """Handle generic on/off entities."""
        _LOGGER.debug("Switching entity %s to %s", entity_id, state.state)
        service_data: dict = {}

        if state.state == "on" or state.state == "off" or (
            state.state == "unavailable" and unavailable_as_off
        ):
            service = "turn_on" if state.state == "on" else "turn_off"
            await self._hass.services.async_call(
                "homeassistant",
                service,
                service_data,
                blocking=False,
                target={"entity_id": entity_id},
                context=context,
            )
            return {"entity_id": entity_id, "service": f"homeassistant.{service}", "service_data": service_data}

        _LOGGER.debug("State in neither on nor off (is %s), do nothing", state.state)
        return None
