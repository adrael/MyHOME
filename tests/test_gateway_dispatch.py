"""End to end dispatch: raw bus frames in, `media_player` entity states out.

Home Assistant is stubbed (see `ha_stubs`), everything else is the real code:
`gateway.handle_sound_diffusion`, the WHO=22 parser and `MyHOMEAmplifier`.
"""

import asyncio
import os
import sys
import types

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ha_stubs  # noqa: E402

const = ha_stubs.load("const")
sound_diffusion = ha_stubs.load("sound_diffusion")
gateway = ha_stubs.load("gateway")
media_player = ha_stubs.load("media_player")

DOMAIN = const.DOMAIN
MAC = "00:03:50:11:22:33"
PLAYING = ha_stubs.MediaPlayerState.PLAYING
OFF = ha_stubs.MediaPlayerState.OFF

#: The installation the frames below were captured on, minus the disabled tablet.
AMPLIFIERS = [
    (7, 1, "Radio Cuisine"),
    (2, 1, "Radio Suite"),
    (2, 2, "Radio Suite SDB"),
    (3, 1, "Radio Bureau Julie"),
    (3, 2, "Radio Bureau Julie SDB"),
    (4, 1, "Radio Gym"),
    (5, 1, "Radio Chambre Ami"),
    (5, 2, "Radio Chambre Ami SDB"),
    (6, 1, "Radio Bureau Raph"),
    (6, 2, "Radio Bureau Raph SDB"),
    (1, 1, "Radio Tablette"),
]

#: Monitor session of the F454, 2026-08-25, replayed verbatim.
CAPTURE = [
    "*22*1#4#2*3#2#2##",
    "*#22*3#2#2*12*1*4##",
    "*16*3*22##",
    "*16*3*121##",
    "*22*1#4#2*2#1##",
    "*22*2#4#2*5#2#1##",
    "*#22*3#2#2*1##",
    "*#16*22*1*18##",
    "*#22*3#2#2*1*18##",
    "*22*3#1*3#2#2##",
    "*#22*3#2#2*1*19##",
    "*22*4#1*3#2#2##",
    "*#22*3#2#2*1*18##",
    "*22*9*5#3#2#2##",
    "*#16*101*6*0*106000##",
    "*#22*5#2#1*5*1*10600##",
    "*#22*5#2#1*11*1*10600*14##",
    "*#16*101*7*0*14##",
    "*#22*2#1*6*14##",
    "*22*1#4#2*3#2#1##",
    "*#22*3#2#1*12*1*4##",
    "*22*2#4#2*5#2#1##",
    "*#22*3#2#1*1*17##",
    "*22*0#4#0*3#2#1##",
    "*16*13*21##",
    "*#22*3#2#1*12*0*10##",
]


class FakeGateway(gateway.MyHOMEGatewayHandler):
    """The real handler, without the config entry and the sockets."""

    def __init__(self, hass):
        self.hass = hass
        self.is_connected = True
        self.gateway = types.SimpleNamespace(serial=MAC, log_id="[test]", host="192.168.1.17")
        self.sent = []
        self.status_requests = []

    async def send(self, message):
        self.sent.append(str(message))

    async def send_status_request(self, message):
        self.status_requests.append(str(message))


class Installation:
    """A stubbed `hass` holding one gateway and its amplifier entities."""

    def __init__(self, amplifiers=AMPLIFIERS, source=1, radio_stations=None):
        self.data = {DOMAIN: {MAC: {const.CONF_PLATFORMS: {}}}}
        if radio_stations is not None:
            self.data[DOMAIN][MAC][const.CONF_RADIO_STATIONS] = radio_stations

        self.handler = FakeGateway(self)
        self.devices = {}
        self.entities = {}

        for _area, _point, _name in amplifiers:
            _device_id = sound_diffusion.amplifier_device_id(_area, _point)
            _source = source(_area, _point) if callable(source) else source
            self.devices[_device_id] = {
                const.CONF_WHO: "22",
                const.CONF_WHERE: f"3#{_area}#{_point}",
                "name": _name,
                const.CONF_ENTITY_NAME: None,
                const.CONF_ICON: None,
                const.CONF_SOURCE: _source,
                const.CONF_MANUFACTURER: "BTicino S.p.A.",
                const.CONF_DEVICE_MODEL: None,
                const.CONF_ENTITIES: {},
            }
        self.data[DOMAIN][MAC][const.CONF_PLATFORMS]["media_player"] = self.devices

        for _device_id, _device in self.devices.items():
            _entity = media_player.MyHOMEAmplifier(
                hass=self,
                name=_device["name"],
                entity_name=None,
                icon=None,
                device_id=_device_id,
                who="22",
                where=_device[const.CONF_WHERE],
                source=_device[const.CONF_SOURCE],
                manufacturer=_device[const.CONF_MANUFACTURER],
                model=None,
                gateway=self.handler,
            )
            _device[const.CONF_ENTITIES]["media_player"] = _entity
            self.entities[_device_id] = _entity

    def replay(self, frames):
        for _frame in frames:
            if _frame.startswith("*22*") or _frame.startswith("*#22*"):
                self.handler.handle_sound_diffusion(_frame)

    def entity(self, area, point):
        return self.entities[sound_diffusion.amplifier_device_id(area, point)]

    @property
    def tuner(self):
        return self.data[DOMAIN][MAC][const.CONF_SOUND_SOURCES]


