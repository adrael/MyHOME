"""Support for MyHome binary sensors (dry contacts and motion sensors)."""
from datetime import datetime, timedelta, timezone
from homeassistant.components.binary_sensor import (
    DOMAIN as PLATFORM,
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import (
    CONF_NAME,
    CONF_MAC,
    CONF_ENTITIES,
    STATE_ON,
)
from homeassistant.core import callback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.event import async_call_later

from OWNd.message import (
    OWNDryContactEvent,
    OWNDryContactCommand,
    OWNLightingCommand,
    MESSAGE_TYPE_MOTION,
    MESSAGE_TYPE_PIR_SENSITIVITY,
    MESSAGE_TYPE_MOTION_TIMEOUT,
    OWNLightingEvent,
)

from .const import (
    CONF_PLATFORMS,
    CONF_ENTITY,
    CONF_ENTITY_NAME,
    CONF_WHO,
    CONF_WHERE,
    CONF_MANUFACTURER,
    CONF_DEVICE_MODEL,
    CONF_DEVICE_CLASS,
    CONF_INVERTED,
    CONF_CALL_TIMEOUT,
    DOMAIN,
    LOGGER,
)
from .myhome_device import MyHOMEEntity
from .gateway import MyHOMEGatewayHandler
from .video_door_entry import RING_EVENTS, SESSION_END_EVENTS

SCAN_INTERVAL = timedelta(seconds=5)
PIR_SENSITIVITY = ["low", "medium", "high", "very high"]


async def async_setup_entry(hass, config_entry, async_add_entities):
    if PLATFORM not in hass.data[DOMAIN][config_entry.data[CONF_MAC]][CONF_PLATFORMS]:
        return True

    _binary_sensors = []
    _configured_binary_sensors = hass.data[DOMAIN][config_entry.data[CONF_MAC]][CONF_PLATFORMS][PLATFORM]

    for _binary_sensor in _configured_binary_sensors.keys():
        _who = int(_configured_binary_sensors[_binary_sensor][CONF_WHO])
        _device_class = _configured_binary_sensors[_binary_sensor][CONF_DEVICE_CLASS]
        if _who == 25:
            _binary_sensor = MyHOMEDryContact(
                hass=hass,
                device_id=_binary_sensor,
                who=_configured_binary_sensors[_binary_sensor][CONF_WHO],
                where=_configured_binary_sensors[_binary_sensor][CONF_WHERE],
                name=_configured_binary_sensors[_binary_sensor][CONF_NAME],
                entity_name=_configured_binary_sensors[_binary_sensor][CONF_ENTITY_NAME],
                inverted=_configured_binary_sensors[_binary_sensor][CONF_INVERTED],
                device_class=_device_class,
                manufacturer=_configured_binary_sensors[_binary_sensor][CONF_MANUFACTURER],
                model=_configured_binary_sensors[_binary_sensor][CONF_DEVICE_MODEL],
                gateway=hass.data[DOMAIN][config_entry.data[CONF_MAC]][CONF_ENTITY],
            )
            _binary_sensors.append(_binary_sensor)
        elif _who == 9:
            _binary_sensor = MyHOMEAuxiliary(
                hass=hass,
                device_id=_binary_sensor,
                who=_configured_binary_sensors[_binary_sensor][CONF_WHO],
                where=_configured_binary_sensors[_binary_sensor][CONF_WHERE],
                name=_configured_binary_sensors[_binary_sensor][CONF_NAME],
                entity_name=_configured_binary_sensors[_binary_sensor][CONF_ENTITY_NAME],
                inverted=_configured_binary_sensors[_binary_sensor][CONF_INVERTED],
                device_class=_device_class,
                manufacturer=_configured_binary_sensors[_binary_sensor][CONF_MANUFACTURER],
                model=_configured_binary_sensors[_binary_sensor][CONF_DEVICE_MODEL],
                gateway=hass.data[DOMAIN][config_entry.data[CONF_MAC]][CONF_ENTITY],
            )
            _binary_sensors.append(_binary_sensor)
        elif _who == 8:
            _binary_sensor = MyHOMEVideoDoorEntryCall(
                hass=hass,
                device_id=_binary_sensor,
                who=_configured_binary_sensors[_binary_sensor][CONF_WHO],
                where=_configured_binary_sensors[_binary_sensor][CONF_WHERE],
                name=_configured_binary_sensors[_binary_sensor][CONF_NAME],
                entity_name=_configured_binary_sensors[_binary_sensor][CONF_ENTITY_NAME],
                call_timeout=_configured_binary_sensors[_binary_sensor][CONF_CALL_TIMEOUT],
                manufacturer=_configured_binary_sensors[_binary_sensor][CONF_MANUFACTURER],
                model=_configured_binary_sensors[_binary_sensor][CONF_DEVICE_MODEL],
                gateway=hass.data[DOMAIN][config_entry.data[CONF_MAC]][CONF_ENTITY],
            )
            _binary_sensors.append(_binary_sensor)
        elif _who == 1 and _device_class == BinarySensorDeviceClass.MOTION:
            _binary_sensor = MyHOMEMotionSensor(
                hass=hass,
                device_id=_binary_sensor,
                who=_configured_binary_sensors[_binary_sensor][CONF_WHO],
                where=_configured_binary_sensors[_binary_sensor][CONF_WHERE],
                name=_configured_binary_sensors[_binary_sensor][CONF_NAME],
                entity_name=_configured_binary_sensors[_binary_sensor][CONF_ENTITY_NAME],
                inverted=_configured_binary_sensors[_binary_sensor][CONF_INVERTED],
                device_class=_device_class,
                manufacturer=_configured_binary_sensors[_binary_sensor][CONF_MANUFACTURER],
                model=_configured_binary_sensors[_binary_sensor][CONF_DEVICE_MODEL],
                gateway=hass.data[DOMAIN][config_entry.data[CONF_MAC]][CONF_ENTITY],
            )
            _binary_sensors.append(_binary_sensor)

    async_add_entities(_binary_sensors)


async def async_unload_entry(hass, config_entry):
    if PLATFORM not in hass.data[DOMAIN][config_entry.data[CONF_MAC]][CONF_PLATFORMS]:
        return True

    _configured_binary_sensors = hass.data[DOMAIN][config_entry.data[CONF_MAC]][CONF_PLATFORMS][PLATFORM]

    # Iterated over a copy: deleting out of the dict being walked raises on the
    # second key. Aligned with button/event/camera, which all iterate a list.
    for _binary_sensor in list(_configured_binary_sensors):
        del hass.data[DOMAIN][config_entry.data[CONF_MAC]][CONF_PLATFORMS][PLATFORM][_binary_sensor]

    return True


class MyHOMEDryContact(MyHOMEEntity, BinarySensorEntity):
    def __init__(
        self,
        hass,
        name: str,
        entity_name: str,
        device_id: str,
        who: str,
        where: str,
        inverted: bool,
        device_class: str,
        manufacturer: str,
        model: str,
        gateway: MyHOMEGatewayHandler,
    ):
        super().__init__(
            hass=hass,
            name=name,
            platform=PLATFORM,
            device_id=device_id,
            who=who,
            where=where,
            manufacturer=manufacturer,
            model=model,
            gateway=gateway,
        )

        self._inverted = inverted

        self._attr_device_class = device_class
        self._attr_name = entity_name if entity_name else self._attr_device_class.replace("_", " ").capitalize()

        self._attr_unique_id = f"{gateway.mac}-{self._device_id}-{self._attr_device_class}"

        self._attr_is_on = False
        self._attr_extra_state_attributes = {"Sensor": f"({self._where[0]}){self._where[1:]}"}

    async def async_added_to_hass(self):
        """When entity is added to hass."""
        self._hass.data[DOMAIN][self._gateway_handler.mac][CONF_PLATFORMS][self._platform][self._device_id][CONF_ENTITIES][self._attr_device_class] = self
        await self.async_update()

    async def async_will_remove_from_hass(self):
        """When entity is removed from hass."""
        if self._attr_device_class in self._hass.data[DOMAIN][self._gateway_handler.mac][CONF_PLATFORMS][self._platform][self._device_id][CONF_ENTITIES]:
            del self._hass.data[DOMAIN][self._gateway_handler.mac][CONF_PLATFORMS][self._platform][self._device_id][CONF_ENTITIES][self._attr_device_class]

    async def async_update(self):
        """Update the entity.

        Only used by the generic entity update service.
        """
        await self._gateway_handler.send_status_request(OWNDryContactCommand.status(self._where))

    def handle_event(self, message: OWNDryContactEvent):
        """Handle an event message."""
        LOGGER.info(
            "%s %s",
            self._gateway_handler.log_id,
            message.human_readable_log,
        )
        self._attr_is_on = message.is_on != self._inverted
        self.async_schedule_update_ha_state()


class MyHOMEAuxiliary(MyHOMEEntity, BinarySensorEntity):
    def __init__(
        self,
        hass,
        name: str,
        entity_name: str,
        device_id: str,
        who: str,
        where: str,
        inverted: bool,
        device_class: str,
        manufacturer: str,
        model: str,
        gateway: MyHOMEGatewayHandler,
    ):
        super().__init__(
            hass=hass,
            name=name,
            platform=PLATFORM,
            device_id=device_id,
            who=who,
            where=where,
            manufacturer=manufacturer,
            model=model,
            gateway=gateway,
        )

        self._inverted = inverted

        self._attr_device_class = device_class
        self._attr_name = entity_name if entity_name else self._attr_device_class.replace("_", " ").capitalize()

        self._attr_unique_id = f"{gateway.mac}-{self._device_id}-{self._attr_device_class}"

        self._attr_is_on = False
        self._attr_extra_state_attributes = {"Auxiliary channel": self._where}

    async def async_added_to_hass(self):
        """When entity is added to hass."""
        self._hass.data[DOMAIN][self._gateway_handler.mac][CONF_PLATFORMS][self._platform][self._device_id][CONF_ENTITIES][self._attr_device_class] = self
        await self.async_update()

    async def async_will_remove_from_hass(self):
        """When entity is removed from hass."""
        if self._attr_device_class in self._hass.data[DOMAIN][self._gateway_handler.mac][CONF_PLATFORMS][self._platform][self._device_id][CONF_ENTITIES]:
            del self._hass.data[DOMAIN][self._gateway_handler.mac][CONF_PLATFORMS][self._platform][self._device_id][CONF_ENTITIES][self._attr_device_class]

    async def async_update(self):
        """AUX sensors are read only and cannot be queried, no async_update implementation."""

    def handle_event(self, message: OWNDryContactEvent):
        """Handle an event message."""
        LOGGER.info(
            "%s %s",
            self._gateway_handler.log_id,
            message.human_readable_log,
        )
        self._attr_is_on = message.is_on != self._inverted
        self.async_schedule_update_ha_state()


class MyHOMEMotionSensor(MyHOMEEntity, BinarySensorEntity, RestoreEntity):
    def __init__(
        self,
        hass,
        name: str,
        entity_name: str,
        device_id: str,
        who: str,
        where: str,
        inverted: bool,
        device_class: str,
        manufacturer: str,
        model: str,
        gateway: MyHOMEGatewayHandler,
    ):
        super().__init__(
            hass=hass,
            name=name,
            platform=PLATFORM,
            device_id=device_id,
            who=who,
            where=where,
            manufacturer=manufacturer,
            model=model,
            gateway=gateway,
        )

        self._inverted = inverted
        self._attr_force_update = False
        self._last_updated = None
        self._timeout = timedelta(seconds=315)

        self._attr_device_class = device_class
        self._attr_name = entity_name if entity_name else self._attr_device_class.replace("_", " ").capitalize()

        self._attr_unique_id = f"{gateway.mac}-{self._device_id}-{self._attr_device_class}"
        self._attr_should_poll = True
        self._attr_is_on = None
        self._attr_extra_state_attributes = {
            "A": where[: len(where) // 2],
            "PL": where[len(where) // 2 :],
            "Timeout": self._timeout.total_seconds(),
            "Sensitivity": PIR_SENSITIVITY[1],
        }

    async def async_added_to_hass(self):
        """When entity is added to hass."""
        self._hass.data[DOMAIN][self._gateway_handler.mac][CONF_PLATFORMS][self._platform][self._device_id][CONF_ENTITIES][self._attr_device_class] = self
        await self._gateway_handler.send_status_request(OWNLightingCommand.get_pir_sensitivity(self._where))
        await self._gateway_handler.send_status_request(OWNLightingCommand.get_motion_timeout(self._where))
        state = await self.async_get_last_state()
        if state:
            self._attr_is_on = state.state == STATE_ON
            self._last_updated = state.last_updated
        await self.async_update()

    async def async_will_remove_from_hass(self):
        """When entity is removed from hass."""
        if self._attr_device_class in self._hass.data[DOMAIN][self._gateway_handler.mac][CONF_PLATFORMS][self._platform][self._device_id][CONF_ENTITIES]:
            del self._hass.data[DOMAIN][self._gateway_handler.mac][CONF_PLATFORMS][self._platform][self._device_id][CONF_ENTITIES][self._attr_device_class]

    async def async_update(self):
        """Update the entity.

        Only used by the generic entity update service.
        """
        if self._attr_is_on and self._last_updated and self._last_updated + self._timeout < datetime.now(timezone.utc):
            self._attr_is_on = False
            self._last_updated = datetime.now(timezone.utc)
            self.async_schedule_update_ha_state()

    def handle_event(self, message: OWNLightingEvent):
        """Handle an event message."""
        if message.message_type not in [
            MESSAGE_TYPE_MOTION,
            MESSAGE_TYPE_MOTION_TIMEOUT,
            MESSAGE_TYPE_PIR_SENSITIVITY,
        ]:
            return True

        LOGGER.info(
            "%s %s",
            self._gateway_handler.log_id,
            message.human_readable_log,
        )
        if message.message_type == MESSAGE_TYPE_MOTION and message.motion:
            self._attr_is_on = message.motion != self._inverted
        elif message.message_type == MESSAGE_TYPE_MOTION_TIMEOUT:
            self._timeout = message.motion_timeout + timedelta(seconds=15)
            self._attr_extra_state_attributes["Timeout"] = self._timeout.total_seconds()
        elif message.message_type == MESSAGE_TYPE_PIR_SENSITIVITY:
            self._attr_extra_state_attributes["Sensitivity"] = PIR_SENSITIVITY[message.pir_sensitivity]
        self._last_updated = datetime.now(timezone.utc)
        self._attr_force_update = True
        self.async_write_ha_state()
        self._attr_force_update = False


class MyHOMEVideoDoorEntryCall(MyHOMEEntity, BinarySensorEntity):
    """"Call in progress" for one entrance panel (WHO=8).

    On when the bell rings, off when the bus reports the session ended. The end
    is not guaranteed to arrive, so a safety timeout (the `call_timeout` option,
    60 s by default) takes it off if nothing else does. `RUNNING` is the closest
    device class: a call is a thing that is either running or not.

    `available` is deliberately **not** overridden to follow the gateway
    connection: only the gateway refreshes that flag, and it does not walk the
    video-door-entry entities, so an override would freeze on its first value.
    """

    _attr_device_class = BinarySensorDeviceClass.RUNNING
    _attr_icon = "mdi:phone-in-talk"

    def __init__(
        self,
        hass,
        name: str,
        entity_name: str,
        device_id: str,
        who: str,
        where: str,
        call_timeout: int,
        manufacturer: str,
        model: str,
        gateway: MyHOMEGatewayHandler,
    ):
        super().__init__(
            hass=hass,
            name=name,
            platform=PLATFORM,
            device_id=device_id,
            who=who,
            where=where,
            manufacturer=manufacturer,
            model=model,
            gateway=gateway,
        )
        self._attr_name = entity_name if entity_name else "Call in progress"
        self._attr_unique_id = f"{gateway.mac}-{self._device_id}-call"
        self._timeout = call_timeout
        self._cancel_timeout = None
        self._attr_is_on = False

    async def async_added_to_hass(self):
        """When entity is added to hass."""
        self._hass.data[DOMAIN][self._gateway_handler.mac][CONF_PLATFORMS][self._platform][self._device_id][CONF_ENTITIES]["call"] = self

    async def async_will_remove_from_hass(self):
        """When entity is removed from hass."""
        self._clear_timeout()
        _entities = self._hass.data[DOMAIN][self._gateway_handler.mac][CONF_PLATFORMS][self._platform][self._device_id][CONF_ENTITIES]
        if "call" in _entities:
            del _entities["call"]

    async def async_update(self):
        """The panel cannot be polled: the state is pushed by the gateway."""

    def _clear_timeout(self) -> None:
        if self._cancel_timeout is not None:
            self._cancel_timeout()
            self._cancel_timeout = None

    @callback
    def _call_timed_out(self, _now) -> None:
        """Safety net: no end frame arrived, so drop the call after the timeout.

        `async_call_later` hands the callback the current time; the argument is
        taken and ignored. `@callback` keeps it on the event loop — a bare sync
        target is run in an executor thread, where `async_write_ha_state` is
        illegal.
        """
        self._cancel_timeout = None
        if self._attr_is_on:
            self._attr_is_on = False
            self.async_write_ha_state()

    def handle_event(self, message) -> None:
        """On on a ring, off on the session end; the timeout guards the gap."""
        if isinstance(message, RING_EVENTS):
            LOGGER.info("%s Call started: %s", self._gateway_handler.log_id, message)
            # A re-ring while already on restarts the timeout rather than stacking.
            self._clear_timeout()
            self._cancel_timeout = async_call_later(self._hass, self._timeout, self._call_timed_out)
            self._attr_is_on = True
            self.async_write_ha_state()
        elif isinstance(message, SESSION_END_EVENTS):
            # Only a call end (`*8*3#1#…`, kind 1) takes the sensor off. A view
            # end (`*8*3#5#…`, kind 5) is the close of an auto-on — someone
            # watched the camera — and would otherwise drop a call that is still
            # in progress. The safety timeout still guards a call end that never
            # arrives.
            if message.kind != 1:
                return
            LOGGER.info("%s Call ended: %s", self._gateway_handler.log_id, message)
            self._clear_timeout()
            self._attr_is_on = False
            self.async_write_ha_state()
