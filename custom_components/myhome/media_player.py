"""Support for MyHome sound diffusion amplifiers (WHO=22)."""
from homeassistant.components.media_player import (
    DOMAIN as PLATFORM,
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
)

from homeassistant.const import (
    CONF_NAME,
    CONF_MAC,
)

from OWNd.message import OWNCommand

from .const import (
    CONF_PLATFORMS,
    CONF_ENTITY,
    CONF_ENTITY_NAME,
    CONF_ICON,
    CONF_SOURCE,
    CONF_SOUND_SOURCES,
    CONF_WHO,
    CONF_WHERE,
    CONF_MANUFACTURER,
    CONF_DEVICE_MODEL,
    DOMAIN,
    LOGGER,
)
from .myhome_device import MyHOMEEntity
from .gateway import MyHOMEGatewayHandler
from .sound_diffusion import (
    MAX_VOLUME,
    MODULATION_FM,
    AmplifierCommand,
    AmplifierState,
    AmplifierVolume,
    amplifier_off_bus,
    amplifier_on_simple,
    format_frequency,
    request_amplifier_state,
    request_amplifier_volume,
    request_source_frequency_station,
    station_name,
    station_next_from_amplifier,
    station_previous_from_amplifier,
    volume_down,
    volume_set,
    volume_up,
)


async def async_setup_entry(hass, config_entry, async_add_entities):
    if PLATFORM not in hass.data[DOMAIN][config_entry.data[CONF_MAC]][CONF_PLATFORMS]:
        return True

    _amplifiers = []
    _configured_amplifiers = hass.data[DOMAIN][config_entry.data[CONF_MAC]][CONF_PLATFORMS][PLATFORM]

    for _amplifier in _configured_amplifiers.keys():
        _amplifier = MyHOMEAmplifier(
            hass=hass,
            device_id=_amplifier,
            who=_configured_amplifiers[_amplifier][CONF_WHO],
            where=_configured_amplifiers[_amplifier][CONF_WHERE],
            icon=_configured_amplifiers[_amplifier][CONF_ICON],
            name=_configured_amplifiers[_amplifier][CONF_NAME],
            entity_name=_configured_amplifiers[_amplifier][CONF_ENTITY_NAME],
            source=_configured_amplifiers[_amplifier][CONF_SOURCE],
            manufacturer=_configured_amplifiers[_amplifier][CONF_MANUFACTURER],
            model=_configured_amplifiers[_amplifier][CONF_DEVICE_MODEL],
            gateway=hass.data[DOMAIN][config_entry.data[CONF_MAC]][CONF_ENTITY],
        )
        _amplifiers.append(_amplifier)

    async_add_entities(_amplifiers)


async def async_unload_entry(hass, config_entry):  # pylint: disable=unused-argument
    if PLATFORM not in hass.data[DOMAIN][config_entry.data[CONF_MAC]][CONF_PLATFORMS]:
        return True

    _configured_amplifiers = hass.data[DOMAIN][config_entry.data[CONF_MAC]][CONF_PLATFORMS][PLATFORM]

    # `list()` because the loop deletes from the very dict it iterates over.
    for _amplifier in list(_configured_amplifiers.keys()):
        del hass.data[DOMAIN][config_entry.data[CONF_MAC]][CONF_PLATFORMS][PLATFORM][_amplifier]