@pytest.fixture(name="installation")
def installation_fixture():
    return Installation()


# --------------------------------------------------------------------------- #
# Replaying the capture
# --------------------------------------------------------------------------- #


def test_replaying_the_capture_leaves_the_expected_states(installation):
    installation.replay(CAPTURE)

    _suite_sdb = installation.entity(2, 2)
    assert _suite_sdb.state == PLAYING
    assert _suite_sdb._raw_volume == 18
    assert _suite_sdb.volume_level == pytest.approx(18 / 31)
    assert _suite_sdb.media_title == "106.0 MHz · SUD RADIO"
    assert _suite_sdb.media_channel == "SUD RADIO"
    assert _suite_sdb.media_content_type == ha_stubs.MediaType.CHANNEL

    # Turned on, volume reported, then turned off again by the wall command.
    _suite = installation.entity(2, 1)
    assert _suite.state == OFF
    assert _suite._raw_volume == 17
    assert _suite.media_title is None
    assert _suite.media_channel is None
    assert _suite.media_content_type is None

    # Never addressed: no state, but the tuner is shared all the same.
    _cuisine = installation.entity(7, 1)
    assert _cuisine.state is None
    assert _cuisine._raw_volume is None


def test_replaying_the_capture_fills_the_shared_tuner(installation):
    installation.replay(CAPTURE)
    assert installation.tuner[1]["frequency"] == 10600
    assert installation.tuner[1]["modulation"] == 1
    assert installation.tuner[1]["station"] == 14
    # Dead keys of the previous implementation must not come back.
    assert "is_on" not in installation.tuner[1]
    assert "mmtype" not in installation.tuner[1]
    assert "area" not in installation.tuner[1]


def test_presets_cycle_through_the_station_table(installation):
    installation.replay(CAPTURE)
    _cuisine = installation.entity(7, 1)
    _cuisine.handle_event(sound_diffusion.AmplifierState(area=7, point=1, is_on=True, mmtype=4))

    installation.handler.handle_sound_diffusion("*#22*5#2#1*11*1*9730*15##")
    assert _cuisine.media_title == "97.3 MHz · NOSTALGIE"
    assert _cuisine.extra_state_attributes["preset"] == 15

    installation.handler.handle_sound_diffusion("*#22*5#2#1*11*1*9430*1##")
    assert _cuisine.media_title == "94.3 MHz · EUROPE 2"
    assert _cuisine.extra_state_attributes["frequency_mhz"] == 94.3


# --------------------------------------------------------------------------- #
# Dispatch targeting
# --------------------------------------------------------------------------- #


def test_a_source_event_only_reaches_the_amplifiers_on_that_source():
    installation = Installation(source=lambda area, point: 1 if area == 2 else 2)
    for _entity in installation.entities.values():
        _entity.handle_event(sound_diffusion.AmplifierState(area=0, point=0, is_on=True, mmtype=4))
        _entity.written_states = 0

    installation.handler.handle_sound_diffusion("*#22*5#2#1*11*1*10600*14##")

    assert installation.entity(2, 1).written_states == 1
    assert installation.entity(2, 2).written_states == 1
    assert installation.entity(7, 1).written_states == 0
    assert installation.entity(7, 1).media_title is None

    installation.handler.handle_sound_diffusion("*#22*5#2#2*11*1*9730*15##")
    assert installation.entity(7, 1).media_title == "97.3 MHz · NOSTALGIE"
    assert installation.entity(2, 2).media_title == "106.0 MHz · SUD RADIO"


