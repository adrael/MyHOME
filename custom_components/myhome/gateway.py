"""Code to handle a MyHome Gateway."""
import asyncio
from typing import Dict, List

from homeassistant.const import (
    CONF_ENTITIES,
    CONF_HOST,
    CONF_PORT,
    CONF_PASSWORD,
    CONF_NAME,
    CONF_MAC,
    CONF_FRIENDLY_NAME,
)
from homeassistant.components.light import DOMAIN as LIGHT
from homeassistant.components.switch import (
    SwitchDeviceClass,
    DOMAIN as SWITCH,
)
from homeassistant.components.button import DOMAIN as BUTTON
from homeassistant.components.cover import DOMAIN as COVER
from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    DOMAIN as BINARY_SENSOR,
)
from homeassistant.components.sensor import (
    SensorDeviceClass,
    DOMAIN as SENSOR,
)
from homeassistant.components.climate import DOMAIN as CLIMATE
from homeassistant.components.media_player import DOMAIN as MEDIA_PLAYER
from homeassistant.components.number import DOMAIN as NUMBER

from OWNd.connection import OWNSession, OWNEventSession, OWNCommandSession, OWNGateway
from OWNd.message import (
    OWNMessage,
    OWNLightingEvent,
    OWNLightingCommand,
    OWNEnergyEvent,
    OWNAutomationEvent,
    OWNDryContactEvent,
    OWNAuxEvent,
    OWNHeatingEvent,
    OWNHeatingCommand,
    OWNCENPlusEvent,
    OWNCENEvent,
    OWNGatewayEvent,
    OWNGatewayCommand,
    OWNCommand,
)

from .const import (
    CONF_PLATFORMS,
    CONF_FIRMWARE,
    CONF_SSDP_LOCATION,
    CONF_SSDP_ST,
    CONF_DEVICE_TYPE,
    CONF_MANUFACTURER,
    CONF_MANUFACTURER_URL,
    CONF_UDN,
    CONF_SHORT_PRESS,
    CONF_SHORT_RELEASE,
    CONF_LONG_PRESS,
    CONF_LONG_RELEASE,
    CONF_SOUND_SOURCES,
    CONF_TUNER_REQUESTED,
    CONF_WHERE,
    CONF_WHO,
    DOMAIN,
    LOGGER,
)
from .myhome_device import MyHOMEEntity
from .sound_diffusion import (
    AMPLIFIER_EVENTS,
    BROADCAST_EVENTS,
    SOURCE_EVENTS,
    SourceFrequency,
    SourceFrequencyStation,
    SourceStation,
    amplifier_device_id,
    parse_sound_diffusion,
)
from .button import (
    DisableCommandButtonEntity,
    EnableCommandButtonEntity,
)

#: Seconds to wait before reading the bus again after the event session raised.
#: Long enough not to spin on a gateway that is down, short enough to be back
#: within a breath of it coming up.
EVENT_SESSION_RETRY_DELAY = 1


