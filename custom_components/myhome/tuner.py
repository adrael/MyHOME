"""Entities of a MyHome sound diffusion tuner (WHO=22, source `2#<source>`).

A tuner is not declared anywhere in `myhome.yaml`: it is the source the
configured amplifiers listen to, and `validate.py` derives one device per
distinct source. The amplifiers are the `media_player` platform; what is left —
the frequency the box sits on and the four ways of moving it — belongs to the
tuner itself rather than to any one speaker, hence a device of its own carrying
a `number` and four `button` entities.

The entity classes live here, shared, because they are spread over two
platforms: `number.py` and `button.py` both set up part of the same device.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .gateway import MyHOMEGatewayHandler

from homeassistant.components.button import (
    DOMAIN as BUTTON_PLATFORM,
    ButtonEntity,
)

from homeassistant.const import CONF_NAME

from homeassistant.exceptions import ServiceValidationError

from OWNd.message import OWNCommand

from .const import (
    CONF_DEVICE_MODEL,
    CONF_ENTITIES,
    CONF_MANUFACTURER,
    CONF_PLATFORMS,
    CONF_RADIO_STATIONS,
    CONF_SOUND_SOURCES,
    CONF_SOURCE,
    CONF_TUNING_PRESET,
    CONF_WHERE,
    CONF_WHO,
    DOMAIN,
)
from .myhome_device import MyHOMEEntity
from .sound_diffusion import (
    DEFAULT_TUNING_PRESET,
    MODULATION_FM,
    SourceFrequencyStation,
    SourceStation,
    frequency_seek_down,
    frequency_seek_up,
    rds_start,
    request_source_frequency_station,
    set_frequency,
    station_entries,
    station_label,
    station_next,
    station_previous,
)


async def request_tuning(gateway: MyHOMEGatewayHandler, source: int) -> None:
    """Ask a source what it is playing, and have it tell its RDS name from now on.

    The two things a tuner is asked for once per connection, together in one
    place: every caller is a `CONF_TUNER_REQUESTED` claim — the amplifiers of
    `media_player.async_update` and the entities of the tuner device — so a
    source is asked once however many entities read it, and asked again after a
    reconnection, which clears the flag.

    The RDS stream needs no repeating: once started, the tuner keeps sending a
    name per text it receives, station changes included (verified on hardware
    2026-08-26). It is sent as a command rather than as a status request — it
    changes what the tuner does, and its answers arrive whenever the radio has
    something to say, not as a reply.
    """
    await gateway.send_status_request(OWNCommand(request_source_frequency_station(source)))
    await gateway.send(OWNCommand(rds_start(source)))


class TunerState:
    """What one source is tuned to, and the one way of sending it elsewhere.

    A source is a box shared by every amplifier listening to it, so its tuning
    is held once per gateway rather than on any one entity. This is that store,
    with the two gateway options that go with it, so that picking a station by
    name is one piece of code: `media_player.async_select_source` and the
    `select` entity of the tuner device both come through `select_station`.

    Built on the spot wherever it is needed — it holds nothing of its own, only
    the way to `hass.data`.
    """

    def __init__(self, hass, gateway: MyHOMEGatewayHandler, source: int):
        self._hass = hass
        self._gateway = gateway
        self._source = source

    @property
    def _gateway_data(self) -> dict:
        return self._hass.data[DOMAIN][self._gateway.mac]

    @property
    def store(self) -> dict:
        """Tuning of this source, shared with every entity that reads it."""
        return self._gateway_data.setdefault(CONF_SOUND_SOURCES, {}).setdefault(self._source, {})

    @property
    def radio_stations(self):
        """Station table configured on the gateway, `None` for the built-in one.

        An empty table is no table: `radio_stations:` left blank in the
        configuration file must not blank out every station name.
        """
        return self._gateway_data.get(CONF_RADIO_STATIONS) or None

    @property
    def tuning_preset(self) -> int:
        """Preset a retuning overwrites, the `tuning_preset` of the gateway.

        Read with a default rather than with `or`, unlike `radio_stations` just
        above: an empty station table means "no table", a preset of 0 means
        nothing at all and must not be quietly read as 15.
        """
        return self._gateway_data.get(CONF_TUNING_PRESET, DEFAULT_TUNING_PRESET)

    @property
    def frequency(self):
        """Frequency the source reported, in hundredths of MHz."""
        return self.store.get("frequency")

    @property
    def station_options(self) -> list:
        """Every station of the table, by frequency, as a user picks them.

        The list describes what the tuner can be sent to, so it is the same on
        every entity of a gateway.
        """
        return [_label for _frequency, _name, _label in station_entries(self.radio_stations)]

    @property
    def selected_station(self):
        """Label of the station the source is on, `None` when it is unlisted."""
        return station_label(self.frequency, self.radio_stations)

    async def select_station(self, label: str) -> None:
        """Tune the source to the station labelled `label`.

        The tuner only goes to a frequency by having it written into one of its
        fifteen presets, so this overwrites the same scratch preset every time —
        the `tuning_preset` option of the gateway, 15 by default. The preset
        number in the frame is 0-based, hence the `- 1`; see
        :func:`sound_diffusion.set_frequency`.

        The bus echoes the new tuning about 250 ms later, which the optimistic
        refresh only hides. Both the frequency and the preset are recorded, so
        that echo says nothing new and the entities are written once.
        """
        _frequency = next(
            (_frequency for _frequency, _name, _label in station_entries(self.radio_stations) if _label == label),
            None,
        )
        if _frequency is None:
            raise ServiceValidationError(f"`{label}` is not a station of this gateway's table.")

        _preset = self.tuning_preset
        self._gateway.refresh_sound_source(
            SourceFrequencyStation(
                source=self._source,
                modulation=MODULATION_FM,
                frequency=_frequency,
                station=_preset,
            )
        )
        await self._gateway.send(OWNCommand(set_frequency(self._source, _frequency, _preset - 1)))


class MyHOMETunerEntity(MyHOMEEntity):
    """One entity of a tuner device, keyed under its own name in `hass.data`.

    Several entities share the device, so each registers itself under a key of
    its own — `frequency`, `seek_up`, … — the way the two lock buttons of a
    light do. `__init__.py` rebuilds the unique ids out of exactly that, when it
    prunes the registry.
    """

    def __init__(
        self,
        hass,
        name: str,
        entity_name: str,
        entity_key: str,
        platform: str,
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
            platform=platform,
            device_id=device_id,
            who=who,
            where=where,
            manufacturer=manufacturer,
            model=model,
            gateway=gateway,
        )

        self._attr_name = entity_name
        self._entity_key = entity_key
        self._attr_unique_id = f"{gateway.mac}-{device_id}-{entity_key}"
        self._source = source

        # Make sure the shared tuner store exists before any event is dispatched.
        hass.data[DOMAIN][gateway.mac].setdefault(CONF_SOUND_SOURCES, {}).setdefault(source, {})

    # ----------------------------------------------------------------- state #

    @property
    def available(self) -> bool:
        """A tuner is only as reachable as the gateway in front of it."""
        return self._gateway_handler.is_connected

    @property
    def _tuner_state(self) -> TunerState:
        """The source this entity reads, and what can be done to it."""
        return TunerState(self._hass, self._gateway_handler, self._source)

    @property
    def _tuner(self) -> dict:
        """Tuning information of this source, shared with its amplifiers."""
        return self._tuner_state.store

    async def _command(self, frame: str) -> None:
        """Send a frame to the gateway."""
        await self._gateway_handler.send(OWNCommand(frame))

    # ---------------------------------------------------------------- wiring #

    async def async_added_to_hass(self):
        """When entity is added to hass.

        Overridden whole, for two reasons. `MyHOMEEntity` registers itself under
        the *platform* name, which would have the five entities of a tuner
        overwrite one another in `hass.data`; and it calls `async_update`, which
        is left out here — the source is asked for once per gateway, and the
        amplifiers claim that request when they are added (`CONF_TUNER_REQUESTED`
        in `media_player.async_update`). A tuner exists only because amplifiers
        listen to its source, so there is always one to ask.

        Nothing polls these entities either: `MyHOMEEntity` sets
        `_attr_should_poll = False`, so `async_update` runs on the way in and on
        `gateway.reconnected()`, and nowhere else.
        """
        self._hass.data[DOMAIN][self._gateway_handler.mac][CONF_PLATFORMS][self._platform][self._device_id][CONF_ENTITIES][self._entity_key] = self

    async def async_will_remove_from_hass(self):
        """When entity is removed from hass."""
        _entities = self._hass.data[DOMAIN][self._gateway_handler.mac][CONF_PLATFORMS][self._platform][self._device_id][CONF_ENTITIES]
        if self._entity_key in _entities:
            del _entities[self._entity_key]

    async def async_update(self):
        """Nothing to ask for: a button has no state. Overridden by the number."""

    def handle_event(self, message) -> None:
        """Handle a sound diffusion event dispatched by the gateway handler.

        Nothing to show by default, so nothing to write: overridden by the
        entities that display something.
        """


class MyHOMETunerButton(MyHOMETunerEntity, ButtonEntity):
    """A button moving the tuner, addressed to the source rather than to a speaker.

    Every frame is built by `sound_diffusion.py` and verified on hardware; which
    one this button sends is the `frame` builder it was handed.
    """

    def __init__(self, hass, entity_key: str, entity_name: str, icon: str, frame, drops_preset: bool = False, **kwargs):
        super().__init__(
            hass=hass,
            entity_key=entity_key,
            entity_name=entity_name,
            platform=BUTTON_PLATFORM,
            **kwargs,
        )
        self._attr_icon = icon
        self._frame = frame
        self._drops_preset = drops_preset

    async def async_press(self) -> None:
        """Press the button, dropping the preset first when this one scans.

        Verified on hardware 2026-08-26: an automatic scan upwards
        (`*22*5#*2#1##`) moves the tuner to the next station it catches and
        answers `*#22*5#2#1*5*1*10730##` — dimension 5 alone, no dimension 11
        and no dimension 6, so the slot it was on is left behind and never
        mentioned again. Nothing on the bus says so, which is why it is said
        here: this press is the only moment the scan is known to have happened.

        Optimistic like every other command of this integration, and recorded
        before sending for the same reason — the entities show it at once. A
        scan downwards puts the right number back when it falls onto a preset.
        """
        if self._drops_preset and self._tuner.get("station") is not None:
            self._gateway_handler.refresh_sound_source(SourceStation(source=self._source, station=None))
        await self._command(self._frame(self._source))


#: The four buttons of a tuner device, in the order they are created.
#:
#: `entity_key` ends up in the unique id and `entity_name` in the entity id, so
#: neither can be changed without orphaning what is already in the registry.
#:
#: The last field says whether the button leaves the tuner off its preset: the
#: two scans do, the two preset steps land on one and say which.
TUNER_BUTTONS = (
    ("seek_up", "Seek up", "mdi:magnify-plus-outline", frequency_seek_up, True),
    ("seek_down", "Seek down", "mdi:magnify-minus-outline", frequency_seek_down, True),
    ("next_preset", "Next preset", "mdi:skip-next", station_next, False),
    ("previous_preset", "Previous preset", "mdi:skip-previous", station_previous, False),
)


def tuner_buttons(hass, device_id: str, device: dict, gateway: MyHOMEGatewayHandler) -> list:
    """Every button entity of one tuner device."""
    return [
        MyHOMETunerButton(
            hass=hass,
            entity_key=_key,
            entity_name=_name,
            icon=_icon,
            frame=_frame,
            drops_preset=_drops_preset,
            name=device[CONF_NAME],
            device_id=device_id,
            who=device[CONF_WHO],
            where=device[CONF_WHERE],
            source=device[CONF_SOURCE],
            manufacturer=device[CONF_MANUFACTURER],
            model=device[CONF_DEVICE_MODEL],
            gateway=gateway,
        )
        for _key, _name, _icon, _frame, _drops_preset in TUNER_BUTTONS
    ]
