"""End to end dispatch: raw bus frames in, `media_player` entity states out.

Home Assistant is stubbed (see `ha_stubs`), everything else is the real code:
`gateway.handle_sound_diffusion`, the WHO=22 parser and `MyHOMEAmplifier`.
"""

import asyncio
import os
import sys
import types

import pytest
import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ha_stubs  # noqa: E402

const = ha_stubs.load("const")
sound_diffusion = ha_stubs.load("sound_diffusion")
validate = ha_stubs.load("validate")
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
        await asyncio.sleep(0)
        self.sent.append(str(message))

    async def send_status_request(self, message):
        # Yielding here is what makes the interleaving of `async_update` visible.
        await asyncio.sleep(0)
        self.status_requests.append(str(message))


def configuration_file(amplifiers=None, source=1, radio_stations=None) -> str:
    """The `myhome.yaml` such an installation would hold."""
    _lines = ["villa:", f'  mac: "{MAC}"', "  media_player:"]
    for _area, _point, _name in amplifiers if amplifiers is not None else AMPLIFIERS:
        _source = source(_area, _point) if callable(source) else source
        _lines.append(f'    ampli_{_area}_{_point}: {{ where: "3#{_area}#{_point}", name: "{_name}", source: {_source} }}')
    if radio_stations is not None:
        _lines.append("  radio_stations:" + (" {}" if not radio_stations else ""))
        for _frequency, _name in radio_stations.items():
            _lines.append(f'    "{_frequency}": "{_name}"')
    return "\n".join(_lines) + "\n"


class Installation:
    """A stubbed `hass` holding one gateway and its amplifier entities.

    The data structure comes out of the real `validate.config_schema`, so the
    tests cannot drift away from what the integration is actually handed.
    """

    def __init__(self, amplifiers=AMPLIFIERS, source=1, radio_stations=None):
        self.data = {DOMAIN: validate.config_schema(yaml.safe_load(configuration_file(amplifiers, source, radio_stations)))}

        self.handler = FakeGateway(self)
        self.devices = self.data[DOMAIN][MAC][const.CONF_PLATFORMS]["media_player"]
        self.entities = {}

        for _device_id, _device in self.devices.items():
            _entity = media_player.MyHOMEAmplifier(
                hass=self,
                name=_device["name"],
                entity_name=_device[const.CONF_ENTITY_NAME],
                icon=_device[const.CONF_ICON],
                device_id=_device_id,
                who=_device[const.CONF_WHO],
                where=_device[const.CONF_WHERE],
                source=_device[const.CONF_SOURCE],
                manufacturer=_device[const.CONF_MANUFACTURER],
                model=_device[const.CONF_DEVICE_MODEL],
                gateway=self.handler,
            )
            # What `async_added_to_hass` does: register the entity and let it
            # write states.
            _entity.hass = self
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


def test_an_area_command_matches_the_area_as_a_number(installation):
    """`3#1#1` belongs to area 1, not to area 11."""
    installation.replay(["*#22*3#1#1*12*1*4##"])

    installation.handler.handle_sound_diffusion("*22*0#4#0*4#11##")

    assert installation.entity(1, 1).state == PLAYING


def test_a_general_command_is_ignored(installation):
    """WHERE `0` is not a sound diffusion address, so nothing is turned off."""
    installation.replay(["*#22*3#5#1*12*1*4##"])

    installation.handler.handle_sound_diffusion("*22*0#4#0*0##")

    assert installation.entity(5, 1).state == PLAYING


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


def test_dispatching_while_the_config_entry_is_being_reloaded_does_not_raise(installation):
    """`async_setup_entry` creates the gateway key before it fills it."""
    installation.data[DOMAIN][MAC] = {}
    installation.handler.handle_sound_diffusion("*#22*3#2#2*12*1*4##")


def test_a_gateway_without_amplifiers_does_not_parse_anything(installation):
    del installation.data[DOMAIN][MAC][const.CONF_PLATFORMS]["media_player"]
    installation.handler.handle_sound_diffusion("*#22*5#2#1*11*1*10600*14##")
    assert installation.data[DOMAIN][MAC][const.CONF_SOUND_SOURCES][1] == {}


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


