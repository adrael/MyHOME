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

from OWNd.message import OWNCommand

from .const import (
    CONF_DEVICE_MODEL,
    CONF_ENTITIES,
    CONF_MANUFACTURER,
    CONF_PLATFORMS,
    CONF_SOUND_SOURCES,
    CONF_SOURCE,
    CONF_WHERE,
    CONF_WHO,
    DOMAIN,
)
from .myhome_device import MyHOMEEntity
from .sound_diffusion import (
    frequency_seek_down,
    frequency_seek_up,
    station_next,
    station_previous,
)


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
    def _tuner(self) -> dict:
        """Tuning information of this source, shared with its amplifiers."""
        return self._hass.data[DOMAIN][self._gateway_handler.mac].setdefault(CONF_SOUND_SOURCES, {}).setdefault(self._source, {})

    async def _command(self, frame: str) -> None:
        """Send a frame to the gateway."""
        await self._gateway_handler.send(OWNCommand(frame))

    # ---------------------------------------------------------------- wiring #

    async def async_added_to_hass(self):
        """When entity is added to hass.

        `MyHOMEEntity` registers itself under the platform name, which would
        have the five entities of a tuner overwrite one another, and calls
        `async_update`, which Home Assistant does on its own for a tuner entity.
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

    def __init__(self, hass, entity_key: str, entity_name: str, icon: str, frame, **kwargs):
        super().__init__(
            hass=hass,
            entity_key=entity_key,
            entity_name=entity_name,
            platform=BUTTON_PLATFORM,
            **kwargs,
        )
        self._attr_icon = icon
        self._frame = frame

    async def async_press(self) -> None:
        """Press the button."""
        await self._command(self._frame(self._source))


#: The four buttons of a tuner device, in the order they are created.
#:
#: `entity_key` ends up in the unique id and `entity_name` in the entity id, so
#: neither can be changed without orphaning what is already in the registry.
TUNER_BUTTONS = (
    ("seek_up", "Seek up", "mdi:magnify-plus-outline", frequency_seek_up),
    ("seek_down", "Seek down", "mdi:magnify-minus-outline", frequency_seek_down),
    ("next_preset", "Next preset", "mdi:skip-next", station_next),
    ("previous_preset", "Previous preset", "mdi:skip-previous", station_previous),
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
            name=device[CONF_NAME],
            device_id=device_id,
            who=device[CONF_WHO],
            where=device[CONF_WHERE],
            source=device[CONF_SOURCE],
            manufacturer=device[CONF_MANUFACTURER],
            model=device[CONF_DEVICE_MODEL],
            gateway=gateway,
        )
        for _key, _name, _icon, _frame in TUNER_BUTTONS
    ]
