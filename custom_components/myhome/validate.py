"""Validator for the MyHome configuration file."""
import re

from voluptuous import (
    Schema,
    Optional,
    Required,
    Coerce,
    Boolean,
    Any,
    All,
    In,
    Invalid,
    Range,
)
from homeassistant.helpers.device_registry import format_mac as ha_format_mac
from homeassistant.components.light import DOMAIN as LIGHT
from homeassistant.components.switch import (
    SwitchDeviceClass,
    DOMAIN as SWITCH,
)
from homeassistant.components.button import DOMAIN as BUTTON
from homeassistant.components.cover import DOMAIN as COVER
from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    DOMAIN as BINARY_SENSOR,
)
from homeassistant.components.sensor import (
    SensorDeviceClass,
    DOMAIN as SENSOR,
)
from homeassistant.components.climate import DOMAIN as CLIMATE
from homeassistant.components.media_player import DOMAIN as MEDIA_PLAYER
from homeassistant.components.number import DOMAIN as NUMBER
from homeassistant.components.select import DOMAIN as SELECT
from homeassistant.components.event import DOMAIN as EVENT
from homeassistant.components.camera import DOMAIN as CAMERA
from homeassistant.const import CONF_NAME, CONF_MAC

from .sound_diffusion import DEFAULT_TUNING_PRESET, MAX_STATION_PRESET, tuner_device_id
from .video_door_entry import DEFAULT_CAMERA_WHERE, DEFAULT_ENTRANCE_ADDRESS

from .const import (
    CONF_PLATFORMS,
    CONF_WHO,
    CONF_WHERE,
    CONF_BUS_INTERFACE,
    CONF_ENTITIES,
    CONF_ENTITY_NAME,
    CONF_ICON,
    CONF_ICON_ON,
    CONF_ZONE,
    CONF_SOURCE,
    CONF_RADIO_STATIONS,
    CONF_TUNING_PRESET,
    CONF_FAN_SUPPORT,
    CONF_MANUFACTURER,
    CONF_DEVICE_MODEL,
    CONF_DEVICE_CLASS,
    CONF_DIMMABLE,
    CONF_ADVANCED_SHUTTER,
    CONF_INVERTED,
    CONF_HEATING_SUPPORT,
    CONF_COOLING_SUPPORT,
    CONF_STANDALONE,
    CONF_CENTRAL,
    CONF_VIDEO_DOOR_ENTRY,
    CONF_ENTRANCE_ADDRESS,
    CONF_LOCK_ADDRESS,
    CONF_CAMERA_WHERE,
    CONF_CAMERA_PASSWORD,
    CONF_CAMERA_HOST,
    CONF_CALL_TIMEOUT,
    CONF_VERIFY_SSL,
)


def format_mac(address: str) -> str:
    mac = re.sub("[.:-]", "", address).upper()
    mac = "".join(mac.split())
    if len(mac) != 12 or not mac.isalnum() or re.search("[G-Z]", mac) is not None:
        return None
    return ha_format_mac(mac)


class MacAddress(object):
    def __init__(self, msg=None):
        self.msg = msg

    def __call__(self, v):
        v = format_mac(v)
        if v is None:
            raise Invalid("Invalid MAC address")
        return format_mac(v)

    def __repr__(self):
        return "MacAddress(%s, msg=%r)" % ("String", self.msg)


class General(object):
    def __init__(self, msg=None):
        self.msg = msg

    def __call__(self, v):
        if type(v) == str and v == "0":
            return v
        else:
            raise Invalid(f"Invalid General WHERE {v}, it must be 0.")

    def __repr__(self):
        return "Where(%s, msg=%r)" % ("String", self.msg)