def test_an_amplifier_event_only_reaches_its_own_entity(installation):
    for _entity in installation.entities.values():
        _entity.written_states = 0

    installation.handler.handle_sound_diffusion("*#22*3#6#2*12*1*4##")

    assert installation.entity(6, 2).written_states == 1
    assert sum(_entity.written_states for _entity in installation.entities.values()) == 1


def test_an_area_command_reaches_the_amplifiers_of_that_area(installation):
    installation.replay(["*#22*3#5#1*12*1*4##", "*#22*3#5#2*12*1*4##", "*#22*3#7#1*12*1*4##"])

    installation.handler.handle_sound_diffusion("*22*0#4#0*4#5##")

    assert installation.entity(5, 1).state == OFF
    assert installation.entity(5, 2).state == OFF
    assert installation.entity(7, 1).state == PLAYING


def test_a_general_command_reaches_every_amplifier(installation):
    installation.handler.handle_sound_diffusion("*22*1#4#0*0##")
    assert all(_entity.state == PLAYING for _entity in installation.entities.values())

    installation.handler.handle_sound_diffusion("*22*0#4#0*0##")
    assert all(_entity.state == OFF for _entity in installation.entities.values())


def test_an_event_for_an_unconfigured_amplifier_is_ignored(installation):
    installation.handler.handle_sound_diffusion("*#22*3#9#9*12*1*4##")
    assert all(_entity.state is None for _entity in installation.entities.values())


@pytest.mark.parametrize(
    "raw",
    [
        "*#22*3#2#2*1##",  # valueless dimension request
        "*#22*3#2#2*#1*18##",  # echo of our own volume write
        "*#22*5#2#1*#11*1*10600*14##",  # echo of our own frequency write
        "*22*9*5#3#2#2##",  # station change requested from an amplifier
    ],
)
def test_frames_without_state_change_nothing(installation, raw):
    installation.handler.handle_sound_diffusion(raw)
    assert all(_entity.state is None for _entity in installation.entities.values())
    assert all(_entity.written_states == 0 for _entity in installation.entities.values())
    assert installation.data[DOMAIN][MAC].get(const.CONF_SOUND_SOURCES, {}).get(1, {}).get("frequency") is None


def test_dispatching_after_the_config_entry_was_unloaded_does_not_raise(installation):
    del installation.data[DOMAIN][MAC]
    installation.handler.handle_sound_diffusion("*#22*3#2#2*12*1*4##")


# --------------------------------------------------------------------------- #
# Entity behaviour
# --------------------------------------------------------------------------- #


def test_a_volume_out_of_range_is_clamped(installation):
    installation.handler.handle_sound_diffusion("*#22*3#2#2*1*99##")
    _entity = installation.entity(2, 2)
    assert _entity._raw_volume == 31
    assert _entity.volume_level == 1.0


def test_availability_follows_the_gateway_connection(installation):
    assert installation.entity(2, 2).available is True
    installation.handler.is_connected = False
    assert installation.entity(2, 2).available is False


def test_attributes_are_reduced_to_what_carries_a_value(installation):
    _entity = installation.entity(2, 2)
    assert _entity.extra_state_attributes == {"area": 2, "point": 2, "source_id": 1}

    installation.replay(CAPTURE)
    assert _entity.extra_state_attributes == {
        "area": 2,
        "point": 2,
        "source_id": 1,
        "frequency_mhz": 106.0,
        "station_name": "SUD RADIO",
        "preset": 14,
        "raw_volume": 18,
    }


def test_a_modulation_other_than_fm_is_reported_in_khz():
    installation = Installation(amplifiers=[(2, 2, "Radio")])
    installation.replay(["*#22*3#2#2*12*1*4##", "*#22*5#2#1*11*3*1080*4##"])
    _entity = installation.entity(2, 2)
    assert _entity.media_title == "1080 kHz"
    assert _entity.extra_state_attributes["modulation"] == 3


def test_the_gateway_station_table_overrides_the_built_in_one():
    installation = Installation(amplifiers=[(2, 2, "Radio")], radio_stations={10600: "MA RADIO"})
    installation.replay(["*#22*3#2#2*12*1*4##", "*#22*5#2#1*11*1*10600*14##"])
    assert installation.entity(2, 2).media_channel == "MA RADIO"

    installation.replay(["*#22*5#2#1*11*1*9730*15##"])
    assert installation.entity(2, 2).media_channel is None
    assert installation.entity(2, 2).media_title == "97.3 MHz"


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #


