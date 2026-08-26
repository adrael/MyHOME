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
    _attr_available = True
    #: Home Assistant sets both when the entity is added to a platform; until
    #: then writing a state raises, exactly as the real class does.
    hass = None
    entity_id = None
    #: A class attribute: `MyHOMEEntity.__init__` never calls `super().__init__`.
    written_states = 0

    @property
    def available(self):
        return self._attr_available

    def _assert_added(self):
        if self.hass is None:
            raise RuntimeError(f"Attribute hass is None for {type(self).__name__}")

    def async_write_ha_state(self):
        self._assert_added()
        self.written_states = self.written_states + 1

    def async_schedule_update_ha_state(self, force_refresh=False):
        self._assert_added()
        self.written_states = self.written_states + 1


class MediaPlayerEntity(Entity):
    """Stand-in exposing the `_attr_*` fallbacks the real class provides."""

    _attr_state = None
    _attr_volume_level = None
    _attr_supported_features = 0

    @property
    def supported_features(self):
        return self._attr_supported_features

    @property
    def state(self):
        return self._attr_state

    @property
    def volume_level(self):
        return self._attr_volume_level


class _StringEnumMeta(type):
    """Turns the declared members into their lower-case name, as HA's enums do.

    Only the declared ones: a typo in a member name has to raise here just as it
    would against the real `StrEnum`, otherwise a test comparing against
    `MediaPlayerState.PLAYNG` would quietly compare two invented strings.
    """

    def __new__(mcs, name, bases, namespace):
        _class = super().__new__(mcs, name, bases, namespace)
        for _member in namespace.get("_members", ()):
            setattr(_class, _member, _member.lower())
        return _class

    def __getattr__(cls, name):
        raise AttributeError(f"{cls.__name__} has no member named {name}")


class SwitchDeviceClass(metaclass=_StringEnumMeta):
    _members = ("OUTLET", "SWITCH")


class BinarySensorDeviceClass(metaclass=_StringEnumMeta):
    _members = (
        "BATTERY",
        "BATTERY_CHARGING",
        "CO",
        "COLD",
        "CONNECTIVITY",
        "DOOR",
        "GARAGE_DOOR",
        "GAS",
        "HEAT",
        "LIGHT",
        "LOCK",
        "MOISTURE",
        "MOTION",
        "MOVING",
        "OCCUPANCY",
        "OPENING",
        "PLUG",
        "POWER",
        "PRESENCE",
        "PROBLEM",
        "RUNNING",
        "SAFETY",
        "SMOKE",
        "SOUND",
        "TAMPER",
        "UPDATE",
        "VIBRATION",
        "WINDOW",
    )


class SensorDeviceClass(metaclass=_StringEnumMeta):
    _members = ("ENERGY", "HUMIDITY", "ILLUMINANCE", "POWER", "PRESSURE", "TEMPERATURE", "VOLTAGE")


class MediaPlayerDeviceClass(metaclass=_StringEnumMeta):
    _members = ("RECEIVER", "SPEAKER", "TV")


class MediaPlayerState(metaclass=_StringEnumMeta):
    _members = ("BUFFERING", "IDLE", "OFF", "ON", "PAUSED", "PLAYING", "STANDBY")


class MediaType(metaclass=_StringEnumMeta):
    _members = ("APP", "CHANNEL", "EPISODE", "IMAGE", "MOVIE", "MUSIC", "PLAYLIST", "TVSHOW", "URL", "VIDEO")


class MediaPlayerEntityFeature:
    """`IntFlag` stand-in: the integration only ORs the members together."""

    TURN_ON = 128
    TURN_OFF = 256
    VOLUME_SET = 4
    VOLUME_STEP = 1024
    NEXT_TRACK = 32
    PREVIOUS_TRACK = 16
    SELECT_SOURCE = 2048


class HomeAssistantError(Exception):
    """Stand-in for `homeassistant.exceptions.HomeAssistantError`."""


class ServiceValidationError(HomeAssistantError):
    """Stand-in for `homeassistant.exceptions.ServiceValidationError`."""


class EntityCategory(metaclass=_StringEnumMeta):
    _members = ("CONFIG", "DIAGNOSTIC")


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
    _module(
        "homeassistant.exceptions",
        HomeAssistantError=HomeAssistantError,
        ServiceValidationError=ServiceValidationError,
    )
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