class MyHOMEAmplifier(MyHOMEEntity, MediaPlayerEntity):
    """A single sound diffusion amplifier, addressed as `3#<area>#<point>`.

    Every amplifier of the installation shares the same tuner, so the tuning
    information (frequency, preset, station) is kept once per gateway in
    `hass.data[DOMAIN][mac][CONF_SOUND_SOURCES]` and read back by each entity.
    """

    _attr_device_class = MediaPlayerDeviceClass.SPEAKER
    _attr_media_content_type = MediaType.CHANNEL
    _attr_supported_features = (
        MediaPlayerEntityFeature.TURN_ON
        | MediaPlayerEntityFeature.TURN_OFF
        | MediaPlayerEntityFeature.VOLUME_SET
        | MediaPlayerEntityFeature.VOLUME_STEP
        | MediaPlayerEntityFeature.NEXT_TRACK
        | MediaPlayerEntityFeature.PREVIOUS_TRACK
    )

    def __init__(
        self,
        hass,
        name: str,
        entity_name: str,
        icon: str,
        device_id: str,
        who: str,
        where: str,
        source: int,
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

        self._attr_name = entity_name
        if icon is not None:
            self._attr_icon = icon

        # `where` has been normalised to `3#<area>#<point>` by validate.py
        _parts = where.split("#")
        self._area = int(_parts[1])
        self._point = int(_parts[2])
        self._source = source

        # Make sure the shared tuner store exists before any event is dispatched.
        hass.data[DOMAIN][gateway.mac].setdefault(CONF_SOUND_SOURCES, {}).setdefault(self._source, {})

        self._attr_state = None
        self._attr_volume_level = None
        self._raw_volume = None
        self._mmtype = None

    @property
    def _tuner(self) -> dict:
        """Tuning information of the source this amplifier listens to."""
        return self._hass.data[DOMAIN][self._gateway_handler.mac].setdefault(CONF_SOUND_SOURCES, {}).setdefault(self._source, {})

    @property
    def media_title(self):
        """`106.0 MHz · SUD RADIO`, or just the frequency when unknown."""
        _frequency = self._tuner.get("frequency")
        if _frequency is None:
            return None
        _formatted = format_frequency(_frequency, self._tuner.get("modulation", MODULATION_FM))
        _station = station_name(_frequency)
        return f"{_formatted} · {_station}" if _station else _formatted

    @property
    def media_channel(self):
        return station_name(self._tuner.get("frequency"))

    @property
    def extra_state_attributes(self):
        _frequency = self._tuner.get("frequency")
        return {
            "area": self._area,
            "point": self._point,
            "frequency_mhz": round(_frequency / 100, 2) if _frequency is not None else None,
            "station_name": station_name(_frequency),
            "preset": self._tuner.get("station"),
            "modulation": self._tuner.get("modulation"),
            "source_id": self._source,
            "raw_volume": self._raw_volume,
        }

    async def async_update(self):
        """Update the entity.

        Only used by the generic entity update service.
        """
        await self._gateway_handler.send_status_request(OWNCommand(request_amplifier_state(self._area, self._point)))
        await self._gateway_handler.send_status_request(OWNCommand(request_amplifier_volume(self._area, self._point)))
        await self._gateway_handler.send_status_request(OWNCommand(request_source_frequency_station(self._source)))

    async def async_turn_on(self, **kwargs):  # pylint: disable=unused-argument
        """Turn the amplifier on."""
        await self._gateway_handler.send(OWNCommand(amplifier_on_simple(self._area, self._point)))

    async def async_turn_off(self, **kwargs):  # pylint: disable=unused-argument
        """Turn the amplifier off."""
        await self._gateway_handler.send(OWNCommand(amplifier_off_bus(self._area, self._point)))

    async def async_set_volume_level(self, volume: float):
        """Set the volume, converting the 0..1 HA scale to the bus' 0..31."""
        await self._gateway_handler.send(OWNCommand(volume_set(self._area, self._point, round(volume * MAX_VOLUME))))

    async def async_volume_up(self):
        """Raise the volume by one step."""
        await self._gateway_handler.send(OWNCommand(volume_up(self._area, self._point)))

    async def async_volume_down(self):
        """Lower the volume by one step."""
        await self._gateway_handler.send(OWNCommand(volume_down(self._area, self._point)))

    async def async_media_next_track(self):
        """Select the next station of the shared tuner."""
        await self._gateway_handler.send(OWNCommand(station_next_from_amplifier(self._area, self._point)))

    async def async_media_previous_track(self):
        """Select the previous station of the shared tuner."""
        await self._gateway_handler.send(OWNCommand(station_previous_from_amplifier(self._area, self._point)))

    def handle_event(self, message):
        """Handle a sound diffusion event dispatched by the gateway handler.

        Source level events carry no amplifier state: the shared tuner store has
        already been updated by the gateway, so they only trigger a refresh.
        """
        LOGGER.info("%s Sound diffusion event: %s", self._gateway_handler.log_id, message)

        if isinstance(message, AmplifierState):
            self._attr_state = MediaPlayerState.ON if message.is_on else MediaPlayerState.OFF
            self._mmtype = message.mmtype
        elif isinstance(message, AmplifierVolume):
            self._raw_volume = message.volume
            self._attr_volume_level = message.volume / MAX_VOLUME
        elif isinstance(message, AmplifierCommand):
            if message.is_on is not None:
                self._attr_state = MediaPlayerState.ON if message.is_on else MediaPlayerState.OFF

        self.async_schedule_update_ha_state()