class Area(object):
    def __init__(self, msg=None):
        self.msg = msg

    def __call__(self, v):
        if type(v) == str and v in ["00", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10"]:
            return v
        else:
            raise Invalid(f"Invalid Area WHERE {v}, it must be a string in [00, 1-9, 10].")

    def __repr__(self):
        return "Where(%s, msg=%r)" % ("String", self.msg)


class Group(object):
    def __init__(self, msg=None):
        self.msg = msg

    def __call__(self, v):
        if type(v) == str and v.startswith("#") and v[1:].isdigit() and int(v[1:]) >= 1 and int(v[1:]) <= 255:
            return f"#{int(v[1:])}"
        else:
            raise Invalid(f"Invalid Group WHERE {v}, it must be a string like '#[1-255]'.")

    def __repr__(self):
        return "Where(%s, msg=%r)" % ("String", self.msg)


class PointToPoint(object):
    def __init__(self, msg=None):
        self.msg = msg

    def __call__(self, v):
        if type(v) == str and v.isdigit():
            _length = len(v)
            if _length == 2 or _length == 4:
                _a = v[0 : _length // 2]
                _pl = v[_length // 2 :]
                if int(_a) >= 0 and int(_a) <= 10 and int(_pl) >= 0 and int(_pl) <= 15:
                    return f"{_a}{_pl}"
                else:
                    raise Invalid(f"Invalid WHERE {v}, A must be [0-10] and PL must be [0-15].")
            else:
                raise Invalid(f"Invalid WHERE {v} length, it must be a string of 2 or 4 digits.")
        else:
            raise Invalid(f"Invalid WHERE {v}, it must be a string of 2 or 4 digits.")

    def __repr__(self):
        return "Where(%s, msg=%r)" % ("String", self.msg)


class SpecialWhere(object):
    def __init__(self, msg=None):
        self.msg = msg

    def __call__(self, v):
        if type(v) == str and v.isdigit():
            return v
        else:
            raise Invalid(f"Invalid WHERE {v}, it must be a string of digits.")

    def __repr__(self):
        return "Where(%s, msg=%r)" % ("String", self.msg)


class Amplifier(object):
    """Sound diffusion amplifier WHERE, `3#<area>#<point>`.

    The leading `3` is mandatory: a short `<area>#<point>` form would be too easy
    to confuse with the point-to-point WHERE of the other platforms.
    """

    def __call__(self, v):
        if type(v) == str:
            _parts = v.split("#")
            if len(_parts) == 3 and _parts[0] == "3" and _parts[1].isdigit() and _parts[2].isdigit():
                _area, _point = int(_parts[1]), int(_parts[2])
                if 1 <= _area <= 9 and 1 <= _point <= 9:
                    return f"3#{_area}#{_point}"
        raise Invalid(f"Invalid Sound Diffusion WHERE {v}, it must be a string like '3#<area>#<point>' with area and point in [1-9].")

    def __repr__(self):
        return "Amplifier()"


class RadioStations(object):
    """Station table override: `{"106.0": "SUD RADIO"}`, keyed by frequency in MHz.

    Frequencies are rekeyed to hundredths of MHz, the unit the bus uses and the
    one `sound_diffusion.station_name` matches against.

    Rekeying is lossy — `106`, `106.0` and `106.004` all land on 10600 — so two
    keys reaching the same one are refused rather than silently collapsed into
    whichever came last in the file.
    """

    def __call__(self, v):
        if not isinstance(v, dict):
            raise Invalid(f"Invalid radio stations table {v}, it must be a mapping of frequencies in MHz to station names.")
        _table = {}
        _written_by = {}
        for _frequency, _name in v.items():
            try:
                _key = int(round(float(_frequency) * 100))
            except (TypeError, ValueError):
                raise Invalid(f"Invalid radio station frequency {_frequency}, it must be a frequency in MHz like '106.0'.") from None
            if _key in _table:
                raise Invalid(
                    f"Invalid radio stations table, `{_written_by[_key]}` and `{_frequency}` are the same frequency "
                    f"({_key / 100} MHz) and only one of them would be kept."
                )
            _written_by[_key] = _frequency
            _table[_key] = str(_name)
        return _table

    def __repr__(self):
        return "RadioStations()"


class BusInterface(object):
    def __init__(self, msg=None):
        self.msg = msg

    def __call__(self, v):
        if type(v) == str and v.isdigit() and len(v) == 2:
            if int(v) > 15:
                raise Invalid(f"Invalid Bus Interface number {v}, it must be between 00 and 15.")
        elif v is not None:
            raise Invalid(f"Invalid Bus Interface number {v}, it must be a string of 2 digits.")
        return v

    def __repr__(self):
        return "BusInterface(%s, msg=%r)" % ("String", self.msg)


#: Keys of a gateway that configure the gateway itself rather than a platform.
#: `tuning_preset` carries a default, so it is present on every gateway, media
#: player or not: forgetting it here would break installations that have none.
#: `video_door_entry` is not a platform either — it is expanded below into the
#: `event`, `button`, `binary_sensor` and `camera` devices of its panels.
GATEWAY_OPTIONS = (CONF_RADIO_STATIONS, CONF_TUNING_PRESET, CONF_VIDEO_DOOR_ENTRY)


class MyHomeConfigSchema(Schema):
    def __call__(self, data):
        data = super().__call__(data)
        _rekeyed_data = {}
        for gateway in data:
            _rekeyed_data[data[gateway][CONF_MAC]] = {}
            _rekeyed_data[data[gateway][CONF_MAC]][CONF_PLATFORMS] = {}
            for platform in data[gateway]:
                if platform == CONF_MAC:
                    continue
                if platform in GATEWAY_OPTIONS:
                    # A gateway wide option, not a platform: `__init__.py` forwards
                    # every key of CONF_PLATFORMS to `async_forward_entry_setups`,
                    # and would try to set up a platform named after the option.
                    _rekeyed_data[data[gateway][CONF_MAC]][platform] = data[gateway][platform]
                    continue
                _rekeyed_data[data[gateway][CONF_MAC]][CONF_PLATFORMS][platform] = data[gateway][platform]

            if (
                (LIGHT in _rekeyed_data[data[gateway][CONF_MAC]][CONF_PLATFORMS])
                or (SWITCH in _rekeyed_data[data[gateway][CONF_MAC]][CONF_PLATFORMS])
                or (COVER in _rekeyed_data[data[gateway][CONF_MAC]][CONF_PLATFORMS])
            ):
                _rekeyed_data[data[gateway][CONF_MAC]][CONF_PLATFORMS][BUTTON] = {}
                if LIGHT in _rekeyed_data[data[gateway][CONF_MAC]][CONF_PLATFORMS]:
                    for key, value in _rekeyed_data[data[gateway][CONF_MAC]][CONF_PLATFORMS][LIGHT].items():
                        if not value[CONF_WHERE].startswith("#"):
                            _rekeyed_data[data[gateway][CONF_MAC]][CONF_PLATFORMS][BUTTON][key] = value
                if SWITCH in _rekeyed_data[data[gateway][CONF_MAC]][CONF_PLATFORMS]:
                    for key, value in _rekeyed_data[data[gateway][CONF_MAC]][CONF_PLATFORMS][SWITCH].items():
                        if not value[CONF_WHERE].startswith("#"):
                            _rekeyed_data[data[gateway][CONF_MAC]][CONF_PLATFORMS][BUTTON][key] = value
                if COVER in _rekeyed_data[data[gateway][CONF_MAC]][CONF_PLATFORMS]:
                    for key, value in _rekeyed_data[data[gateway][CONF_MAC]][CONF_PLATFORMS][COVER].items():
                        if not value[CONF_WHERE].startswith("#"):
                            _rekeyed_data[data[gateway][CONF_MAC]][CONF_PLATFORMS][BUTTON][key] = value

            _add_tuner_devices(_rekeyed_data[data[gateway][CONF_MAC]][CONF_PLATFORMS])
            _add_video_door_entry_devices(
                _rekeyed_data[data[gateway][CONF_MAC]][CONF_PLATFORMS],
                _rekeyed_data[data[gateway][CONF_MAC]].get(CONF_VIDEO_DOOR_ENTRY),
            )

        return _rekeyed_data


def _add_tuner_devices(platforms: dict) -> None:
    """Derive one tuner device per source the configured amplifiers listen to.

    Nothing declares a tuner in the configuration file: it is the box behind the
    amplifiers, and the `source` option of each of them names it. So the devices
    are built here, which is also what gets `number`, `button` and `select` into
    `CONF_PLATFORMS` — the keys `__init__.py` forwards to
    `async_forward_entry_setups` and unloads again.

    A device dict per platform rather than one shared between the three:
    `button.py` deletes its own on unload, and it must not empty the `number`
    platform on its way out.
    """
    if MEDIA_PLAYER not in platforms:
        return

    _sources = sorted({_amplifier[CONF_SOURCE] for _amplifier in platforms[MEDIA_PLAYER].values()})
    platforms.setdefault(NUMBER, {})
    platforms.setdefault(BUTTON, {})
    platforms.setdefault(SELECT, {})

    for _source in _sources:
        # One source is the common case, and "Tuner FM" reads better than
        # "Tuner FM 1" in front of the single tuner of a house.
        _name = "Tuner FM" if len(_sources) == 1 else f"Tuner FM {_source}"
        for _platform in (NUMBER, BUTTON, SELECT):
            platforms[_platform][tuner_device_id(_source)] = {
                CONF_WHO: "22",
                CONF_WHERE: f"2#{_source}",
                CONF_SOURCE: _source,
                CONF_NAME: _name,
                CONF_ENTITY_NAME: None,
                CONF_ICON: None,
                CONF_MANUFACTURER: None,
                CONF_DEVICE_MODEL: None,
                CONF_ENTITIES: {},
            }


#: Platforms an entrance panel is expanded into. `camera` is added per panel,
#: only when that panel carries a camera password.
VIDEO_DOOR_ENTRY_PLATFORMS = (EVENT, BUTTON, BINARY_SENSOR)


def _add_video_door_entry_devices(platforms: dict, video_door_entry) -> None:
    """Expand each configured entrance panel into its standard-platform devices.

    Nothing under `video_door_entry:` is a Home Assistant platform; a panel is a
    doorbell `event`, an "Open" `button`, a "Call in progress" `binary_sensor`
    and — when it has a camera password — a `camera`. They are built here, which
    is what gets those platforms into `CONF_PLATFORMS`, the keys `__init__.py`
    forwards to `async_forward_entry_setups` and prunes the registry against.

    A fresh device dict per platform, like `_add_tuner_devices`: `button.py`
    empties its own on unload and must not take the others down with it.
    """
    if not video_door_entry:
        return

    for _platform in VIDEO_DOOR_ENTRY_PLATFORMS:
        platforms.setdefault(_platform, {})

    for _panel in video_door_entry.values():
        _entrance = _panel[CONF_ENTRANCE_ADDRESS]
        _lock = _panel[CONF_LOCK_ADDRESS] if _panel.get(CONF_LOCK_ADDRESS) is not None else _entrance
        _password = _panel.get(CONF_CAMERA_PASSWORD)
        # `8-<entrance address>`, so a second panel on the same bus keys apart.
        _device_id = f"8-{_entrance}"

        def _device() -> dict:
            return {
                CONF_WHO: "8",
                CONF_WHERE: str(_entrance),
                CONF_NAME: _panel[CONF_NAME],
                CONF_ENTRANCE_ADDRESS: _entrance,
                CONF_LOCK_ADDRESS: _lock,
                CONF_CAMERA_WHERE: _panel[CONF_CAMERA_WHERE],
                CONF_CAMERA_PASSWORD: _password,
                CONF_CAMERA_HOST: _panel.get(CONF_CAMERA_HOST),
                CONF_VERIFY_SSL: _panel[CONF_VERIFY_SSL],
                CONF_CALL_TIMEOUT: _panel[CONF_CALL_TIMEOUT],
                CONF_ENTITY_NAME: _panel.get(CONF_ENTITY_NAME),
                CONF_ICON: _panel.get(CONF_ICON),
                # `binary_sensor.async_setup_entry` reads this key unconditionally.
                CONF_DEVICE_CLASS: None,
                CONF_MANUFACTURER: _panel[CONF_MANUFACTURER],
                CONF_DEVICE_MODEL: _panel.get(CONF_DEVICE_MODEL),
                CONF_ENTITIES: {},
            }

        for _platform in VIDEO_DOOR_ENTRY_PLATFORMS:
            platforms[_platform][_device_id] = _device()
        if _password:
            platforms.setdefault(CAMERA, {})
            platforms[CAMERA][_device_id] = _device()


class MyHomeDeviceSchema(Schema):
    def __call__(self, data):
        data = super().__call__(data)
        _rekeyed_data = {}

        for device in data:
            data[device][CONF_ENTITIES] = {}
            if CONF_WHERE in data[device]:
                _new_key = (
                    f"{data[device][CONF_WHO]}-{data[device][CONF_WHERE]}#4#{data[device][CONF_BUS_INTERFACE]}"
                    if CONF_BUS_INTERFACE in data[device] and data[device][CONF_BUS_INTERFACE] is not None
                    else f"{data[device][CONF_WHO]}-{data[device][CONF_WHERE]}"
                )
                _rekeyed_data[_new_key] = data[device]
            elif CONF_ZONE in data[device]:
                _new_key = f"{data[device][CONF_WHO]}-{data[device][CONF_ZONE]}"
                data[device][CONF_ZONE] = f"#0#{data[device][CONF_ZONE]}" if data[device][CONF_CENTRAL] and data[device][CONF_ZONE] != "#0" else data[device][CONF_ZONE]
                data[device][CONF_NAME] = (
                    data[device][CONF_NAME] if CONF_NAME in data[device] else "Central unit" if data[device][CONF_ZONE].startswith("#0") else f"Zone {data[device][CONF_ZONE]}"
                )
                _rekeyed_data[_new_key] = data[device]
            if CONF_DEVICE_MODEL not in data[device]:
                data[device][CONF_DEVICE_MODEL] = None
            if CONF_ICON not in data[device]:
                data[device][CONF_ICON] = None
            if CONF_ICON_ON not in data[device]:
                data[device][CONF_ICON_ON] = None
            if CONF_ENTITY_NAME not in data[device]:
                data[device][CONF_ENTITY_NAME] = None

        return _rekeyed_data


class MyHomeSensorSchema(Schema):
    def __call__(self, data):
        data = super().__call__(data)
        _rekeyed_data = {}

        for device in data:
            data[device][CONF_ENTITIES] = {}
            if CONF_DEVICE_CLASS in data[device]:
                if data[device][CONF_DEVICE_CLASS] in [
                    SensorDeviceClass.POWER,
                    SensorDeviceClass.ENERGY,
                ]:
                    if CONF_WHO not in data[device]:
                        data[device][CONF_WHO] = "18"
                    elif data[device][CONF_WHO] != "18":
                        raise Invalid("invalid sensor class for selected who")
                    data[device][CONF_ENTITIES][f"daily-{SensorDeviceClass.ENERGY}"] = {}
                    data[device][CONF_ENTITIES][f"monthly-{SensorDeviceClass.ENERGY}"] = {}
                    data[device][CONF_ENTITIES][f"total-{SensorDeviceClass.ENERGY}"] = {}
                    if data[device][CONF_DEVICE_CLASS] in [SensorDeviceClass.POWER]:
                        data[device][CONF_ENTITIES][f"{SensorDeviceClass.POWER}"] = {}
                elif data[device][CONF_DEVICE_CLASS] in [SensorDeviceClass.TEMPERATURE]:
                    if CONF_WHO not in data[device]:
                        data[device][CONF_WHO] = "4"
                    elif data[device][CONF_WHO] != "4":
                        raise Invalid("invalid sensor class for selected who")
                elif data[device][CONF_DEVICE_CLASS] in [SensorDeviceClass.ILLUMINANCE]:
                    if CONF_WHO not in data[device]:
                        data[device][CONF_WHO] = "1"
                    elif data[device][CONF_WHO] != "1":
                        raise Invalid("invalid sensor class for selected who")
            if CONF_WHERE in data[device]:
                _new_key = (
                    f"{data[device][CONF_WHO]}-{data[device][CONF_WHERE]}#4#{data[device][CONF_BUS_INTERFACE]}"
                    if CONF_BUS_INTERFACE in data[device] and data[device][CONF_BUS_INTERFACE] is not None
                    else f"{data[device][CONF_WHO]}-{data[device][CONF_WHERE]}"
                )
                _rekeyed_data[_new_key] = data[device]
            if CONF_DEVICE_MODEL not in data[device]:
                data[device][CONF_DEVICE_MODEL] = None

        return _rekeyed_data


light_schema = MyHomeDeviceSchema(
    {
        Required(str): {
            Optional(CONF_WHO, default="1"): "1",
            Required(CONF_WHERE): All(
                Coerce(str), Any(General(), Area(), Group(), PointToPoint(), msg="Invalid <WHERE>, expecting a valid General, Area, Group or Point-to-Point <WHERE>")
            ),
            Optional(CONF_BUS_INTERFACE): All(Coerce(str), BusInterface()),
            Required(CONF_NAME): str,
            Optional(CONF_ENTITY_NAME): str,
            Optional(CONF_ICON): str,
            Optional(CONF_ICON_ON): str,
            Optional(CONF_DIMMABLE, default=False): Boolean(),
            Optional(CONF_MANUFACTURER, default="BTicino S.p.A."): str,
            Optional(CONF_DEVICE_MODEL): Coerce(str),
        }
    }
)

switch_schema = MyHomeDeviceSchema(
    {
        Required(str): {
            Optional(CONF_WHO, default="1"): "1",
            Required(CONF_WHERE): All(
                Coerce(str), Any(General(), Area(), Group(), PointToPoint(), msg="Invalid <WHERE>, expecting a valid General, Area, Group or Point-to-Point <WHERE>")
            ),
            Optional(CONF_BUS_INTERFACE): All(Coerce(str), BusInterface()),
            Required(CONF_NAME): str,
            Optional(CONF_ENTITY_NAME): str,
            Optional(CONF_ICON): str,
            Optional(CONF_ICON_ON): str,
            Optional(CONF_DEVICE_CLASS, default=SwitchDeviceClass.SWITCH): In(
                [
                    SwitchDeviceClass.OUTLET,
                    SwitchDeviceClass.SWITCH,
                ]
            ),
            Optional(CONF_MANUFACTURER, default="BTicino S.p.A."): str,
            Optional(CONF_DEVICE_MODEL): Coerce(str),
        }
    }
)

cover_schema = MyHomeDeviceSchema(
    {
        Required(str): {
            Optional(CONF_WHO, default="2"): "2",
            Required(CONF_WHERE): All(
                Coerce(str), Any(General(), Area(), Group(), PointToPoint(), msg="Invalid <WHERE>, expecting a valid General, Area, Group or Point-to-Point <WHERE>")
            ),
            Optional(CONF_BUS_INTERFACE): All(Coerce(str), BusInterface()),
            Required(CONF_NAME): str,
            Optional(CONF_ENTITY_NAME): str,
            Optional(CONF_ADVANCED_SHUTTER, default=False): Boolean(),
            Optional(CONF_MANUFACTURER, default="BTicino S.p.A."): str,
            Optional(CONF_DEVICE_MODEL): Coerce(str),
        }
    }
)

binary_sensor_schema = MyHomeDeviceSchema(
    {
        Required(str): {
            Optional(CONF_WHO, default="25"): In(["1", "9", "25"]),
            Required(CONF_WHERE): All(Coerce(str), SpecialWhere()),
            Required(CONF_NAME): str,
            Optional(CONF_ENTITY_NAME): str,
            Optional(CONF_INVERTED, default=False): Boolean(),
            Optional(CONF_DEVICE_CLASS): In(
                [
                    BinarySensorDeviceClass.BATTERY,
                    BinarySensorDeviceClass.BATTERY_CHARGING,
                    BinarySensorDeviceClass.COLD,
                    BinarySensorDeviceClass.CONNECTIVITY,
                    BinarySensorDeviceClass.DOOR,
                    BinarySensorDeviceClass.GARAGE_DOOR,
                    BinarySensorDeviceClass.GAS,
                    BinarySensorDeviceClass.HEAT,
                    BinarySensorDeviceClass.LIGHT,
                    BinarySensorDeviceClass.LOCK,
                    BinarySensorDeviceClass.MOISTURE,
                    BinarySensorDeviceClass.MOTION,
                    BinarySensorDeviceClass.MOVING,
                    BinarySensorDeviceClass.OCCUPANCY,
                    BinarySensorDeviceClass.OPENING,
                    BinarySensorDeviceClass.PLUG,
                    BinarySensorDeviceClass.POWER,
                    BinarySensorDeviceClass.PRESENCE,
                    BinarySensorDeviceClass.PROBLEM,
                    BinarySensorDeviceClass.SAFETY,
                    BinarySensorDeviceClass.SMOKE,
                    BinarySensorDeviceClass.SOUND,
                    BinarySensorDeviceClass.VIBRATION,
                    BinarySensorDeviceClass.WINDOW,
                ]
            ),
            Optional(CONF_MANUFACTURER, default="BTicino S.p.A."): str,
            Optional(CONF_DEVICE_MODEL): Coerce(str),
        }
    }
)

sensor_schema = MyHomeSensorSchema(
    {
        Required(str): {
            Optional(CONF_WHO): In(["1", "4", "18"]),
            Required(CONF_WHERE): All(Coerce(str), SpecialWhere()),
            Required(CONF_NAME): str,
            Required(CONF_DEVICE_CLASS): In(
                [
                    SensorDeviceClass.TEMPERATURE,
                    SensorDeviceClass.POWER,
                    SensorDeviceClass.ENERGY,
                    SensorDeviceClass.ILLUMINANCE,
                ]
            ),
            Optional(CONF_MANUFACTURER, default="BTicino S.p.A."): str,
            Optional(CONF_DEVICE_MODEL): Coerce(str),
        }
    }
)

climate_schema = MyHomeDeviceSchema(
    {
        Required(str): {
            Optional(CONF_WHO, default="4"): "4",
            Optional(CONF_ZONE, default="#0"): Coerce(str),
            Optional(CONF_NAME): str,
            Optional(CONF_HEATING_SUPPORT, default=True): Boolean(),
            Optional(CONF_COOLING_SUPPORT, default=False): Boolean(),
            Optional(CONF_FAN_SUPPORT, default=False): Boolean(),
            Optional(CONF_STANDALONE, default=False): Boolean(),
            Optional(CONF_CENTRAL, default=False): Boolean(),
            Optional(CONF_MANUFACTURER, default="BTicino S.p.A."): str,
            Optional(CONF_DEVICE_MODEL): Coerce(str),
        }
    }
)

media_player_schema = MyHomeDeviceSchema(
    {
        Required(str): {
            Optional(CONF_WHO, default="22"): "22",
            Required(CONF_WHERE): All(Coerce(str), Amplifier(), msg="Invalid <WHERE>, expecting a valid Sound Diffusion amplifier <WHERE>"),
            Required(CONF_NAME): str,
            Optional(CONF_ENTITY_NAME): str,
            Optional(CONF_SOURCE, default=1): All(Coerce(int), Range(min=1, max=4)),
            Optional(CONF_ICON): str,
            Optional(CONF_MANUFACTURER, default="BTicino S.p.A."): str,
            Optional(CONF_DEVICE_MODEL): Coerce(str),
        }
    }
)

video_door_entry_schema = Schema(
    {
        Required(str): {
            Required(CONF_NAME): str,
            Optional(CONF_ENTRANCE_ADDRESS, default=DEFAULT_ENTRANCE_ADDRESS): All(Coerce(int), Range(min=0)),
            # Defaults to the entrance address; resolved when the device is built.
            Optional(CONF_LOCK_ADDRESS): All(Coerce(int), Range(min=0)),
            Optional(CONF_CAMERA_WHERE, default=DEFAULT_CAMERA_WHERE): All(Coerce(int), Range(min=0)),
            # In clear, or the MD5 hash of the OPEN bus password: `telecamera.php`
            # takes whatever the panel's own web page sends. Kept out of the code.
            Optional(CONF_CAMERA_PASSWORD): Coerce(str),
            Optional(CONF_CAMERA_HOST): str,
            # The panel serves the snapshot over HTTPS with a self-signed cert.
            Optional(CONF_VERIFY_SSL, default=False): Boolean(),
            Optional(CONF_CALL_TIMEOUT, default=60): All(Coerce(int), Range(min=1)),
            Optional(CONF_ENTITY_NAME): str,
            Optional(CONF_ICON): str,
            Optional(CONF_MANUFACTURER, default="BTicino S.p.A."): str,
            Optional(CONF_DEVICE_MODEL): Coerce(str),
        }
    }
)

gateway_schema = Schema(
    {
        Required(CONF_MAC): MacAddress(),
        Optional(LIGHT): light_schema,
        Optional(SWITCH): switch_schema,
        Optional(COVER): cover_schema,
        Optional(BINARY_SENSOR): binary_sensor_schema,
        Optional(SENSOR): sensor_schema,
        Optional(CLIMATE): climate_schema,
        Optional(MEDIA_PLAYER): media_player_schema,
        Optional(CONF_VIDEO_DOOR_ENTRY): video_door_entry_schema,
        Optional(CONF_RADIO_STATIONS): RadioStations(),
        Optional(CONF_TUNING_PRESET, default=DEFAULT_TUNING_PRESET): All(Coerce(int), Range(min=1, max=MAX_STATION_PRESET)),
    }
)

config_schema = MyHomeConfigSchema({Required(str): gateway_schema})