class MyHOMEGatewayHandler:
    """Manages a single MyHOME Gateway."""

    def __init__(self, hass, config_entry, generate_events=False):
        build_info = {
            "address": config_entry.data[CONF_HOST],
            "port": config_entry.data[CONF_PORT],
            "password": config_entry.data[CONF_PASSWORD],
            "ssdp_location": config_entry.data[CONF_SSDP_LOCATION],
            "ssdp_st": config_entry.data[CONF_SSDP_ST],
            "deviceType": config_entry.data[CONF_DEVICE_TYPE],
            "friendlyName": config_entry.data[CONF_FRIENDLY_NAME],
            "manufacturer": config_entry.data[CONF_MANUFACTURER],
            "manufacturerURL": config_entry.data[CONF_MANUFACTURER_URL],
            "modelName": config_entry.data[CONF_NAME],
            "modelNumber": config_entry.data[CONF_FIRMWARE],
            "serialNumber": config_entry.data[CONF_MAC],
            "UDN": config_entry.data[CONF_UDN],
        }
        self.hass = hass
        self.config_entry = config_entry
        self.generate_events = generate_events
        self.gateway = OWNGateway(build_info)
        self._terminate_listener = False
        self._terminate_sender = False
        self.is_connected = False
        self.listening_worker: asyncio.tasks.Task = None
        self.sending_workers: List[asyncio.tasks.Task] = []
        self.send_buffer = asyncio.Queue()

    @property
    def mac(self) -> str:
        return self.gateway.serial

    @property
    def unique_id(self) -> str:
        return self.mac

    @property
    def log_id(self) -> str:
        return self.gateway.log_id

    @property
    def manufacturer(self) -> str:
        return self.gateway.manufacturer

    @property
    def name(self) -> str:
        return f"{self.gateway.model_name} Gateway"

    @property
    def model(self) -> str:
        return self.gateway.model_name

    @property
    def firmware(self) -> str:
        return self.gateway.firmware

    async def test(self) -> Dict:
        return await OWNSession(gateway=self.gateway, logger=LOGGER).test_connection()

    async def listening_loop(self):
        self._terminate_listener = False

        LOGGER.debug("%s Creating listening worker.", self.log_id)

        _event_session = OWNEventSession(gateway=self.gateway, logger=LOGGER)
        await _event_session.connect()
        self._set_connected(True)

        while not self._terminate_listener:
            try:
                message = await _event_session.get_next()
            except Exception:  # pylint: disable=broad-except
                # `get_next` answers `None` for every failure it knows about, so
                # anything raising here surprised it — the reconnection it tries
                # on an interrupted read, most likely. Nothing else reads this
                # bus: the loop has to outlive it.
                LOGGER.exception("%s Event session failed.", self.log_id)
                self._set_connected(False)
                try:
                    await _event_session.connect()
                except Exception:  # pylint: disable=broad-except
                    LOGGER.exception("%s Could not reopen the event session.", self.log_id)
                await asyncio.sleep(EVENT_SESSION_RETRY_DELAY)
                continue

            LOGGER.debug("%s Message received: `%s`", self.log_id, message)

            if self.generate_events:
                if isinstance(message, OWNMessage):
                    _event_content = {"gateway": str(self.gateway.host)}
                    _event_content.update(message.event_content)
                    self.hass.bus.async_fire("myhome_message_event", _event_content)
                else:
                    self.hass.bus.async_fire("myhome_message_event", {"gateway": str(self.gateway.host), "message": str(message)})

            if message is None:
                # `OWNEventSession.get_next` answers `None` for every failure it
                # meets, and most of them are harmless: a frame its parser
                # chokes on (a WHO=13 time write without a timezone raises an
                # IndexError in OWNd 0.7.48) or a read it already reconnected
                # after. The socket is only really gone when the reader is
                # missing — `get_next` then fails without yielding, so reopen
                # the session ourselves and pause, or this loop would starve
                # the event loop.
                if getattr(_event_session, "_stream_reader", None) is None:
                    if self.is_connected:
                        LOGGER.warning("%s Event session lost, reopening it.", self.log_id)
                    self._set_connected(False)
                    try:
                        await _event_session.connect()
                    except Exception:  # pylint: disable=broad-except
                        LOGGER.debug("%s Could not reopen the event session yet.", self.log_id)
                    await asyncio.sleep(EVENT_SESSION_RETRY_DELAY)
                else:
                    LOGGER.debug("%s Event session returned nothing for one frame, ignoring it.", self.log_id)
                continue

            if not self.is_connected:
                # A frame came through: the session is alive again.
                await self.reconnected()

            # OWNd 0.7.48 models neither WHO=22 nor WHO=16: their events reach
            # us as raw strings, and a WHO=22 dimension request as a generic
            # `OWNCommand`. Both have to be handled before the warning below.
            _raw_message = None
            if isinstance(message, str):
                _raw_message = message
            elif isinstance(message, OWNMessage) and str(getattr(message, "who", "")) in ("16", "22"):
                _raw_message = str(message)

            if _raw_message is not None:
                if _raw_message.startswith("*22*") or _raw_message.startswith("*#22*"):
                    self.handle_sound_diffusion(_raw_message)
                    continue

                if _raw_message.startswith("*16*") or _raw_message.startswith("*#16*"):
                    # Legacy WHO=16 mirror frames emitted alongside WHO=22 by
                    # sound diffusion devices; ignored.
                    LOGGER.debug(
                        "%s Ignoring legacy WHO=16 message: `%s`",
                        self.log_id,
                        _raw_message,
                    )
                    continue

            if not isinstance(message, OWNMessage):
                LOGGER.warning(
                    "%s Data received is not a message: `%s`",
                    self.log_id,
                    message,
                )
            elif isinstance(message, OWNEnergyEvent):
                if SENSOR in self.hass.data[DOMAIN][self.mac][CONF_PLATFORMS] and message.entity in self.hass.data[DOMAIN][self.mac][CONF_PLATFORMS][SENSOR]:
                    for _entity in self.hass.data[DOMAIN][self.mac][CONF_PLATFORMS][SENSOR][message.entity][CONF_ENTITIES]:
                        if isinstance(
                            self.hass.data[DOMAIN][self.mac][CONF_PLATFORMS][SENSOR][message.entity][CONF_ENTITIES][_entity],
                            MyHOMEEntity,
                        ):
                            self.hass.data[DOMAIN][self.mac][CONF_PLATFORMS][SENSOR][message.entity][CONF_ENTITIES][_entity].handle_event(message)
                else:
                    continue
            elif (
                isinstance(message, OWNLightingEvent)
                or isinstance(message, OWNAutomationEvent)
                or isinstance(message, OWNDryContactEvent)
                or isinstance(message, OWNAuxEvent)
                or isinstance(message, OWNHeatingEvent)
            ):
                if not message.is_translation:
                    is_event = False
                    if isinstance(message, OWNLightingEvent):
                        if message.is_general:
                            is_event = True
                            event = "on" if message.is_on else "off"
                            self.hass.bus.async_fire(
                                "myhome_general_light_event",
                                {"message": str(message), "event": event},
                            )
                            await asyncio.sleep(0.1)
                            await self.send_status_request(OWNLightingCommand.status("0"))
                        elif message.is_area:
                            is_event = True
                            event = "on" if message.is_on else "off"
                            self.hass.bus.async_fire(
                                "myhome_area_light_event",
                                {
                                    "message": str(message),
                                    "area": message.area,
                                    "event": event,
                                },
                            )
                            await asyncio.sleep(0.1)
                            await self.send_status_request(OWNLightingCommand.status(message.area))
                        elif message.is_group:
                            is_event = True
                            event = "on" if message.is_on else "off"
                            self.hass.bus.async_fire(
                                "myhome_group_light_event",
                                {
                                    "message": str(message),
                                    "group": message.group,
                                    "event": event,
                                },
                            )
                    elif isinstance(message, OWNAutomationEvent):
                        if message.is_general:
                            is_event = True
                            if message.is_opening and not message.is_closing:
                                event = "open"
                            elif message.is_closing and not message.is_opening:
                                event = "close"
                            else:
                                event = "stop"
                            self.hass.bus.async_fire(
                                "myhome_general_automation_event",
                                {"message": str(message), "event": event},
                            )
                        elif message.is_area:
                            is_event = True
                            if message.is_opening and not message.is_closing:
                                event = "open"
                            elif message.is_closing and not message.is_opening:
                                event = "close"
                            else:
                                event = "stop"
                            self.hass.bus.async_fire(
                                "myhome_area_automation_event",
                                {
                                    "message": str(message),
                                    "area": message.area,
                                    "event": event,
                                },
                            )
                        elif message.is_group:
                            is_event = True
                            if message.is_opening and not message.is_closing:
                                event = "open"
                            elif message.is_closing and not message.is_opening:
                                event = "close"
                            else:
                                event = "stop"
                            self.hass.bus.async_fire(
                                "myhome_group_automation_event",
                                {
                                    "message": str(message),
                                    "group": message.group,
                                    "event": event,
                                },
                            )
                    if not is_event:
                        if isinstance(message, OWNLightingEvent) and message.brightness_preset:
                            if isinstance(
                                self.hass.data[DOMAIN][self.mac][CONF_PLATFORMS][LIGHT][message.entity][CONF_ENTITIES][LIGHT],
                                MyHOMEEntity,
                            ):
                                await self.hass.data[DOMAIN][self.mac][CONF_PLATFORMS][LIGHT][message.entity][CONF_ENTITIES][LIGHT].async_update()
                        else:
                            for _platform in self.hass.data[DOMAIN][self.mac][CONF_PLATFORMS]:
                                if _platform != BUTTON and message.entity in self.hass.data[DOMAIN][self.mac][CONF_PLATFORMS][_platform]:
                                    for _entity in self.hass.data[DOMAIN][self.mac][CONF_PLATFORMS][_platform][message.entity][CONF_ENTITIES]:
                                        if (
                                            isinstance(
                                                self.hass.data[DOMAIN][self.mac][CONF_PLATFORMS][_platform][message.entity][CONF_ENTITIES][_entity],
                                                MyHOMEEntity,
                                            )
                                            and not isinstance(
                                                self.hass.data[DOMAIN][self.mac][CONF_PLATFORMS][_platform][message.entity][CONF_ENTITIES][_entity],
                                                DisableCommandButtonEntity,
                                            )
                                            and not isinstance(
                                                self.hass.data[DOMAIN][self.mac][CONF_PLATFORMS][_platform][message.entity][CONF_ENTITIES][_entity],
                                                EnableCommandButtonEntity,
                                            )
                                        ):
                                            self.hass.data[DOMAIN][self.mac][CONF_PLATFORMS][_platform][message.entity][CONF_ENTITIES][_entity].handle_event(message)

                else:
                    LOGGER.debug(
                        "%s Ignoring translation message `%s`",
                        self.log_id,
                        message,
                    )
            elif isinstance(message, OWNHeatingCommand) and message.dimension is not None and message.dimension == 14:
                where = message.where[1:] if message.where.startswith("#") else message.where
                LOGGER.debug(
                    "%s Received heating command, sending query to zone %s",
                    self.log_id,
                    where,
                )
                await self.send_status_request(OWNHeatingCommand.status(where))
            elif isinstance(message, OWNCENPlusEvent):
                event = None
                if message.is_short_pressed:
                    event = CONF_SHORT_PRESS
                elif message.is_held or message.is_still_held:
                    event = CONF_LONG_PRESS
                elif message.is_released:
                    event = CONF_LONG_RELEASE
                else:
                    event = None
                self.hass.bus.async_fire(
                    "myhome_cenplus_event",
                    {
                        "object": int(message.object),
                        "pushbutton": int(message.push_button),
                        "event": event,
                    },
                )
                LOGGER.info(
                    "%s %s",
                    self.log_id,
                    message.human_readable_log,
                )
            elif isinstance(message, OWNCENEvent):
                event = None
                if message.is_pressed:
                    event = CONF_SHORT_PRESS
                elif message.is_released_after_short_press:
                    event = CONF_SHORT_RELEASE
                elif message.is_held:
                    event = CONF_LONG_PRESS
                elif message.is_released_after_long_press:
                    event = CONF_LONG_RELEASE
                else:
                    event = None
                self.hass.bus.async_fire(
                    "myhome_cen_event",
                    {
                        "object": int(message.object),
                        "pushbutton": int(message.push_button),
                        "event": event,
                    },
                )
                LOGGER.info(
                    "%s %s",
                    self.log_id,
                    message.human_readable_log,
                )
            elif isinstance(message, OWNGatewayEvent) or isinstance(message, OWNGatewayCommand):
                LOGGER.info(
                    "%s %s",
                    self.log_id,
                    message.human_readable_log,
                )
            else:
                LOGGER.info(
                    "%s Unsupported message type: `%s`",
                    self.log_id,
                    message,
                )

        await _event_session.close()
        self._set_connected(False)

        LOGGER.debug("%s Destroying listening worker.", self.log_id)
        self.listening_worker.cancel()

    def _tuner_devices(self, platform: str):
        """Every device of `platform` that is a sound diffusion tuner.

        `validate.py` derives one per source under both `number` and `button`,
        and the `button` platform also holds the lock buttons of the lights,
        switches and covers — which have nothing to do with WHO=22.
        """
        _gateway_data = self.hass.data.get(DOMAIN, {}).get(self.mac)
        if not _gateway_data or CONF_PLATFORMS not in _gateway_data:
            return
        for _device in _gateway_data[CONF_PLATFORMS].get(platform, {}).values():
            if _device.get(CONF_WHO) == "22":
                yield _device

    def _sound_entities(self):
        """Every sound diffusion entity of this gateway that hass already knows.

        The amplifiers of the `media_player` platform and the entities of the
        tuner devices, spread over `number` and `button`. Those platforms are
        walked and no other: `available` elsewhere does not follow the
        connection, and writing those entities would change their behaviour.

        The amplifiers come first, so that the one status request a source is
        worth is claimed by an amplifier when a gateway has both.
        """
        _gateway_data = self.hass.data.get(DOMAIN, {}).get(self.mac)
        if not _gateway_data or CONF_PLATFORMS not in _gateway_data:
            return
        _devices = list(_gateway_data[CONF_PLATFORMS].get(MEDIA_PLAYER, {}).values())
        _devices += list(self._tuner_devices(NUMBER)) + list(self._tuner_devices(BUTTON))
        for _device in _devices:
            for _entity in _device[CONF_ENTITIES].values():
                # `hass` is set when the entity is added to a platform; writing
                # a state before that raises.
                if isinstance(_entity, MyHOMEEntity) and getattr(_entity, "hass", None) is not None:
                    yield _entity

    def _set_connected(self, is_connected: bool) -> None:
        """Record the connection state and refresh the sound diffusion entities.

        Their `available` is this very flag, and no other code path writes them
        when the gateway comes and goes.
        """
        if self.is_connected == is_connected:
            return

        self.is_connected = is_connected
        for _entity in self._sound_entities():
            _entity.async_write_ha_state()

    async def reconnected(self) -> None:
        """Catch up with a bus that went on living while we were not listening.

        Everything we hold about the amplifiers and the tuner dates from before
        the outage, so it is all asked for again. The tuner is guarded by a flag
        set on its first request, which has to be cleared for the amplifiers to
        ask a second time.
        """
        self._set_connected(True)

        _gateway_data = self.hass.data.get(DOMAIN, {}).get(self.mac)
        if _gateway_data is None:
            return

        for _source in _gateway_data.get(CONF_SOUND_SOURCES, {}).values():
            _source.pop(CONF_TUNER_REQUESTED, None)

        try:
            for _entity in self._sound_entities():
                await _entity.async_update()
        except Exception:  # pylint: disable=broad-except
            # Called from the listening loop, which must not die of it: the
            # amplifiers are asked again on the next reconnection either way.
            LOGGER.exception("%s Could not refresh the sound diffusion entities.", self.log_id)

    def handle_sound_diffusion(self, raw_message: str) -> None:
        """Dispatch a WHO=22 frame to the relevant media_player entities."""
        # The listener outlives both ends of a reload: the config entry may have
        # been unloaded (no gateway key left) or be halfway through its setup
        # (`async_setup_entry` creates the key before filling it). Raising here
        # would kill the loop before it gets a chance to close the session.
        _gateway_data = self.hass.data.get(DOMAIN, {}).get(self.mac)
        if not _gateway_data or CONF_PLATFORMS not in _gateway_data:
            return

        if MEDIA_PLAYER not in _gateway_data[CONF_PLATFORMS]:
            # Nothing to dispatch to: not worth parsing the frame.
            return
        _configured_amplifiers = _gateway_data[CONF_PLATFORMS][MEDIA_PLAYER]

        _event = parse_sound_diffusion(raw_message)
        if _event is None:
            LOGGER.debug(
                "%s Ignoring sound diffusion message: `%s`",
                self.log_id,
                raw_message,
            )
            return

        if isinstance(_event, AMPLIFIER_EVENTS):
            _device_id = amplifier_device_id(_event.area, _event.point)
            if _device_id not in _configured_amplifiers:
                LOGGER.debug(
                    "%s Sound diffusion event for unconfigured amplifier `%s`.",
                    self.log_id,
                    _device_id,
                )
                return
            _devices = [_configured_amplifiers[_device_id]]
        elif isinstance(_event, SOURCE_EVENTS):
            # A source is shared by several amplifiers, so its tuning is stored
            # once per gateway and read back by each of them. Repeated readings
            # change nothing worth writing a dozen entity states for.
            if not self.update_sound_source(_event):
                return
            # Handed to every amplifier: which source one listens to is the
            # configured one until a WHAT 35 command moves it, and only the
            # entity knows that. It drops the events of the other sources.
            # The tuner devices read the store too, and drop them the same way.
            _devices = list(_configured_amplifiers.values()) + list(self._tuner_devices(NUMBER))
        elif isinstance(_event, BROADCAST_EVENTS):
            # Compared as numbers: `3#1#1` belongs to area 1, not to area 11.
            _devices = [_device for _device in _configured_amplifiers.values() if int(_device[CONF_WHERE].split("#")[1]) == _event.area]
        else:
            # Parsed, and that is all it is worth: see `SOURCE_EVENTS`.
            LOGGER.debug(
                "%s Sound diffusion event carrying nothing to dispatch: `%s`",
                self.log_id,
                _event,
            )
            return

        for _device in _devices:
            for _entity in _device[CONF_ENTITIES]:
                if isinstance(_device[CONF_ENTITIES][_entity], MyHOMEEntity):
                    _device[CONF_ENTITIES][_entity].handle_event(_event)

    def refresh_sound_source(self, event) -> None:
        """Record a tuning the integration just commanded, and show it at once.

        The bus echoes a retuning about 250 ms later; recording it now is what
        makes a station change feel immediate. Since the store then already holds
        it, `update_sound_source` finds nothing new in the echo and the
        amplifiers are written once, not twice.

        Every sound diffusion entity of the gateway is handed the event — the
        amplifiers and the tuner devices — as `handle_event` alone knows which
        source its entity is listening to. The seek buttons come through here
        too, to drop a preset the scan they are about to send leaves behind.
        """
        if not self.update_sound_source(event):
            return
        for _entity in self._sound_entities():
            _entity.handle_event(event)

    def update_sound_source(self, event) -> bool:
        """Record a source's tuning; answer whether it moved.

        Read back by every amplifier listening to that source, which is why an
        unchanged reading is worth nothing to them.

        A dimension 5 landing on another frequency is **not** read as leaving
        the preset behind, though a scan does exactly that. A preset step is
        answered by a burst — dimension 5 with the new frequency, then dimension
        11 with the slot about 20 ms later — so dropping the preset on the 5 had
        every station change blink the number away and back. The preset is
        dropped where the scan is known to have happened instead: the two seek
        buttons clear it themselves before sending (`tuner.MyHOMETunerButton`).

        What is left of it: a seek pressed at a wall control is invisible to us
        until the tuner reports a slot again, and the preset shown until then is
        the one it started from. A dimension 11 or a dimension 6 puts the right
        one back — a scan downwards falling onto a preset emits one at once.
        """
        _source = self.hass.data[DOMAIN][self.mac].setdefault(CONF_SOUND_SOURCES, {}).setdefault(event.source, {})
        _before = dict(_source)

        if isinstance(event, SourceFrequencyStation):
            _source["modulation"] = event.modulation
            _source["frequency"] = event.frequency
            _source["station"] = event.station
        elif isinstance(event, SourceFrequency):
            _source["modulation"] = event.modulation
            _source["frequency"] = event.frequency
        elif isinstance(event, SourceStation):
            _source["station"] = event.station

        return _source != _before

    async def sending_loop(self, worker_id: int):
        self._terminate_sender = False

        LOGGER.debug(
            "%s Creating sending worker %s",
            self.log_id,
            worker_id,
        )

        _command_session = OWNCommandSession(gateway=self.gateway, logger=LOGGER)
        await _command_session.connect()

        while not self._terminate_sender:
            task = await self.send_buffer.get()
            LOGGER.debug(
                "%s Message `%s` was successfully unqueued by worker %s.",
                self.log_id,
                task["message"],
                worker_id,
            )
            await _command_session.send(message=task["message"], is_status_request=task["is_status_request"])
            self.send_buffer.task_done()

        await _command_session.close()

        LOGGER.debug(
            "%s Destroying sending worker %s",
            self.log_id,
            worker_id,
        )
        self.sending_workers[worker_id].cancel()

    async def close_listener(self) -> bool:
        LOGGER.info("%s Closing event listener", self.log_id)
        self._terminate_sender = True
        self._terminate_listener = True

        # Both flags are only read at the top of their loop, which is blocked on
        # `get_next()` / `send_buffer.get()`: the workers keep running until the
        # next frame or the next command wakes them. `handle_sound_diffusion`
        # therefore has to tolerate a gateway key that is gone or half built.
        return True

    async def send(self, message: OWNCommand):
        await self.send_buffer.put({"message": message, "is_status_request": False})
        LOGGER.debug(
            "%s Message `%s` was successfully queued.",
            self.log_id,
            message,
        )

    async def send_status_request(self, message: OWNCommand):
        await self.send_buffer.put({"message": message, "is_status_request": True})
        LOGGER.debug(
            "%s Message `%s` was successfully queued.",
            self.log_id,
            message,
        )
