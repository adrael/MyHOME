"""Support for MyHome sound diffusion tuners (WHO=22), as a tunable frequency.

One entity per source, `number.tuner_fm_frequency`: the frequency the shared
tuner sits on, and the only control able to send it to a frequency the station
table does not carry.
"""

from homeassistant.components.number import (
    DOMAIN as PLATFORM,
    NumberEntity,
    NumberMode,
)

from homeassistant.const import (
    CONF_NAME,
    CONF_MAC,
)

from OWNd.message import OWNCommand

from .const import (
    CONF_ENTITY,
    CONF_PLATFORMS,
    CONF_SOURCE,
    CONF_TUNER_REQUESTED,
    CONF_TUNING_PRESET,
    CONF_WHO,
    CONF_WHERE,
    CONF_MANUFACTURER,
    CONF_DEVICE_MODEL,
    DOMAIN,
    LOGGER,
)
from .sound_diffusion import (
    DEFAULT_TUNING_PRESET,
    FREQUENCY_STEP,
    MAX_FREQUENCY,
    MIN_FREQUENCY,
    MODULATION_FM,
    SOURCE_EVENTS,
    SourceFrequencyStation,
    request_source_frequency_station,
    set_frequency,
)
from .tuner import MyHOMETunerEntity


async def async_setup_entry(hass, config_entry, async_add_entities):
    if PLATFORM not in hass.data[DOMAIN][config_entry.data[CONF_MAC]][CONF_PLATFORMS]:
        return

    _tuners = []
    _configured_tuners = hass.data[DOMAIN][config_entry.data[CONF_MAC]][CONF_PLATFORMS][PLATFORM]

    for _device_id, _device in _configured_tuners.items():
        _tuners.append(
            MyHOMETunerFrequency(
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

    Home Assistant never calls this: unloading a config entry resets the entity
    platform, which removes the entities one by one through
    `async_will_remove_from_hass` and never looks for a module level
    `async_unload_entry` — only `__init__.py` has one that is called. Kept
    because every platform of this integration carries the same hook.
    """
    if PLATFORM not in hass.data[DOMAIN][config_entry.data[CONF_MAC]][CONF_PLATFORMS]:
        return True

    # Iterated over a copy: the loop is deleting out of the dict it walks.
    for _device_id in list(hass.data[DOMAIN][config_entry.data[CONF_MAC]][CONF_PLATFORMS][PLATFORM]):
        del hass.data[DOMAIN][config_entry.data[CONF_MAC]][CONF_PLATFORMS][PLATFORM][_device_id]

    return True


class MyHOMETunerFrequency(MyHOMETunerEntity, NumberEntity):
    """The frequency of one tuner, in MHz, readable and writable.

    Writing it is the same trick `media_player.select_source` plays: an FM tuner
    has no "go to 101.1 MHz" command, so the frequency is written into one of the
    fifteen presets — always the same scratch one, the `tuning_preset` option of
    the gateway — which retunes the box at once.
    """

    _attr_native_unit_of_measurement = "MHz"
    _attr_native_min_value = MIN_FREQUENCY / 100
    _attr_native_max_value = MAX_FREQUENCY / 100
    _attr_native_step = FREQUENCY_STEP / 100
    # `AUTO` and not `SLIDER`: the band holds 410 steps, and Home Assistant
    # turns a range that long into a text box in the more-info dialog rather
    # than a slider nobody can land on a channel with. The slider of the
    # dashboard is the `numeric-input` tile feature, which asks for one; see
    # `examples/dashboard-radios.yaml`.
    _attr_mode = NumberMode.AUTO
    _attr_icon = "mdi:sine-wave"

    def __init__(self, hass, **kwargs):
        super().__init__(
            hass=hass,
            entity_key="frequency",
            entity_name="Frequency",
            platform=PLATFORM,
            **kwargs,
        )

    # ----------------------------------------------------------------- state #

    @property
    def native_value(self):
        """The frequency the tuner reported, in MHz, `None` until it says one."""
        _frequency = self._tuner.get("frequency")
        return None if _frequency is None else _frequency / 100

    @property
    def _tuning_preset(self) -> int:
        """Preset a write overwrites, the `tuning_preset` of the gateway.

        Read with a default rather than with `or`: a preset of 0 means nothing
        at all and must not be quietly read as 15.
        """
        return self._hass.data[DOMAIN][self._gateway_handler.mac].get(CONF_TUNING_PRESET, DEFAULT_TUNING_PRESET)

    # -------------------------------------------------------------- commands #

    async def async_update(self):
        """Ask the tuner what it is playing, unless an amplifier already has.

        The flag is the one the amplifiers claim, so a gateway asks once however
        many entities read that source.
        """
        _tuner = self._tuner
        if _tuner.get(CONF_TUNER_REQUESTED):
            return
        _tuner[CONF_TUNER_REQUESTED] = True

        await self._gateway_handler.send_status_request(OWNCommand(request_source_frequency_station(self._source)))

    async def async_set_native_value(self, value: float) -> None:
        """Retune the source, spending the scratch preset.

        The bus echoes the new tuning about 250 ms later; recording it now is
        what makes the slider feel immediate, and leaves the echo with nothing
        new to say. Both the frequency and the preset are recorded, exactly as
        `select_source` does — the preset is what the tuner will report.

        Snapped onto the step first: the box of the more-info dialog takes any
        value, 87.53 MHz included, and the tuner has no such channel. Rounding
        it here rather than sending it is what keeps the echo silent — the store
        holds the frequency the tuner will answer with, not the one asked for.
        """
        _frequency = round(value * 100 / FREQUENCY_STEP) * FREQUENCY_STEP
        _preset = self._tuning_preset

        self._gateway_handler.refresh_sound_source(
            SourceFrequencyStation(
                source=self._source,
                modulation=MODULATION_FM,
                frequency=_frequency,
                station=_preset,
            )
        )
        await self._command(set_frequency(self._source, _frequency, _preset - 1))

    # ----------------------------------------------------------------- events #

    def handle_event(self, message) -> None:
        """Show what the shared tuner store just learned."""
        LOGGER.debug("%s Tuner event: %s", self._gateway_handler.log_id, message)

        if isinstance(message, SOURCE_EVENTS) and message.source != self._source:
            # Verified on hardware: a request addressed to one source is
            # answered by all of them. This entity reads one.
            return

        self.async_write_ha_state()
