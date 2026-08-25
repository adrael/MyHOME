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
    CONF_RADIO_STATIONS,
    CONF_SOURCE,
    CONF_SOUND_SOURCES,
    CONF_TUNER_REQUESTED,
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
    AreaCommand,
    SOURCE_EVENTS,
    SoundDiffusionEvent,
    amplifier_off,
    amplifier_on_simple,
    format_frequency,
    request_amplifier_state,
    request_amplifier_volume,
    request_source_frequency_station,
    station_name,
    station_next,
    station_previous,
    volume_down,
    volume_set,
    volume_up,
)


async def async_setup_entry(hass, config_entry, async_add_entities):
    if PLATFORM not in hass.data[DOMAIN][config_entry.data[CONF_MAC]][CONF_PLATFORMS]:
        return

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


class MyHOMEAmplifier(MyHOMEEntity, MediaPlayerEntity):
    """A single sound diffusion amplifier, addressed as `3#<area>#<point>`.

    Amplifiers share their source, so the tuning information (frequency, preset,
    station) is kept once per gateway in
    `hass.data[DOMAIN][mac][CONF_SOUND_SOURCES]` and read back by each entity.
    """

    _attr_device_class = MediaPlayerDeviceClass.SPEAKER
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
            # Left unset otherwise, so the SPEAKER device class picks the icon.
            self._attr_icon = icon

        # `where` has been normalised to `3#<area>#<point>` by validate.py
        _parts = where.split("#")
        self._area = int(_parts[1])
        self._point = int(_parts[2])
        self._source = source
        #: Source a WHAT 35 command put this amplifier on, overriding the
        #: configured one.
        self._current_source = None

        # Make sure the shared tuner store exists before any event is dispatched.
        hass.data[DOMAIN][gateway.mac].setdefault(CONF_SOUND_SOURCES, {}).setdefault(self._source, {})

        self._attr_state = None
        self._attr_volume_level = None
        self._raw_volume = None

    # ----------------------------------------------------------------- state #

    @property
    def available(self) -> bool:
        """An amplifier is only as reachable as the gateway in front of it."""
        return self._gateway_handler.is_connected

    @property
    def _is_on(self) -> bool:
        return self._attr_state == MediaPlayerState.PLAYING

    @property
    def _tuner_source(self) -> int:
        """Source this amplifier listens to, as last seen rather than as configured."""
        return self._current_source or self._source

    @property
    def _tuner(self) -> dict:
        """Tuning information of the source this amplifier listens to."""
        return self._hass.data[DOMAIN][self._gateway_handler.mac].setdefault(CONF_SOUND_SOURCES, {}).setdefault(self._tuner_source, {})

    @property
    def _radio_stations(self):
        """Station table configured on the gateway, `None` for the built-in one.

        An empty table is no table: `radio_stations:` left blank in the
        configuration file must not blank out every station name.
        """
        return self._hass.data[DOMAIN][self._gateway_handler.mac].get(CONF_RADIO_STATIONS) or None

    @property
    def _frequency(self):
        """Frequency the shared tuner is on, whatever this amplifier is doing."""
        return self._tuner.get("frequency")

    @property
    def _modulation(self) -> int:
        return self._tuner.get("modulation", MODULATION_FM)

    @property
    def _station_name(self):
        return station_name(self._frequency, self._radio_stations)

    @property
    def media_content_type(self):
        return MediaType.CHANNEL if self._is_on and self._frequency is not None else None

    @property
    def media_title(self):
        """`106.0 MHz · SUD RADIO`, or just the frequency when it is unknown.

        What is *playing* here, so `None` while the amplifier is off, however
        well tuned the source may be.
        """
        _frequency = self._frequency
        if not self._is_on or _frequency is None:
            return None
        _formatted = format_frequency(_frequency, self._modulation)
        _station = self._station_name
        return f"{_formatted} · {_station}" if _station else _formatted

    @property
    def media_channel(self):
        return self._station_name if self._is_on else None

    @property
    def extra_state_attributes(self):
        """Only the attributes that carry a value, to keep the state readable.

        The tuner is one box shared by the whole installation, so what it is
        tuned to is reported whether this amplifier is playing it or not. That
        is what makes a dashboard able to show the station while every amplifier
        is off.
        """
        _attributes = {
            "area": self._area,
            "point": self._point,
            "source_id": self._tuner_source,
        }

        _frequency = self._frequency
        if _frequency is not None:
            _attributes["frequency_mhz"] = round(_frequency / 100, 2)
            if self._modulation != MODULATION_FM:
                _attributes["modulation"] = self._modulation
            _station = self._station_name
            if _station is not None:
                _attributes["station_name"] = _station

        _preset = self._tuner.get("station")
        if _preset is not None:
            _attributes["preset"] = _preset

        if self._raw_volume is not None:
            _attributes["raw_volume"] = self._raw_volume

        return _attributes

    def _set_raw_volume(self, volume) -> None:
        """Store a volume, clamped to the 0-31 range the bus works in."""
        self._raw_volume = min(MAX_VOLUME, max(0, int(volume)))
        self._attr_volume_level = self._raw_volume / MAX_VOLUME

    async def _command(self, frame: str) -> None:
        """Send a frame to the gateway."""
        await self._gateway_handler.send(OWNCommand(frame))

    # -------------------------------------------------------------- commands #

    async def async_update(self):
        """Update the entity.

        Only used by the generic entity update service and at startup.
        """
        # Claimed before the first `await`, so the amplifiers being added to hass
        # together cannot interleave and all ask for the same tuning.
        _tuner = self._tuner
        _ask_the_tuner = not _tuner.get(CONF_TUNER_REQUESTED)
        if _ask_the_tuner:
            _tuner[CONF_TUNER_REQUESTED] = True

        await self._gateway_handler.send_status_request(OWNCommand(request_amplifier_state(self._area, self._point)))
        await self._gateway_handler.send_status_request(OWNCommand(request_amplifier_volume(self._area, self._point)))

        if _ask_the_tuner:
            await self._gateway_handler.send_status_request(OWNCommand(request_source_frequency_station(self._tuner_source)))

    async def async_turn_on(self, **kwargs):  # pylint: disable=unused-argument
        """Turn the amplifier on."""
        self._attr_state = MediaPlayerState.PLAYING
        self.async_write_ha_state()
        await self._command(amplifier_on_simple(self._area, self._point))

    async def async_turn_off(self, **kwargs):  # pylint: disable=unused-argument
        """Turn the amplifier off, spec form, verified on hardware.

        The wall control emits the same frame with an area parameter of 0; both
        turn the amplifier off, see :func:`amplifier_off_bus`.
        """
        self._attr_state = MediaPlayerState.OFF
        self.async_write_ha_state()
        await self._command(amplifier_off(self._area, self._point))

    async def async_set_volume_level(self, volume: float):
        """Set the volume, converting the 0..1 HA scale to the bus' 0..31.

        Dimension 1 is written with an absolute value, verified on hardware
        (F454, 2026-08-25): the bus echoes `*#22*3#<a>#<p>*1*<volume>##` within
        about 150 ms. The optimistic write only hides that round trip.
        """
        self._set_raw_volume(round(volume * MAX_VOLUME))
        self.async_write_ha_state()
        await self._command(volume_set(self._area, self._point, self._raw_volume))

    async def async_volume_up(self):
        """Raise the volume by one step."""
        if self._raw_volume is not None:
            self._set_raw_volume(self._raw_volume + 1)
            self.async_write_ha_state()
        await self._command(volume_up(self._area, self._point))

    async def async_volume_down(self):
        """Lower the volume by one step."""
        if self._raw_volume is not None:
            self._set_raw_volume(self._raw_volume - 1)
            self.async_write_ha_state()
        await self._command(volume_down(self._area, self._point))

    async def async_media_next_track(self):
        """Select the next station of the shared tuner, spec form.

        Addressed to the source rather than to this amplifier: the tuner is what
        moves. Verified on hardware, although OWNd builds the frame with
        `is_valid = False` — see :func:`station_next`.
        """
        await self._command(station_next(self._tuner_source))

    async def async_media_previous_track(self):
        """Select the previous station of the shared tuner. See above."""
        await self._command(station_previous(self._tuner_source))

    # ----------------------------------------------------------------- events #

    def handle_event(self, message: SoundDiffusionEvent) -> None:
        """Handle a sound diffusion event dispatched by the gateway handler.

        Source level events carry no amplifier state: the shared tuner store has
        already been updated by the gateway, so they only trigger a refresh.
        They are handed to every amplifier of the gateway, since the source one
        listens to is the configured one only until a WHAT 35 command moves it.
        """
        LOGGER.debug("%s Sound diffusion event: %s", self._gateway_handler.log_id, message)

        if isinstance(message, SOURCE_EVENTS) and message.source != self._tuner_source:
            # Verified on hardware: a request addressed to one source is answered
            # by all of them. This amplifier plays one.
            return

        if isinstance(message, AmplifierState):
            self._attr_state = MediaPlayerState.PLAYING if message.is_on else MediaPlayerState.OFF
        elif isinstance(message, AmplifierVolume):
            self._set_raw_volume(message.volume)
        elif isinstance(message, (AmplifierCommand, AreaCommand)):
            if isinstance(message, AmplifierCommand) and message.source is not None:
                # WHAT 35 turns an amplifier on *and* puts it on a source.
                self._current_source = message.source
            if message.is_on is not None:
                self._attr_state = MediaPlayerState.PLAYING if message.is_on else MediaPlayerState.OFF

        self.async_write_ha_state()
