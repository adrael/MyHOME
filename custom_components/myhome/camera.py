"""Snapshot camera for MyHome video door entry (WHO=8).

One `camera` entity per entrance panel that carries a camera password, pulling a
still from the panel's own web endpoint: ``GET https://<host>/telecamera.php?
CAM_PASSWD=<password>`` returns a 320x240 JPEG.

The stream is only live while a video session is open — a call, or the WHO=7
activation frame this entity sends first — so every snapshot opens a session and
then fetches one frame. The panel saturates if polled hard (verified on
hardware), so a snapshot is taken at most once every :data:`SNAPSHOT_THROTTLE`
seconds and the last frame is served in between; that window is also the
camera's `frame_interval`, which is the cadence Home Assistant's live view pulls
at.

Nothing here is verified on hardware end to end from Home Assistant yet: the
endpoint and the JPEG were confirmed on the panel, the wiring through
`async_camera_image` was not.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

import aiohttp

if TYPE_CHECKING:
    from .gateway import MyHOMEGatewayHandler

from homeassistant.components.camera import (
    DOMAIN as PLATFORM,
    Camera,
)

from homeassistant.const import (
    CONF_NAME,
    CONF_MAC,
    CONF_ENTITIES,
)
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from OWNd.message import OWNCommand

from .const import (
    CONF_ENTITY,
    CONF_PLATFORMS,
    CONF_WHO,
    CONF_WHERE,
    CONF_ENTITY_NAME,
    CONF_CAMERA_WHERE,
    CONF_CAMERA_PASSWORD,
    CONF_CAMERA_HOST,
    CONF_VERIFY_SSL,
    CONF_MANUFACTURER,
    CONF_DEVICE_MODEL,
    DOMAIN,
    LOGGER,
)
from .myhome_device import MyHOMEEntity
from .video_door_entry import activate_camera

#: A snapshot opens a video session and fetches one frame at most this often, in
#: seconds. The panel is fragile under load, so this is deliberately slow.
SNAPSHOT_THROTTLE = 2.0

#: Seconds to wait after opening the video session before pulling a frame.
#: ``send()`` only queues the ``*7*0*`` activation — a separate sending worker
#: transmits it — so the stream is not live the instant ``send()`` returns; a
#: short pause lets the panel bring the camera up before the GET. Empirical:
#: tune on hardware.
CAMERA_WARMUP = 0.8


async def async_setup_entry(hass, config_entry, async_add_entities):
    if PLATFORM not in hass.data[DOMAIN][config_entry.data[CONF_MAC]][CONF_PLATFORMS]:
        return True

    _cameras = []
    _configured = hass.data[DOMAIN][config_entry.data[CONF_MAC]][CONF_PLATFORMS][PLATFORM]

    for _device_id, _device in _configured.items():
        if _device[CONF_WHO] != "8":
            continue
        if not _device.get(CONF_CAMERA_PASSWORD):
            # `validate.py` only builds a camera device for a panel with a
            # password, so this is belt and braces: a camera with no way in is
            # of no use, and is not created.
            LOGGER.warning(
                "Video door entry camera `%s` has no camera_password; not creating it.",
                _device_id,
            )
            continue
        _cameras.append(
            MyHOMEDoorCamera(
                hass=hass,
                device_id=_device_id,
                who=_device[CONF_WHO],
                where=_device[CONF_WHERE],
                name=_device[CONF_NAME],
                entity_name=_device[CONF_ENTITY_NAME],
                camera_where=_device[CONF_CAMERA_WHERE],
                camera_password=_device[CONF_CAMERA_PASSWORD],
                camera_host=_device[CONF_CAMERA_HOST],
                verify_ssl=_device[CONF_VERIFY_SSL],
                manufacturer=_device[CONF_MANUFACTURER],
                model=_device[CONF_DEVICE_MODEL],
                gateway=hass.data[DOMAIN][config_entry.data[CONF_MAC]][CONF_ENTITY],
            )
        )

    async_add_entities(_cameras)


async def async_unload_entry(hass, config_entry):
    """Forget the camera devices of this gateway.

    Home Assistant never calls this, like the other platforms; kept for symmetry.
    """
    if PLATFORM not in hass.data[DOMAIN][config_entry.data[CONF_MAC]][CONF_PLATFORMS]:
        return True

    for _device_id in list(hass.data[DOMAIN][config_entry.data[CONF_MAC]][CONF_PLATFORMS][PLATFORM]):
        del hass.data[DOMAIN][config_entry.data[CONF_MAC]][CONF_PLATFORMS][PLATFORM][_device_id]

    return True


class MyHOMEDoorCamera(MyHOMEEntity, Camera):
    """A pull-only camera taking a still through the panel's `telecamera.php`."""

    _attr_frame_interval = SNAPSHOT_THROTTLE
    _attr_icon = "mdi:doorbell-video"

    def __init__(
        self,
        hass,
        name: str,
        entity_name: str,
        device_id: str,
        who: str,
        where: str,
        camera_where: int,
        camera_password: str,
        camera_host: str,
        verify_ssl: bool,
        manufacturer: str,
        model: str,
        gateway: MyHOMEGatewayHandler,
    ):
        # `MyHOMEEntity.__init__` does not chain to `super().__init__`, so the
        # `Camera` base is initialised by hand — it sets `content_type`, the
        # access-token deque the camera proxy view reads, and more.
        Camera.__init__(self)
        MyHOMEEntity.__init__(
            self,
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
        self._attr_name = entity_name if entity_name else "Camera"
        self._attr_unique_id = f"{gateway.mac}-{self._device_id}"

        self._camera_where = camera_where
        self._camera_password = camera_password
        self._camera_host = camera_host
        self._verify_ssl = verify_ssl

        self._last_image = None
        # `None` until the first fetch is attempted, not `0.0`: `time.monotonic()`
        # has an arbitrary origin (uptime on Linux) and can legitimately read
        # near zero just after a boot, which a numeric sentinel would misread as
        # "never fetched" and skip the throttle on.
        self._last_fetch = None
        self._fetch_lock = asyncio.Lock()

    async def async_added_to_hass(self):
        """When entity is added to hass."""
        self._hass.data[DOMAIN][self._gateway_handler.mac][CONF_PLATFORMS][self._platform][self._device_id][CONF_ENTITIES]["camera"] = self

    async def async_will_remove_from_hass(self):
        """When entity is removed from hass."""
        _entities = self._hass.data[DOMAIN][self._gateway_handler.mac][CONF_PLATFORMS][self._platform][self._device_id][CONF_ENTITIES]
        if "camera" in _entities:
            del _entities["camera"]

    @property
    def _host(self) -> str:
        """Camera host: the configured one, else the gateway's own address."""
        return self._camera_host or str(self._gateway_handler.gateway.host)

    async def async_camera_image(self, width=None, height=None):
        """Open a session, pull one JPEG, and cache it for the throttle window.

        Both arguments are ignored: the panel returns a fixed 320x240 frame, and
        Home Assistant scales it if it needs to.

        The camera password never reaches the log. It rides in the query string,
        so the request URL — and any aiohttp exception that carries it, a 401
        being the usual one — must never be interpolated into a log line; a
        failure is reported by exception type and HTTP status only.
        """
        async with self._fetch_lock:
            _now = time.monotonic()
            # Throttle on elapsed time alone, never on "do we have an image yet":
            # a panel stuck on a persistent 401 must not re-open a session and
            # hammer the bus and the web endpoint on every single call. The stamp
            # is taken before the fetch so a failure counts against the window too.
            if self._last_fetch is not None and (_now - self._last_fetch) < SNAPSHOT_THROTTLE:
                return self._last_image
            self._last_fetch = _now

            try:
                # The stream is dark outside a session, so open one first, then
                # give the panel a moment to bring the camera up before pulling.
                # Activation is inside the try: a failure to queue it must not
                # take the entity down any more than a failed fetch does.
                await self._gateway_handler.send(OWNCommand(activate_camera(self._camera_where)))
                await asyncio.sleep(CAMERA_WARMUP)

                _session = async_get_clientsession(self._hass, self._verify_ssl)
                async with _session.get(
                    f"https://{self._host}/telecamera.php",
                    params={"CAM_PASSWD": self._camera_password},
                    timeout=aiohttp.ClientTimeout(total=8),
                ) as _response:
                    _response.raise_for_status()
                    self._last_image = await _response.read()
            except Exception as _err:  # pylint: disable=broad-except
                # A snapshot that fails is served as the last one we had, or as
                # nothing; it must never take the entity down. Logged by type and
                # status only — never the exception itself: its string carries the
                # request URL, and the URL carries the camera password.
                LOGGER.warning(
                    "%s Could not fetch the door camera snapshot (%s, status %s).",
                    self._gateway_handler.log_id,
                    type(_err).__name__,
                    getattr(_err, "status", None),
                )
            return self._last_image
