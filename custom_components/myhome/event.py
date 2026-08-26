"""Doorbell event entities for MyHome video door entry (WHO=8).

One `event` entity per configured entrance panel, `event.<name>_doorbell`,
firing a `ring` event when the panel's bell is pressed. An auto-on — someone
looking at the camera — is a different WHO=8 frame (`*8*1#5#…` rather than
`*8*1#1#…`) and does **not** fire it; see `video_door_entry.py`.

The panels are declared under `video_door_entry:` in `myhome.yaml`;
`validate.py` derives one `event` device per panel out of them.
"""

from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .gateway import MyHOMEGatewayHandler

from homeassistant.components.event import (
    DOMAIN as PLATFORM,
    EventDeviceClass,
    EventEntity,
)

from homeassistant.const import (
    CONF_NAME,
    CONF_MAC,
)

from .const import (
    CONF_ENTITY,
    CONF_PLATFORMS,
    CONF_WHO,
    CONF_WHERE,
    CONF_ENTITY_NAME,
    CONF_MANUFACTURER,
    CONF_DEVICE_MODEL,
    DOMAIN,
    LOGGER,
)
from .myhome_device import MyHOMEEntity
from .video_door_entry import RING_EVENTS


async def async_setup_entry(hass, config_entry, async_add_entities):
    if PLATFORM not in hass.data[DOMAIN][config_entry.data[CONF_MAC]][CONF_PLATFORMS]:
        return True

    _events = []
    _configured = hass.data[DOMAIN][config_entry.data[CONF_MAC]][CONF_PLATFORMS][PLATFORM]

    for _device_id, _device in _configured.items():
        if _device[CONF_WHO] != "8":
            continue
        _events.append(
            MyHOMEDoorbell(
                hass=hass,
                device_id=_device_id,
                who=_device[CONF_WHO],
                where=_device[CONF_WHERE],
                name=_device[CONF_NAME],
                entity_name=_device[CONF_ENTITY_NAME],
                manufacturer=_device[CONF_MANUFACTURER],
                model=_device[CONF_DEVICE_MODEL],
                gateway=hass.data[DOMAIN][config_entry.data[CONF_MAC]][CONF_ENTITY],
            )
        )

    async_add_entities(_events)


async def async_unload_entry(hass, config_entry):
    """Forget the doorbell devices of this gateway.

    Home Assistant never calls this, exactly as in the other platforms: unloading
    a config entry resets the entity platform, which removes the entities one by
    one. Kept because every platform of this integration carries the same hook.
    """
    if PLATFORM not in hass.data[DOMAIN][config_entry.data[CONF_MAC]][CONF_PLATFORMS]:
        return True

    for _device_id in list(hass.data[DOMAIN][config_entry.data[CONF_MAC]][CONF_PLATFORMS][PLATFORM]):
        del hass.data[DOMAIN][config_entry.data[CONF_MAC]][CONF_PLATFORMS][PLATFORM][_device_id]

    return True


class MyHOMEDoorbell(MyHOMEEntity, EventEntity):
    """The doorbell of one entrance panel, firing `ring` when the bell is pressed."""

    _attr_device_class = EventDeviceClass.DOORBELL
    _attr_event_types = ["ring"]
    _attr_icon = "mdi:doorbell-video"

    def __init__(
        self,
        hass,
        name: str,
        entity_name: str,
        device_id: str,
        who: str,
        where: str,
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
        self._attr_name = entity_name if entity_name else "Doorbell"
        self._attr_unique_id = f"{gateway.mac}-{self._device_id}"

    async def async_update(self):
        """Nothing to poll: the ring is pushed by the gateway."""

    def handle_event(self, message) -> None:
        """Fire `ring` on a doorbell press; ignore every other WHO=8 event."""
        if not isinstance(message, RING_EVENTS):
            return
        LOGGER.info("%s Doorbell ring: %s", self._gateway_handler.log_id, message)
        self._trigger_event("ring")
        self.async_write_ha_state()