def test_the_tuner_attributes_show_even_when_the_amplifier_is_off(installation):
    """The tuner is one box for the whole house: what it plays is worth showing."""
    installation.replay(CAPTURE)
    _entity = installation.entity(2, 1)

    assert _entity.state == OFF
    assert _entity.extra_state_attributes == {
        "area": 2,
        "point": 1,
        "source_id": 1,
        "frequency_mhz": 106.0,
        "station_name": "SUD RADIO",
        "preset": 14,
        "raw_volume": 17,
    }
    # What the amplifier plays, on the other hand, is nothing.
    assert _entity.media_title is None
    assert _entity.media_channel is None
    assert _entity.media_content_type is None


def test_an_amplifier_follows_the_source_a_what_35_command_selected(installation):
    _entity = installation.entity(2, 2)
    installation.replay(["*#22*3#2#2*12*1*4##", "*#22*5#2#1*11*1*10600*14##"])
    assert _entity.media_title == "106.0 MHz · SUD RADIO"

    installation.handler.handle_sound_diffusion("*22*35#4#2#2*3#2#2##")
    installation.handler.handle_sound_diffusion("*#22*5#2#2*11*1*9730*15##")

    assert _entity.media_title == "97.3 MHz · NOSTALGIE"
    assert _entity.extra_state_attributes["source_id"] == 2


def test_an_unchanged_tuner_does_not_refresh_the_amplifiers(installation):
    installation.handler.handle_sound_diffusion("*#22*5#2#1*11*1*10600*14##")
    for _entity in installation.entities.values():
        _entity.written_states = 0

    installation.handler.handle_sound_diffusion("*#22*5#2#1*11*1*10600*14##")
    assert all(_entity.written_states == 0 for _entity in installation.entities.values())

    installation.handler.handle_sound_diffusion("*#22*5#2#1*11*1*9730*15##")
    assert all(_entity.written_states == 1 for _entity in installation.entities.values())


def test_an_empty_station_table_falls_back_to_the_built_in_one():
    """`radio_stations:` with nothing under it must not blank every station."""
    installation = Installation(amplifiers=[(2, 2, "Radio")], radio_stations={})
    installation.replay(["*#22*3#2#2*12*1*4##", "*#22*5#2#1*11*1*10600*14##"])
    assert installation.entity(2, 2).media_channel == "SUD RADIO"


def test_a_modulation_other_than_fm_is_reported_in_khz():
    installation = Installation(amplifiers=[(2, 2, "Radio")])
    installation.replay(["*#22*3#2#2*12*1*4##", "*#22*5#2#1*11*3*1080*4##"])
    _entity = installation.entity(2, 2)
    assert _entity.media_title == "1080 kHz"
    assert _entity.extra_state_attributes["modulation"] == 3


def test_the_gateway_station_table_overrides_the_built_in_one():
    installation = Installation(amplifiers=[(2, 2, "Radio")], radio_stations={"106.0": "MA RADIO"})
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


def test_a_wall_command_right_after_a_home_assistant_one_is_applied(installation):
    """Verified on hardware: every command is echoed by the bus in under 300 ms.

    Whatever comes next therefore says what the amplifier is doing now, even a
    tenth of a second after we asked for something else: somebody pressed the
    wall switch.
    """
    _entity = installation.entity(2, 2)
    asyncio.run(_entity.async_turn_on())
    assert _entity.state == PLAYING

    installation.handler.handle_sound_diffusion("*22*0#4#2*3#2#2##")
    assert _entity.state == OFF

    installation.handler.handle_sound_diffusion("*#22*3#2#2*12*0*10##")
    assert _entity.state == OFF


def test_a_volume_moved_at_the_wall_right_after_a_command_is_applied(installation):
    _entity = installation.entity(2, 2)
    asyncio.run(_entity.async_set_volume_level(0.5))
    assert _entity._raw_volume == 16

    installation.handler.handle_sound_diffusion("*#22*3#2#2*1*20##")
    assert _entity._raw_volume == 20


def test_an_amplifier_that_never_was_commanded_takes_what_the_bus_says(installation):
    _entity = installation.entity(2, 2)
    installation.handler.handle_sound_diffusion("*#22*3#2#2*12*1*4##")
    installation.handler.handle_sound_diffusion("*#22*3#2#2*1*18##")
    assert _entity.state == PLAYING
    assert _entity._raw_volume == 18


def test_next_and_previous_track_use_the_bus_observed_form(installation):
    _entity = installation.entity(2, 2)
    asyncio.run(_entity.async_media_next_track())
    asyncio.run(_entity.async_media_previous_track())
    assert installation.handler.sent == ["*22*9*5#3#2#2##", "*22*10*5#3#2#2##"]


