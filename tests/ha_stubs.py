"""Minimal Home Assistant stand-ins, so the integration modules can be imported.

Home Assistant is not a dependency of this repository: the tests stub just
enough of it (module layout, entity base class, device class enumerations) to
import `validate.py`, `gateway.py` and `media_player.py` and exercise their
pure logic. OWNd is a real dependency and is imported for real.

The `myhome` package is loaded under the name ``myhome`` rather than
``custom_components.myhome`` so that nothing pulls in the integration's
``__init__.py``, which needs the full Home Assistant runtime.
"""

import importlib.util
import os
import sys
import types

MYHOME_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "custom_components",
    "myhome",
)

#: Platform domains the integration imports `DOMAIN` from.
_PLATFORMS = [
    "light",
    "switch",
    "button",
    "cover",
    "binary_sensor",
    "sensor",
    "climate",
    "media_player",
]


class Entity:
    """Stand-in for `homeassistant.helpers.entity.Entity`."""

    _attr_should_poll = True
    #: A class attribute: `MyHOMEEntity.__init__` never calls `super().__init__`.
    written_states = 0

    def async_write_ha_state(self):
        self.written_states = self.written_states + 1

    def async_schedule_update_ha_state(self, force_refresh=False):
        self.written_states = self.written_states + 1


class MediaPlayerEntity(Entity):
    """Stand-in exposing the `_attr_*` fallbacks the real class provides."""

    _attr_state = None
    _attr_volume_level = None

    @property
    def state(self):
        return self._attr_state

    @property
    def volume_level(self):
        return self._attr_volume_level


class _StringEnumMeta(type):
    """Turns any attribute access into its lower-case name, as HA's enums do."""

    def __getattr__(cls, name):
        if name.startswith("_"):
            raise AttributeError(name)
        value = name.lower()
        setattr(cls, name, value)
        return value


class SwitchDeviceClass(metaclass=_StringEnumMeta):
    pass


class BinarySensorDeviceClass(metaclass=_StringEnumMeta):
    pass


class SensorDeviceClass(metaclass=_StringEnumMeta):
    pass


class MediaPlayerDeviceClass(metaclass=_StringEnumMeta):
    pass


class MediaPlayerState(metaclass=_StringEnumMeta):
    pass


class MediaType(metaclass=_StringEnumMeta):
    pass


class MediaPlayerEntityFeature:
    """`IntFlag` stand-in: the integration only ORs the members together."""

    TURN_ON = 128
    TURN_OFF = 256
    VOLUME_SET = 4
    VOLUME_STEP = 1024
    NEXT_TRACK = 32
    PREVIOUS_TRACK = 16


class EntityCategory(metaclass=_StringEnumMeta):
    pass


def _module(name, **attributes):
    module = types.ModuleType(name)
    for key, value in attributes.items():
        setattr(module, key, value)
    sys.modules[name] = module
    return module


def install():
    """Register the Home Assistant stubs in `sys.modules`, once."""
    if "homeassistant" in sys.modules:
        return

    _module("homeassistant")
    _module("homeassistant.core", HomeAssistant=object)
    _module("homeassistant.helpers")
    _module("homeassistant.helpers.entity", Entity=Entity)
    _module(
        "homeassistant.helpers.device_registry",
        format_mac=lambda mac: ":".join(mac.lower()[i : i + 2] for i in range(0, 12, 2)),
    )
    _module(
        "homeassistant.const",
        CONF_NAME="name",
        CONF_MAC="mac",
        CONF_ENTITIES="entities",
        CONF_HOST="host",
        CONF_PORT="port",
        CONF_PASSWORD="password",
        CONF_FRIENDLY_NAME="friendly_name",
        EntityCategory=EntityCategory,
    )
    _module("homeassistant.components")
    for _platform in _PLATFORMS:
        _module(f"homeassistant.components.{_platform}", DOMAIN=_platform)

    sys.modules["homeassistant.components.switch"].SwitchDeviceClass = SwitchDeviceClass
    sys.modules["homeassistant.components.binary_sensor"].BinarySensorDeviceClass = BinarySensorDeviceClass
    sys.modules["homeassistant.components.sensor"].SensorDeviceClass = SensorDeviceClass
    sys.modules["homeassistant.components.button"].ButtonEntity = type("ButtonEntity", (Entity,), {})
    _media_player = sys.modules["homeassistant.components.media_player"]
    _media_player.MediaPlayerEntity = MediaPlayerEntity
    _media_player.MediaPlayerDeviceClass = MediaPlayerDeviceClass
    _media_player.MediaPlayerState = MediaPlayerState
    _media_player.MediaType = MediaType
    _media_player.MediaPlayerEntityFeature = MediaPlayerEntityFeature


def load(name):
    """Import `custom_components/myhome/<name>.py` as `myhome.<name>`."""
    install()
    if "myhome" not in sys.modules:
        _package = types.ModuleType("myhome")
        _package.__path__ = [MYHOME_PATH]
        sys.modules["myhome"] = _package

    _full_name = f"myhome.{name}"
    if _full_name in sys.modules:
        return sys.modules[_full_name]

    _spec = importlib.util.spec_from_file_location(_full_name, os.path.join(MYHOME_PATH, f"{name}.py"))
    _module_object = importlib.util.module_from_spec(_spec)
    sys.modules[_full_name] = _module_object
    _spec.loader.exec_module(_module_object)
    setattr(sys.modules["myhome"], name, _module_object)
    return _module_object
