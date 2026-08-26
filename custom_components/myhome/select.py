"""Support for MyHome sound diffusion tuners (WHO=22), as a station dropdown.

One entity per source, `select.tuner_fm_station`: the stations of the gateway's
table, on the tuner device rather than on a speaker. Picking one here and
picking one from an amplifier's Source menu are the same code path
(`tuner.TunerState.select_station`) and the same scratch preset.

The dropdown belongs to the tuner because that is what moves: an installation
whose amplifiers all listen to one source has ten Source menus doing the same
thing, and one Station select saying so.
"""

from homeassistant.components.select import (
    DOMAIN as PLATFORM,
    SelectEntity,
)

from homeassistant.const import (
    CONF_NAME,
    CONF_MAC,
)

from .const import (
    CONF_ENTITY,
    CONF_PLATFORMS,
    CONF_SOURCE,
    CONF_TUNER_REQUESTED,
    CONF_WHO,
    CONF_WHERE,
    CONF_MANUFACTURER,
    CONF_DEVICE_MODEL,
    DOMAIN,
    LOGGER,
)
from .sound_diffusion import (
    MODULATION_FM,
    SOURCE_EVENTS,
)
from .tuner import MyHOMETunerEntity, request_tuning


async def async_setup_entry(hass, config_entry, async_add_entities):
    if PLATFORM not in hass.data[DOMAIN][config_entry.data[CONF_MAC]][CONF_PLATFORMS]:
        return

    _tuners = []
    _configured_tuners = hass.data[DOMAIN][config_entry.data[CONF_MAC]][CONF_PLATFORMS][PLATFORM]

    for _device_id, _device in _configured_tuners.items():
        _tuners.append(
            MyHOMETunerStation(
                hass=hass,
                device_id=_device_id,
                who=_device[CONF_WHO],
                where=_device[CONF_WHERE],
                name=_device[CONF_NAME],
                source=_device[CONF_SOURCE],
                manufacturer=_device[CONF_MANUFACTURER],
                model=_device[CONF_DEVICE_MODEL],
                gateway=hass.data[DOMAIN][config_entry.data[CONF_MAC]][CONF_ENTITY],
            )
        )

    async_add_entities(_tuners)


async def async_unload_entry(hass, config_entry):
    """Forget the tuner devices of this gateway.

    Home Assistant never calls this, exactly as in `number.py`: unloading a
    config entry resets the entity platform, which removes the entities one by
    one through `async_will_remove_from_hass`. Kept because every platform of
    this integration carries the same hook.
    """
    if PLATFORM not in hass.data[DOMAIN][config_entry.data[CONF_MAC]][CONF_PLATFORMS]:
        return True

    # Iterated over a copy: the loop is deleting out of the dict it walks.
    for _device_id in list(hass.data[DOMAIN][config_entry.data[CONF_MAC]][CONF_PLATFORMS][PLATFORM]):
        del hass.data[DOMAIN][config_entry.data[CONF_MAC]][CONF_PLATFORMS][PLATFORM][_device_id]

    return True


class MyHOMETunerStation(MyHOMETunerEntity, SelectEntity):
    """The station one tuner is on, picked from the gateway's table.

    The options are the labels of the table, the same list every amplifier of
    that source offers as its `source_list`. The current option is the station
    the tuner reports being on, matched to the table within 0.05 MHz, and
    `None` when the frequency is one the table does not carry — a tuner between
    two stations has nothing to select, and says so rather than lying.
    """

    _attr_icon = "mdi:playlist-music"

    def __init__(self, hass, **kwargs):
        super().__init__(
            hass=hass,
            entity_key="station",
            entity_name="Station",
            platform=PLATFORM,
            **kwargs,
        )

    # ----------------------------------------------------------------- state #

    @property
    def options(self) -> list:
        return self._tuner_state.station_options

    @property
    def current_option(self):
        return self._tuner_state.selected_station

    @property
    def extra_state_attributes(self):
        """What the tuner is on, for a dashboard that shows the box itself.

        Only the attributes that carry a value, like the amplifiers: a gateway
        whose tuner never answered has nothing to say about it.
        """
        _attributes = {}

        _frequency = self._tuner.get("frequency")
        if _frequency is not None:
            _attributes["frequency_mhz"] = round(_frequency / 100, 2)
            _modulation = self._tuner.get("modulation", MODULATION_FM)
            if _modulation != MODULATION_FM:
                _attributes["modulation"] = _modulation

        _preset = self._tuner.get("station")
        if _preset is not None:
            _attributes["preset"] = _preset

        _rds = self._tuner.get("rds")
        if _rds is not None:
            _attributes["rds_name"] = _rds

        return _attributes

    # -------------------------------------------------------------- commands #

    async def async_update(self):
        """Ask the tuner what it is playing, unless something already has.

        The flag is the one the amplifiers claim, so a gateway asks once however
        many entities read that source. Identical to the number's: they are two
        readings of one box, and whichever is added first does the asking.
        """
        _tuner = self._tuner
        if _tuner.get(CONF_TUNER_REQUESTED):
            return
        _tuner[CONF_TUNER_REQUESTED] = True

        await request_tuning(self._gateway_handler, self._source)

    async def async_select_option(self, option: str) -> None:
        """Tune the source to that station; see `tuner.TunerState.select_station`.

        It spends the scratch preset of the gateway and does **not** turn any
        amplifier on: which speakers play the tuner is a separate question.
        """
        await self._tuner_state.select_station(option)

    # ----------------------------------------------------------------- events #

    def handle_event(self, message) -> None:
        """Show what the shared tuner store just learned."""
        LOGGER.debug("%s Tuner event: %s", self._gateway_handler.log_id, message)

        if isinstance(message, SOURCE_EVENTS) and message.source != self._source:
            # Verified on hardware: a request addressed to one source is
            # answered by all of them. This entity reads one.
            return

        self.async_write_ha_state()