def test_the_tuner_is_only_asked_for_once_per_gateway(installation):
    """Every amplifier asks about itself; only one of them asks about the tuner."""

    async def _update_every_amplifier():
        for _entity in installation.entities.values():
            await _entity.async_update()

    asyncio.run(_update_every_amplifier())

    _requests = installation.handler.status_requests
    assert _requests.count("*#22*5#2#1*11##") == 1
    for _area, _point, _ in AMPLIFIERS:
        assert _requests.count(f"*#22*3#{_area}#{_point}*12##") == 1
        assert _requests.count(f"*#22*3#{_area}#{_point}*1##") == 1


def test_only_one_amplifier_asks_for_the_shared_tuning(installation):
    """Eleven amplifiers are added at once, and the tuner is one box.

    The flag is claimed with no `await` between the test and the set, so the
    amplifiers cannot interleave between the two however they are scheduled.
    """

    async def _update_concurrently():
        await asyncio.gather(*(_entity.async_update() for _entity in installation.entities.values()))

    asyncio.run(_update_concurrently())

    assert installation.handler.status_requests.count("*#22*5#2#1*11##") == 1


def test_each_source_is_asked_for_once():
    installation = Installation(source=lambda area, point: 1 if area == 2 else 2)

    async def _update_every_amplifier():
        for _entity in installation.entities.values():
            await _entity.async_update()

    asyncio.run(_update_every_amplifier())

    _requests = installation.handler.status_requests
    assert _requests.count("*#22*5#2#1*11##") == 1
    assert _requests.count("*#22*5#2#2*11##") == 1
    assert sorted(_request for _request in _requests if _request.startswith("*#22*5#")) == [
        "*#22*5#2#1*11##",
        "*#22*5#2#2*11##",
    ]


# --------------------------------------------------------------------------- #
# Connection state
# --------------------------------------------------------------------------- #


def test_connecting_and_disconnecting_writes_every_amplifier_state(installation):
    """`available` is the gateway connection, so only the gateway can refresh it.

    Entities are added before the listening worker is created
    (`async_forward_entry_setups` is awaited first in `__init__.py`), so they
    write "unavailable" on their first state write and nothing but the gateway
    can clear it.
    """
    installation.handler._set_connected(False)
    for _entity in installation.entities.values():
        _entity.written_states = 0
        assert _entity.available is False

    installation.handler._set_connected(True)
    assert all(_entity.available is True for _entity in installation.entities.values())
    assert all(_entity.written_states == 1 for _entity in installation.entities.values())

    installation.handler._set_connected(False)
    assert all(_entity.available is False for _entity in installation.entities.values())
    assert all(_entity.written_states == 2 for _entity in installation.entities.values())


def test_a_connection_state_that_does_not_change_writes_nothing(installation):
    for _entity in installation.entities.values():
        _entity.written_states = 0

    installation.handler._set_connected(True)

    assert all(_entity.written_states == 0 for _entity in installation.entities.values())


def test_an_entity_not_yet_added_to_hass_is_not_written(installation):
    """`async_write_ha_state` raises before Home Assistant has added the entity."""
    _entity = installation.entity(2, 2)
    _entity.hass = None

    installation.handler._set_connected(False)

    assert _entity.written_states == 0
    assert installation.entity(7, 1).written_states == 1


def test_the_connection_state_survives_an_unloaded_config_entry(installation):
    del installation.data[DOMAIN][MAC]
    installation.handler._set_connected(False)


def test_a_reconnection_asks_every_amplifier_and_the_tuner_again(installation):
    """The bus lived on without us: what we know is stale, so ask again."""

    async def _update_every_amplifier():
        for _entity in installation.entities.values():
            await _entity.async_update()

    asyncio.run(_update_every_amplifier())
    _booted = len(installation.handler.status_requests)
    assert installation.handler.status_requests.count("*#22*5#2#1*11##") == 1

    installation.handler._set_connected(False)
    asyncio.run(installation.handler.reconnected())

    _after = installation.handler.status_requests[_booted:]
    assert installation.handler.is_connected is True
    assert _after.count("*#22*5#2#1*11##") == 1, "the shared tuner is asked for again"
    for _area, _point, _ in AMPLIFIERS:
        assert _after.count(f"*#22*3#{_area}#{_point}*12##") == 1
        assert _after.count(f"*#22*3#{_area}#{_point}*1##") == 1