def test_turning_on_and_off_is_reflected_before_the_bus_answers(installation):
    _entity = installation.entity(2, 2)

    asyncio.run(_entity.async_turn_on())
    assert _entity.state == PLAYING
    assert _entity.written_states == 1
    assert installation.handler.sent == ["*22*1#4#2*3#2#2##"]

    asyncio.run(_entity.async_turn_off())
    assert _entity.state == OFF
    assert installation.handler.sent[-1] == "*22*0#4#0*3#2#2##"


def test_setting_a_volume_is_reflected_before_the_bus_answers(installation):
    _entity = installation.entity(2, 2)

    asyncio.run(_entity.async_set_volume_level(0.5))
    assert _entity._raw_volume == 16
    assert _entity.volume_level == pytest.approx(16 / 31)
    assert installation.handler.sent == ["*#22*3#2#2*#1*16##"]

    asyncio.run(_entity.async_set_volume_level(1.0))
    assert _entity._raw_volume == 31
    assert installation.handler.sent[-1] == "*#22*3#2#2*#1*31##"


def test_stepping_the_volume_moves_the_known_value(installation):
    _entity = installation.entity(2, 2)
    installation.handler.handle_sound_diffusion("*#22*3#2#2*1*18##")

    asyncio.run(_entity.async_volume_up())
    assert _entity._raw_volume == 19
    assert installation.handler.sent == ["*22*3#1*3#2#2##"]

    asyncio.run(_entity.async_volume_down())
    assert _entity._raw_volume == 18
    assert installation.handler.sent[-1] == "*22*4#1*3#2#2##"


def test_stepping_an_unknown_volume_only_sends(installation):
    _entity = installation.entity(2, 2)
    asyncio.run(_entity.async_volume_up())
    assert _entity._raw_volume is None
    assert installation.handler.sent == ["*22*3#1*3#2#2##"]


def test_next_and_previous_track_use_the_bus_observed_form(installation):
    _entity = installation.entity(2, 2)
    asyncio.run(_entity.async_media_next_track())
    asyncio.run(_entity.async_media_previous_track())
    assert installation.handler.sent == ["*22*9*5#3#2#2##", "*22*10*5#3#2#2##"]


def test_the_tuner_is_only_asked_for_once_per_gateway(installation):
    """Eleven amplifiers, one tuner: 11 x 2 amplifier requests plus one tuner one."""

    async def _update_every_amplifier():
        for _entity in installation.entities.values():
            await _entity.async_update()

    asyncio.run(_update_every_amplifier())

    _requests = installation.handler.status_requests
    assert len(_requests) == 23
    assert _requests.count("*#22*5#2#1*11##") == 1
    assert _requests.count("*#22*3#2#2*12##") == 1
    assert _requests.count("*#22*3#2#2*1##") == 1


def test_each_source_is_asked_for_once():
    installation = Installation(source=lambda area, point: 1 if area == 2 else 2)

    async def _update_every_amplifier():
        for _entity in installation.entities.values():
            await _entity.async_update()

    asyncio.run(_update_every_amplifier())

    _requests = installation.handler.status_requests
    assert _requests.count("*#22*5#2#1*11##") == 1
    assert _requests.count("*#22*5#2#2*11##") == 1
    assert len(_requests) == 24


def test_an_entity_is_unavailable_until_a_frame_comes_back(installation):
    """Entities are added before the listener connects, and nothing re-writes them.

    `async_forward_entry_setups` runs before the listening worker is created, so
    every amplifier writes "unavailable" on its first state write. Only an
    inbound WHO=22 frame clears it: connecting the listener is not, by itself,
    something the entities are told about.
    """
    _entity = installation.entity(2, 2)
    installation.handler.is_connected = False

    asyncio.run(_entity.async_update())
    _written = _entity.written_states

    installation.handler.is_connected = True
    assert _entity.written_states == _written, "connecting does not refresh the entities"
    assert _entity.available is True

    # In practice the state comes back with the answer to the status request.
    assert installation.handler.status_requests[0] == "*#22*3#2#2*12##"
    installation.handler.handle_sound_diffusion("*#22*3#2#2*12*1*4##")
    assert _entity.written_states == _written + 1
    assert _entity.state == PLAYING
