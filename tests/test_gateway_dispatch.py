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
number = ha_stubs.load("number")
select = ha_stubs.load("select")
tuner = ha_stubs.load("tuner")

DOMAIN = const.DOMAIN
MAC = "00:03:50:11:22:33"
PLAYING = ha_stubs.MediaPlayerState.PLAYING
OFF = ha_stubs.MediaPlayerState.OFF

#: The installation the frames below were captured on, minus the disabled tablet.
AMPLIFIERS = [
    (7, 1, "Radio Cuisine"),
    (2, 1, "Radio Suite"),
    (2, 2, "Radio Suite SDB"),
    (3, 1, "Radio Office 1"),
    (3, 2, "Radio Office 1 Bathroom"),
    (4, 1, "Radio Gym"),
    (5, 1, "Radio Chambre Ami"),
    (5, 2, "Radio Chambre Ami SDB"),
    (6, 1, "Radio Office 2"),
    (6, 2, "Radio Office 2 Bathroom"),
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
        self.generate_events = False
        self.gateway = types.SimpleNamespace(serial=MAC, log_id="[test]", host="192.168.1.17")
        # Cancelled by `listening_loop` on its way out.
        self.listening_worker = types.SimpleNamespace(cancel=lambda: None)
        self.sent = []
        self.status_requests = []

    async def send(self, message):
        await asyncio.sleep(0)
        self.sent.append(str(message))

    async def send_status_request(self, message):
        # Yielding here is what makes the interleaving of `async_update` visible.
        await asyncio.sleep(0)
        self.status_requests.append(str(message))


def configuration_file(amplifiers=None, source=1, radio_stations=None, tuning_preset=None) -> str:
    """The `myhome.yaml` such an installation would hold."""
    _lines = ["house:", f'  mac: "{MAC}"', "  media_player:"]
    for _area, _point, _name in amplifiers if amplifiers is not None else AMPLIFIERS:
        _source = source(_area, _point) if callable(source) else source
        _lines.append(f'    ampli_{_area}_{_point}: {{ where: "3#{_area}#{_point}", name: "{_name}", source: {_source} }}')
    if radio_stations is not None:
        _lines.append("  radio_stations:" + (" {}" if not radio_stations else ""))
        for _frequency, _name in radio_stations.items():
            _lines.append(f'    "{_frequency}": "{_name}"')
    if tuning_preset is not None:
        _lines.append(f"  tuning_preset: {tuning_preset}")
    return "\n".join(_lines) + "\n"


class Installation:
    """A stubbed `hass` holding one gateway and its amplifier entities.

    The data structure comes out of the real `validate.config_schema`, so the
    tests cannot drift away from what the integration is actually handed.
    """

    def __init__(self, amplifiers=AMPLIFIERS, source=1, radio_stations=None, tuning_preset=None):
        self.data = {
            DOMAIN: validate.config_schema(yaml.safe_load(configuration_file(amplifiers, source, radio_stations, tuning_preset)))
        }

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

        # The tuner devices `validate.py` derived out of those amplifiers, kept
        # apart from `self.entities`: the assertions walking that one are about
        # the amplifiers.
        self.tuner_entities = {}
        _platforms = self.data[DOMAIN][MAC][const.CONF_PLATFORMS]
        for _device_id, _device in _platforms.get("number", {}).items():
            self._add_tuner_entity(
                _device,
                number.MyHOMETunerFrequency(
                    hass=self,
                    device_id=_device_id,
                    who=_device[const.CONF_WHO],
                    where=_device[const.CONF_WHERE],
                    name=_device["name"],
                    source=_device[const.CONF_SOURCE],
                    manufacturer=_device[const.CONF_MANUFACTURER],
                    model=_device[const.CONF_DEVICE_MODEL],
                    gateway=self.handler,
                ),
            )
        for _device_id, _device in _platforms.get("select", {}).items():
            self._add_tuner_entity(
                _device,
                select.MyHOMETunerStation(
                    hass=self,
                    device_id=_device_id,
                    who=_device[const.CONF_WHO],
                    where=_device[const.CONF_WHERE],
                    name=_device["name"],
                    source=_device[const.CONF_SOURCE],
                    manufacturer=_device[const.CONF_MANUFACTURER],
                    model=_device[const.CONF_DEVICE_MODEL],
                    gateway=self.handler,
                ),
            )
        for _device_id, _device in _platforms.get("button", {}).items():
            if _device[const.CONF_WHO] != "22":
                continue
            for _button in tuner.tuner_buttons(hass=self, device_id=_device_id, device=_device, gateway=self.handler):
                self._add_tuner_entity(_device, _button)

    def _add_tuner_entity(self, device, entity):
        """What `async_added_to_hass` does for a tuner entity."""
        entity.hass = self
        device[const.CONF_ENTITIES][entity._entity_key] = entity
        self.tuner_entities[f"{entity._device_id}-{entity._entity_key}"] = entity

    def tuner_entity(self, key, source=1):
        return self.tuner_entities[f"{sound_diffusion.tuner_device_id(source)}-{key}"]

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


def test_an_amplifier_moved_by_a_what_35_is_refreshed_by_its_new_source(installation):
    """A runtime source switch has to move the entity, not only what it reads.

    The configured source is what the file says; WHAT 35 is what happened. It is
    the entity, which knows both, that tells a source event apart.
    """
    _entity = installation.entity(2, 2)
    installation.handler.handle_sound_diffusion("*22*35#4#2#2*3#2#2##")
    _entity.written_states = 0

    installation.handler.handle_sound_diffusion("*#22*5#2#1*11*1*10600*14##")
    assert _entity.written_states == 0

    installation.handler.handle_sound_diffusion("*#22*5#2#2*11*1*9730*15##")
    assert _entity.written_states == 1
    assert _entity.media_title == "97.3 MHz · NOSTALGIE"


def test_a_source_nobody_listens_to_is_parsed_and_ignored(installation):
    """Verified on hardware: sources 2 to 4 answer a dim 11 request as well.

    They exist on the bus and are tuned to something; no amplifier of this
    installation is on them, so nothing they say is worth a state write.
    """
    installation.replay(["*#22*5#2#1*11*1*9430*1##"])
    for _entity in installation.entities.values():
        _entity.written_states = 0

    installation.handler.handle_sound_diffusion("*#22*2#2*5*1*8701##")

    assert all(_entity.written_states == 0 for _entity in installation.entities.values())
    assert installation.tuner[2]["frequency"] == 8701
    assert installation.entity(2, 2).extra_state_attributes["frequency_mhz"] == 94.3


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
    assert installation.handler.sent[-1] == "*22*0#4#2*3#2#2##"


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


def test_next_and_previous_track_address_the_source(installation):
    """Spec form, verified on hardware: the tuner is what moves, not the amplifier."""
    _entity = installation.entity(2, 2)
    asyncio.run(_entity.async_media_next_track())
    asyncio.run(_entity.async_media_previous_track())
    assert installation.handler.sent == ["*22*9#*2#1##", "*22*10#*2#1##"]


def test_next_track_follows_the_source_the_amplifier_listens_to():
    installation = Installation(amplifiers=[(2, 2, "Radio")], source=2)
    asyncio.run(installation.entity(2, 2).async_media_next_track())
    assert installation.handler.sent == ["*22*9#*2#2##"]


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


# --------------------------------------------------------------------------- #
# Listening loop
# --------------------------------------------------------------------------- #


class FakeEventSession:
    """Stand-in for `OWNEventSession`, playing a script of frames and failures.

    An `Exception` in the script is raised instead of being returned, which is
    what OWNd does when the reconnection it attempts on an interrupted read
    fails in its turn. The loop is asked to stop once the script runs out.
    """

    def __init__(self, script, handler):
        self._script = list(script)
        self._handler = handler
        self.connects = 0
        self.closed = False
        self._stream_reader = object()

    async def connect(self):
        self.connects = self.connects + 1

    async def get_next(self):
        # No `await` here on purpose: the real `get_next` fails without
        # yielding when its reader is missing, and the loop must cope.
        if not self._script:
            self._handler._terminate_listener = True
            # A frame the loop ignores, so nothing is read into the last turn.
            return "*16*3*22##"
        _next = self._script.pop(0)
        if isinstance(_next, Exception):
            raise _next
        return _next

    async def close(self):
        self.closed = True


def _run_listening_loop(installation, monkeypatch, script):
    monkeypatch.setattr(gateway, "EVENT_SESSION_RETRY_DELAY", 0)
    _session = FakeEventSession(script, installation.handler)
    monkeypatch.setattr(gateway, "OWNEventSession", lambda gateway, logger: _session)
    asyncio.run(installation.handler.listening_loop())
    return _session


def test_the_listening_loop_survives_a_session_that_raises(installation, monkeypatch):
    """`get_next` swallows what it knows about; the rest must not kill the loop.

    A gateway whose listener died is a gateway that never comes back, since
    nothing else reads the bus.
    """
    _session = _run_listening_loop(
        installation,
        monkeypatch,
        ["*#22*3#2#2*12*1*4##", OSError("connection lost"), "*#22*3#2#2*1*18##"],
    )

    _entity = installation.entity(2, 2)
    assert _entity.state == PLAYING, "the frames after the failure were handled"
    assert _entity._raw_volume == 18
    assert _session.connects == 2, "the session was reopened"
    assert _session.closed is True


def test_a_session_that_raises_is_caught_up_with_once_it_answers_again(installation, monkeypatch):
    """The failure marks the amplifiers unavailable; the next frame catches up.

    The catch-up only runs on an amplifier the gateway had given up on, so the
    status requests below are the proof that it did.
    """
    _run_listening_loop(
        installation,
        monkeypatch,
        [OSError("connection lost"), "*#22*3#2#2*12*1*4##"],
    )

    assert installation.handler.status_requests.count("*#22*3#2#2*12##") == 1
    assert installation.handler.status_requests.count("*#22*5#2#1*11##") == 1


def test_a_frame_owND_cannot_parse_is_ignored_without_dropping_the_session(installation, monkeypatch, caplog):
    """OWNd answers `None` for a frame its parser chokes on (a WHO=13 time write
    without timezone raises an IndexError in 0.7.48); the socket is fine."""
    with caplog.at_level("WARNING", logger="myhome"):
        _session = _run_listening_loop(installation, monkeypatch, [None, None, "*#22*3#2#2*12*1*4##", None])

    # (the loop marks the gateway disconnected when it exits; what matters is
    # that no reconnection happened along the way and the frame after got in)
    assert _session.connects == 1, "the initial connect only: a parse failure is not a lost socket"
    assert installation.entity(2, 2).state == PLAYING
    assert not [_record for _record in caplog.records if _record.levelname == "WARNING"]


def test_a_session_without_reader_is_reopened_and_yields(installation, monkeypatch):
    """A missing reader makes `get_next` fail without yielding: reopen it, and let other tasks run meanwhile."""
    _other_task_ran = False

    async def _other():
        nonlocal _other_task_ran
        _other_task_ran = True

    async def _both():
        _task = asyncio.ensure_future(_other())
        monkeypatch.setattr(gateway, "EVENT_SESSION_RETRY_DELAY", 0)
        _session = FakeEventSession([None] * 50, installation.handler)
        _session._stream_reader = None
        monkeypatch.setattr(gateway, "OWNEventSession", lambda gateway, logger: _session)
        await installation.handler.listening_loop()
        await _task
        return _session

    _session = asyncio.run(_both())

    assert _other_task_ran, "the loop starved the event loop"
    assert _session.connects >= 50, "every `None` without a reader must try to reopen the session"


def test_a_reconnection_survives_an_amplifier_that_cannot_be_updated(installation):
    """One amplifier refusing to talk must not stop the gateway from coming back."""

    async def _fail():
        raise RuntimeError("the bus said no")

    installation.entity(2, 2).async_update = _fail
    installation.handler._set_connected(False)

    asyncio.run(installation.handler.reconnected())

    assert installation.handler.is_connected is True


def test_a_source_event_that_feeds_nothing_is_not_dispatched(installation):
    """`SourceState` and the source commands are parsed for the log, and stop there."""
    installation.replay(["*#22*3#2#2*12*1*4##"])
    for _entity in installation.entities.values():
        _entity.written_states = 0

    for _frame in ("*#22*5#2#1*12*1*4##", "*22*1#4#2*2#1##", "*22*2#4#2*5#2#1##"):
        installation.handler.handle_sound_diffusion(_frame)

    assert all(_entity.written_states == 0 for _entity in installation.entities.values())
    assert installation.entity(2, 2).state == PLAYING


# --------------------------------------------------------------------------- #
# Selecting a station
# --------------------------------------------------------------------------- #


def test_the_source_list_is_the_station_table_sorted_by_frequency(installation):
    _entity = installation.entity(7, 1)

    assert _entity.source_list == [_name for _frequency, _name in sorted(sound_diffusion.STATIONS.items())]
    assert _entity.source_list[:2] == ["MOUV'", "RADIO CAMPUS"]


def test_the_source_list_follows_the_gateway_station_table():
    installation = Installation(amplifiers=[(2, 2, "Radio")], radio_stations={"106.0": "MA RADIO", "97.3": "AUTRE"})
    assert installation.entity(2, 2).source_list == ["AUTRE", "MA RADIO"]


def test_an_empty_station_table_leaves_the_built_in_source_list():
    installation = Installation(amplifiers=[(2, 2, "Radio")], radio_stations={})
    assert len(installation.entity(2, 2).source_list) == len(sound_diffusion.STATIONS)


def test_selecting_a_station_writes_the_scratch_preset(installation):
    """The frame's preset is 0-based, so the last preset, 15, is written as 14."""
    _entity = installation.entity(7, 1)

    asyncio.run(_entity.async_select_source("FRANCE INTER"))

    assert installation.handler.sent == ["*#22*5#2#1*#11*1*8970*14##"]


def test_selecting_a_station_uses_the_tuning_preset_of_the_gateway():
    installation = Installation(amplifiers=[(2, 2, "Radio")], tuning_preset=3)

    asyncio.run(installation.entity(2, 2).async_select_source("FRANCE INTER"))

    assert installation.handler.sent == ["*#22*5#2#1*#11*1*8970*2##"]
    assert installation.entity(2, 2).extra_state_attributes["preset"] == 3


def test_selecting_a_station_addresses_the_source_the_amplifier_listens_to():
    installation = Installation(amplifiers=[(2, 2, "Radio")], source=2)

    asyncio.run(installation.entity(2, 2).async_select_source("NOSTALGIE"))

    assert installation.handler.sent == ["*#22*5#2#2*#11*1*9730*14##"]


def test_selecting_a_station_is_reflected_before_the_bus_answers(installation):
    _entity = installation.entity(7, 1)
    _entity.handle_event(sound_diffusion.AmplifierState(area=7, point=1, is_on=True, mmtype=4))
    _entity.written_states = 0

    asyncio.run(_entity.async_select_source("FRANCE INTER"))

    assert _entity.written_states == 1
    assert installation.tuner[1] == {"modulation": 1, "frequency": 8970, "station": 15}
    assert _entity.media_title == "89.7 MHz \u00b7 FRANCE INTER"
    assert _entity.source == "FRANCE INTER"


def test_the_echo_of_a_selection_says_nothing_new(installation):
    """The optimistic refresh records the 1-based preset the bus will echo."""
    _entity = installation.entity(7, 1)
    asyncio.run(_entity.async_select_source("FRANCE INTER"))
    _written = _entity.written_states

    installation.replay(["*#22*5#2#1*5*1*8970##", "*#22*5#2#1*11*1*8970*15##"])

    assert _entity.written_states == _written


def test_selecting_a_station_refreshes_every_amplifier_on_that_source():
    installation = Installation(source=lambda area, point: 1 if area == 2 else 2)
    for _entity in installation.entities.values():
        _entity.written_states = 0

    asyncio.run(installation.entity(2, 2).async_select_source("FRANCE INTER"))

    assert installation.entity(2, 1).written_states == 1
    assert installation.entity(2, 2).written_states == 1
    assert installation.entity(7, 1).written_states == 0


def test_selecting_a_station_does_not_turn_the_amplifier_on(installation):
    """The tuner is shared: changing station says nothing about who listens."""
    _entity = installation.entity(7, 1)

    asyncio.run(_entity.async_select_source("FRANCE INTER"))

    assert _entity.state is None
    # The tuner moved, so `source` follows it; the amplifier did not.
    assert _entity.source == "FRANCE INTER"
    assert _entity.media_channel is None
    assert _entity.extra_state_attributes["frequency_mhz"] == 89.7


def test_source_reflects_the_station_the_shared_tuner_is_on(installation):
    installation.replay(["*#22*3#2#2*12*1*4##", "*#22*5#2#1*11*1*10600*14##"])
    assert installation.entity(2, 2).source == "SUD RADIO"

    installation.replay(["*#22*5#2#1*11*1*10110*14##"])
    assert installation.entity(2, 2).source is None, "101.1 MHz is not in the station table"


def test_source_is_scoped_to_the_tuner_not_to_the_amplifier(installation):
    """Every amplifier names the station, playing it or not — `media_channel` does not.

    A dashboard showing the station dropdown of an amplifier that is off must
    show the station selected in it, or the control looks broken.
    """
    installation.replay(["*#22*5#2#1*11*1*10600*14##"])

    _off = installation.entity(2, 1)
    assert _off.state is None
    assert _off.source == "SUD RADIO"
    assert _off.media_channel is None
    assert _off.media_title is None

    installation.replay(["*#22*3#2#1*12*0*10##"])
    assert _off.state == OFF
    assert _off.source == "SUD RADIO"


def test_source_carries_the_disambiguating_suffix_of_the_source_list():
    installation = Installation(amplifiers=[(2, 2, "Radio")], radio_stations={"106.0": "RELAIS", "97.3": "RELAIS"})
    installation.replay(["*#22*3#2#2*12*1*4##", "*#22*5#2#1*11*1*10600*14##"])
    _entity = installation.entity(2, 2)

    assert _entity.source_list == ["RELAIS (97.3)", "RELAIS (106.0)"]
    assert _entity.source == "RELAIS (106.0)"
    assert _entity.source in _entity.source_list

    asyncio.run(_entity.async_select_source("RELAIS (97.3)"))
    assert installation.handler.sent == ["*#22*5#2#1*#11*1*9730*14##"]


def test_selecting_a_station_the_table_does_not_carry_is_refused(installation):
    _entity = installation.entity(7, 1)

    with pytest.raises(ha_stubs.ServiceValidationError):
        asyncio.run(_entity.async_select_source("RADIO NOWHERE"))

    assert installation.handler.sent == []
    assert installation.tuner[1] == {}


def test_selecting_a_station_supports_source_selection(installation):
    assert installation.entity(7, 1).supported_features & ha_stubs.MediaPlayerEntityFeature.SELECT_SOURCE


# --------------------------------------------------------------------------- #
# A preset the tuner left behind
# --------------------------------------------------------------------------- #

#: Hardware session of 2026-08-26, `hwtest-write-presets.log`, sequence S1:
#: an automatic scan upwards answers with dimension 5 and nothing else.
SCAN_UP = ["*#22*5#2#1*5*1*10730##"]

#: Same log, sequence S2: a scan downwards falls back onto preset 15 and says so.
SCAN_DOWN = [
    "*#22*5#2#1*5*1*10680##",
    "*#22*5#2#1*11*1*10680*15##",
    "*#22*5#2#1*5*1*10680##",
    "*#22*5#2#1*11*1*10680*15##",
]


def preset_step(frequency: int, station: int) -> list:
    """The two frames a preset step answers with, in the order the bus sends them.

    Dimension 5 with the frequency it landed on and, about 20 ms later,
    dimension 11 with the same frequency and the slot number. The frequencies
    below are taken from the built-in station table rather than from a
    transcript; the *shape* is what these tests are about.
    """
    return [
        f"*#22*5#2#1*5*1*{frequency}##",
        f"*#22*5#2#1*11*1*{frequency}*{station}##",
    ]


#: The fifteen slots of the tuner, stepped through one **next preset** at a time.
PRESETS = [
    (8770, 1),
    (8850, 2),
    (8970, 3),
    (9130, 4),
    (9220, 5),
    (9350, 6),
    (9430, 7),
    (9530, 8),
    (9670, 9),
    (9730, 10),
    (9820, 11),
    (9960, 12),
    (10080, 13),
    (10240, 14),
    (10420, 15),
]


def presets_seen(installation, frames, source=1) -> list:
    """Replay `frames` one at a time, reading the preset back after each.

    A preset that blinks — a value, then `None`, then a value again — is what a
    dashboard shows as a row going blank, and it is only visible between two
    frames of the same burst.
    """
    _seen = []
    for _frame in frames:
        installation.replay([_frame])
        _seen.append(installation.tuner[source].get("station"))
    return _seen


def test_a_scan_up_commanded_here_drops_the_preset_before_the_bus_answers(installation):
    """S1: the tuner jumps and never says which slot it is on now, so we drop it."""
    installation.replay(["*#22*5#2#1*11*1*10680*15##"])
    assert installation.tuner[1]["station"] == 15

    asyncio.run(installation.tuner_entity("seek_up").async_press())

    assert installation.tuner[1]["station"] is None
    assert installation.handler.sent == ["*22*5#*2#1##"]

    installation.replay(SCAN_UP)

    assert installation.tuner[1]["frequency"] == 10730
    assert installation.tuner[1]["station"] is None


def test_a_scan_down_commanded_here_drops_the_preset_too(installation):
    """S2: dropped on the press, and put back by the dimension 11 that follows."""
    installation.replay(["*#22*5#2#1*11*1*10730*3##"])

    asyncio.run(installation.tuner_entity("seek_down").async_press())
    assert installation.tuner[1]["station"] is None

    installation.replay(SCAN_DOWN)

    assert installation.tuner[1]["frequency"] == 10680
    assert installation.tuner[1]["station"] == 15


def test_a_stale_preset_is_left_out_of_the_attributes(installation):
    installation.replay(["*#22*3#2#2*12*1*4##", "*#22*5#2#1*11*1*10680*15##"])
    _entity = installation.entity(2, 2)
    assert _entity.extra_state_attributes["preset"] == 15

    asyncio.run(installation.tuner_entity("seek_up").async_press())
    installation.replay(SCAN_UP)

    assert "preset" not in _entity.extra_state_attributes
    # The frequency is what the tuner reported, and the station table still
    # names it: only the slot number is unknown.
    assert _entity.media_title == "107.3 MHz · BFM BUSINESS"
    assert _entity.extra_state_attributes["frequency_mhz"] == 107.3
    assert _entity.extra_state_attributes["station_name"] == "BFM BUSINESS"


def test_a_seek_button_writes_the_amplifiers_once(installation):
    """The optimistic drop is a state change like any other: one write, not two."""
    installation.replay(["*#22*5#2#1*11*1*10680*15##"])
    for _entity in list(installation.entities.values()) + list(installation.tuner_entities.values()):
        _entity.written_states = 0

    asyncio.run(installation.tuner_entity("seek_up").async_press())

    assert all(_entity.written_states == 1 for _entity in installation.entities.values())
    # The tuner's own entities read the same store: the Preset row of the
    # dashboard is what the drop is early for.
    assert installation.tuner_entity("frequency").written_states == 1


def test_a_seek_button_on_a_tuner_nobody_heard_from_writes_nothing(installation):
    """Nothing to drop: the store has no preset to blank out."""
    for _entity in installation.entities.values():
        _entity.written_states = 0

    asyncio.run(installation.tuner_entity("seek_up").async_press())

    assert installation.tuner[1].get("station") is None
    assert all(_entity.written_states == 0 for _entity in installation.entities.values())
    assert installation.handler.sent == ["*22*5#*2#1##"]


def test_a_preset_step_never_blanks_the_preset(installation):
    """T6: the burst is dimension 5 then dimension 11, and 5 must not blank 11.

    The bus reports the new frequency about 20 ms before it reports the slot.
    Reading a moved frequency as "the preset is unknown" made every preset step
    blink the row: a number, nothing, the next number.
    """
    installation.replay(["*#22*5#2#1*11*1*10680*14##"])

    asyncio.run(installation.tuner_entity("next_preset").async_press())
    _seen = presets_seen(installation, preset_step(10730, 15))

    assert None not in _seen
    assert _seen == [14, 15]
    assert installation.tuner[1]["frequency"] == 10730


def test_stepping_through_the_fifteen_presets_never_blanks_the_preset(installation):
    """N01..N15: fifteen **next preset** steps in a row, one burst each."""
    installation.replay(["*#22*5#2#1*11*1*10680*15##"])
    _seen = []

    for _frequency, _station in PRESETS:
        asyncio.run(installation.tuner_entity("next_preset").async_press())
        _seen.extend(presets_seen(installation, preset_step(_frequency, _station)))

    assert None not in _seen
    assert _seen[1::2] == [_station for _frequency, _station in PRESETS]


def test_a_preset_step_writes_each_amplifier_at_most_twice(installation):
    """One write for the frequency, one for the slot: the burst carries two frames."""
    installation.replay(["*#22*5#2#1*11*1*10680*15##"])

    for _frequency, _station in PRESETS:
        for _entity in installation.entities.values():
            _entity.written_states = 0

        asyncio.run(installation.tuner_entity("next_preset").async_press())
        installation.replay(preset_step(_frequency, _station))

        assert all(_entity.written_states <= 2 for _entity in installation.entities.values())


def test_a_dimension_5_on_the_frequency_we_hold_keeps_the_preset(installation):
    """The tuner repeats itself constantly; a reading that moved nothing is not a scan."""
    installation.replay(["*#22*5#2#1*11*1*10680*15##"])
    for _entity in installation.entities.values():
        _entity.written_states = 0

    installation.replay(["*#22*5#2#1*5*1*10680##"])

    assert installation.tuner[1]["station"] == 15
    assert all(_entity.written_states == 0 for _entity in installation.entities.values())


def test_a_scan_at_the_wall_leaves_the_preset_it_left_behind(installation):
    """The residual of dropping the preset on the press rather than on the frame.

    Nobody tells us a scan happened until the tuner reports a slot again, so a
    seek done at a wall control shows the slot it started from for as long as it
    takes the tuner to sit on one — a dimension 6 or a dimension 11.
    """
    installation.replay(["*#22*5#2#1*11*1*10680*15##"])

    installation.replay(SCAN_UP)

    assert installation.tuner[1]["frequency"] == 10730
    assert installation.tuner[1]["station"] == 15


def test_a_dimension_6_puts_the_preset_back_on_its_own(installation):
    installation.replay(["*#22*5#2#1*11*1*10680*15##"])
    asyncio.run(installation.tuner_entity("seek_up").async_press())
    installation.replay(SCAN_UP)
    assert installation.tuner[1]["station"] is None

    installation.replay(["*#22*2#1*6*3##"])

    assert installation.tuner[1]["station"] == 3
    assert installation.tuner[1]["frequency"] == 10730


def test_the_first_frequency_of_an_unknown_tuner_carries_no_preset(installation):
    installation.replay(["*#22*5#2#1*5*1*10730##"])
    assert installation.tuner[1]["frequency"] == 10730
    assert installation.tuner[1].get("station") is None


# --------------------------------------------------------------------------- #
# RDS: the name the station calls itself
# --------------------------------------------------------------------------- #

#: The frames of the hardware session of 2026-08-26, verbatim.
RDS_SKYROCK = "*#22*5#2#1*10*83*75*89*82*79*67*75*32##"
RDS_M_RADIO = "*#22*5#2#1*10*77*32*82*65*68*73*79*32##"
RDS_SILENT = "*#22*5#2#1*10*32*32*32*32*32*32*32*32##"


def test_the_rds_name_reaches_the_shared_store(installation):
    installation.replay(["*#22*5#2#1*11*1*8850*3##", RDS_M_RADIO])

    assert installation.tuner[1]["rds"] == "M RADIO"


def test_a_tuner_with_nothing_to_say_holds_no_name(installation):
    """Eight spaces: tuned, but no RDS text has reached the box yet."""
    installation.replay([RDS_SILENT])

    assert installation.tuner[1]["rds"] is None


def test_an_rds_name_that_says_nothing_new_writes_nothing(installation):
    installation.replay([RDS_SKYROCK])
    for _entity in installation.entities.values():
        _entity.written_states = 0

    installation.replay([RDS_SKYROCK])

    assert all(_entity.written_states == 0 for _entity in installation.entities.values())


def test_the_rds_name_is_dropped_when_the_frequency_moves(installation):
    """It named the station that was playing; the tuner sends the new one after."""
    installation.replay(["*#22*5#2#1*11*1*10280*2##", RDS_SKYROCK])

    installation.replay(["*#22*5#2#1*5*1*8850##"])
    assert installation.tuner[1]["rds"] is None

    installation.replay([RDS_M_RADIO])
    assert installation.tuner[1]["rds"] == "M RADIO"


def test_a_frequency_that_did_not_move_keeps_the_rds_name(installation):
    installation.replay(["*#22*5#2#1*11*1*10280*2##", RDS_SKYROCK, "*#22*5#2#1*5*1*10280##"])

    assert installation.tuner[1]["rds"] == "SKYROCK"


def test_the_first_frequency_of_a_gateway_keeps_a_name_that_arrived_first(installation):
    """A first reading is not a change: the RDS stream can answer before it."""
    installation.replay([RDS_SKYROCK, "*#22*5#2#1*11*1*10280*2##"])

    assert installation.tuner[1]["rds"] == "SKYROCK"


def test_an_rds_name_of_another_source_leaves_this_one_alone():
    installation = Installation(source=lambda area, point: 1 if area == 2 else 2)

    installation.replay(["*#22*5#2#2*10*83*75*89*82*79*67*75*32##"])

    assert installation.tuner[2]["rds"] == "SKYROCK"
    assert installation.tuner.get(1, {}).get("rds") is None


def test_the_rds_name_is_an_attribute_of_every_amplifier_on_that_source(installation):
    installation.replay(["*#22*5#2#1*11*1*10280*2##", RDS_SKYROCK])

    assert installation.entity(7, 1).extra_state_attributes["rds_name"] == "SKYROCK"
    assert installation.entity(2, 2).extra_state_attributes["rds_name"] == "SKYROCK"


def test_an_amplifier_of_a_silent_tuner_carries_no_rds_attribute(installation):
    installation.replay(["*#22*5#2#1*11*1*10280*2##"])

    assert "rds_name" not in installation.entity(7, 1).extra_state_attributes


def test_the_station_table_wins_over_the_rds_name(installation):
    """The table is what a user configured; RDS covers what it does not carry."""
    installation.replay(["*#22*5#2#1*11*1*9770*4##", RDS_SKYROCK])
    asyncio.run(installation.entity(7, 1).async_turn_on())

    assert installation.entity(7, 1).media_title == "97.7 MHz · FRANCE CULTURE"
    assert installation.entity(7, 1).media_channel == "FRANCE CULTURE"
    assert installation.entity(7, 1).extra_state_attributes["station_name"] == "FRANCE CULTURE"
    assert installation.entity(7, 1).extra_state_attributes["rds_name"] == "SKYROCK"


def test_a_frequency_the_table_does_not_carry_is_named_by_rds(installation):
    installation.replay(["*#22*5#2#1*5*1*8830##", RDS_SKYROCK])
    asyncio.run(installation.entity(7, 1).async_turn_on())

    assert installation.entity(7, 1).media_title == "88.3 MHz · SKYROCK"
    assert installation.entity(7, 1).media_channel == "SKYROCK"
    assert installation.entity(7, 1).extra_state_attributes["station_name"] == "SKYROCK"


def test_a_frequency_nothing_names_is_the_frequency_alone(installation):
    installation.replay(["*#22*5#2#1*5*1*8830##"])
    asyncio.run(installation.entity(7, 1).async_turn_on())

    assert installation.entity(7, 1).media_title == "88.3 MHz"
    assert installation.entity(7, 1).media_channel is None


def test_the_rds_name_of_an_amplifier_that_is_off_is_still_published(installation):
    """Tuner scoped, like the frequency and the preset: one box, one name."""
    installation.replay(["*#22*5#2#1*5*1*8830##", RDS_SKYROCK])

    assert installation.entity(7, 1).state != PLAYING
    assert installation.entity(7, 1).extra_state_attributes["rds_name"] == "SKYROCK"
    assert installation.entity(7, 1).media_title is None


def test_the_rds_stream_is_started_once_per_source(installation):
    """Every entity reading a source claims the same flag, so one frame goes out."""
    for _entity in list(installation.entities.values()) + list(installation.tuner_entities.values()):
        asyncio.run(_entity.async_update())

    assert installation.handler.sent == ["*22*31*2#1##"]


def test_each_source_gets_its_own_rds_stream():
    installation = Installation(source=lambda area, point: 1 if area == 2 else 2)

    for _entity in list(installation.entities.values()) + list(installation.tuner_entities.values()):
        asyncio.run(_entity.async_update())

    assert sorted(installation.handler.sent) == ["*22*31*2#1##", "*22*31*2#2##"]


def test_a_reconnection_starts_the_rds_stream_again(installation):
    """The tuner was left alone while we were not listening; so was its stream."""
    asyncio.run(installation.entity(7, 1).async_update())
    installation.handler.sent.clear()
    installation.handler._set_connected(False)

    asyncio.run(installation.handler.reconnected())

    assert installation.handler.sent == ["*22*31*2#1##"]


def test_the_rds_stream_is_started_after_the_tuning_was_asked_for(installation):
    """The request first: it is answered at once, the RDS name whenever."""
    asyncio.run(installation.tuner_entity("frequency").async_update())

    assert installation.handler.status_requests == ["*#22*5#2#1*11##"]
    assert installation.handler.sent == ["*22*31*2#1##"]


# --------------------------------------------------------------------------- #
# The tuner device: one `number` and four `button` entities
# --------------------------------------------------------------------------- #


def test_a_tuner_device_is_derived_for_each_source():
    installation = Installation(source=lambda area, point: 1 if area == 2 else 2)
    _platforms = installation.data[DOMAIN][MAC][const.CONF_PLATFORMS]

    assert sorted(_platforms["number"]) == ["22-2#1", "22-2#2"]
    assert sorted(_device for _device in _platforms["button"] if _platforms["button"][_device][const.CONF_WHO] == "22") == [
        "22-2#1",
        "22-2#2",
    ]
    assert installation.tuner_entity("frequency", source=2)._source == 2


def test_the_only_tuner_of_a_house_is_named_without_a_number(installation):
    _frequency = installation.tuner_entity("frequency")

    assert _frequency._attr_device_info["name"] == "Tuner FM"
    assert _frequency._attr_device_info["identifiers"] == {(DOMAIN, f"{MAC}-22-2#1")}
    assert _frequency._attr_device_info["manufacturer"] == "BTicino S.p.A."
    assert _frequency._attr_device_info["via_device"] == (DOMAIN, MAC)
    # `has_entity_name`: "Tuner FM" + "Frequency" gives `number.tuner_fm_frequency`.
    assert _frequency._attr_has_entity_name is True
    assert _frequency._attr_name == "Frequency"
    assert _frequency._attr_unique_id == f"{MAC}-22-2#1-frequency"


def test_several_tuners_are_told_apart_by_their_source():
    installation = Installation(source=lambda area, point: 1 if area == 2 else 2)

    assert installation.tuner_entity("frequency", source=1)._attr_device_info["name"] == "Tuner FM 1"
    assert installation.tuner_entity("frequency", source=2)._attr_device_info["name"] == "Tuner FM 2"


def test_the_buttons_share_the_device_of_the_number(installation):
    _frequency = installation.tuner_entity("frequency")

    for _key in ("seek_up", "seek_down", "next_preset", "previous_preset"):
        _button = installation.tuner_entity(_key)
        assert _button._attr_device_info["identifiers"] == _frequency._attr_device_info["identifiers"]
        assert _button._attr_unique_id == f"{MAC}-22-2#1-{_key}"

    assert [installation.tuner_entity(_key)._attr_name for _key, *_ in tuner.TUNER_BUTTONS] == [
        "Seek up",
        "Seek down",
        "Next preset",
        "Previous preset",
    ]


def test_the_number_describes_the_fm_band(installation):
    _frequency = installation.tuner_entity("frequency")

    assert _frequency.native_unit_of_measurement == "MHz"
    assert _frequency.native_min_value == 87.5
    assert _frequency.native_max_value == 108.0
    assert _frequency.native_step == 0.05
    assert _frequency.mode == ha_stubs.NumberMode.AUTO
    assert _frequency.device_class is None
    assert _frequency._attr_icon == "mdi:sine-wave"
    assert _frequency._attr_should_poll is False


def test_the_number_reads_the_shared_tuner(installation):
    _frequency = installation.tuner_entity("frequency")
    assert _frequency.native_value is None

    installation.replay(["*#22*5#2#1*11*1*10600*14##"])
    assert _frequency.native_value == 106.0

    installation.replay(["*#22*5#2#1*5*1*10245##"])
    assert _frequency.native_value == 102.45


def test_the_number_follows_the_tuner_with_every_amplifier_off(installation):
    """The tuner is a box of its own; no amplifier has to play for it to be tuned."""
    installation.replay(CAPTURE)

    assert all(_entity.state != PLAYING for _entity in installation.entities.values() if _entity is not installation.entity(2, 2))
    assert installation.tuner_entity("frequency").native_value == 106.0


def test_a_tuner_event_writes_the_number(installation):
    _frequency = installation.tuner_entity("frequency")
    _frequency.written_states = 0

    installation.replay(["*#22*5#2#1*11*1*10600*14##"])
    assert _frequency.written_states == 1

    # Nothing moved, so nothing is written.
    installation.replay(["*#22*5#2#1*11*1*10600*14##"])
    assert _frequency.written_states == 1


def test_a_tuner_event_of_another_source_leaves_the_number_alone():
    installation = Installation(source=lambda area, point: 1 if area == 2 else 2)
    _first = installation.tuner_entity("frequency", source=1)
    _second = installation.tuner_entity("frequency", source=2)
    _first.written_states = 0
    _second.written_states = 0

    installation.replay(["*#22*5#2#2*11*1*9730*15##"])

    assert _first.written_states == 0
    assert _second.written_states == 1
    assert _first.native_value is None
    assert _second.native_value == 97.3


def test_setting_the_number_writes_the_scratch_preset(installation):
    asyncio.run(installation.tuner_entity("frequency").async_set_native_value(101.1))

    assert installation.handler.sent == ["*#22*5#2#1*#11*1*10110*14##"]


def test_setting_the_number_uses_the_tuning_preset_of_the_gateway():
    installation = Installation(tuning_preset=3)

    asyncio.run(installation.tuner_entity("frequency").async_set_native_value(101.1))

    assert installation.handler.sent == ["*#22*5#2#1*#11*1*10110*2##"]


def test_setting_the_number_addresses_its_own_source():
    installation = Installation(amplifiers=[(2, 2, "Radio")], source=2)

    asyncio.run(installation.tuner_entity("frequency", source=2).async_set_native_value(89.7))

    assert installation.handler.sent == ["*#22*5#2#2*#11*1*8970*14##"]


def test_setting_the_number_is_reflected_before_the_bus_answers(installation):
    _frequency = installation.tuner_entity("frequency")
    _frequency.written_states = 0

    asyncio.run(_frequency.async_set_native_value(101.1))

    assert _frequency.native_value == 101.1
    assert _frequency.written_states == 1
    # The frame carries preset 14, 0-based; the tuner will report preset 15.
    assert installation.tuner[1] == {"modulation": 1, "frequency": 10110, "station": 15}


def test_the_echo_of_a_number_write_says_nothing_new(installation):
    _frequency = installation.tuner_entity("frequency")
    asyncio.run(_frequency.async_set_native_value(101.1))
    _frequency.written_states = 0
    for _entity in installation.entities.values():
        _entity.written_states = 0

    installation.replay(["*#22*5#2#1*5*1*10110##", "*#22*5#2#1*11*1*10110*15##"])

    assert _frequency.written_states == 0
    assert all(_entity.written_states == 0 for _entity in installation.entities.values())


def test_setting_the_number_refreshes_the_amplifiers_too(installation):
    for _entity in installation.entities.values():
        _entity.written_states = 0

    asyncio.run(installation.tuner_entity("frequency").async_set_native_value(97.3))

    assert all(_entity.written_states == 1 for _entity in installation.entities.values())
    assert installation.entity(7, 1).extra_state_attributes["station_name"] == "NOSTALGIE"


def test_a_number_rounded_to_the_bus_unit(installation):
    """The bus counts in hundredths of MHz; 0.05 MHz is its finest step."""
    asyncio.run(installation.tuner_entity("frequency").async_set_native_value(102.45))

    assert installation.handler.sent == ["*#22*5#2#1*#11*1*10245*14##"]
    assert installation.tuner_entity("frequency").native_value == 102.45


def test_a_number_off_the_step_is_snapped_onto_it(installation):
    """A value typed into the box is not on the grid: 87.53 MHz is not a channel."""
    asyncio.run(installation.tuner_entity("frequency").async_set_native_value(87.53))

    assert installation.handler.sent == ["*#22*5#2#1*#11*1*8755*14##"]
    assert installation.tuner_entity("frequency").native_value == 87.55


@pytest.mark.parametrize(
    ("written", "sent"),
    [
        (87.5, 8750),
        (87.51, 8750),
        (87.53, 8755),
        (99.999, 10000),
        (108.0, 10800),
    ],
)
def test_every_written_frequency_lands_on_the_step(installation, written, sent):
    asyncio.run(installation.tuner_entity("frequency").async_set_native_value(written))

    assert installation.handler.sent == [f"*#22*5#2#1*#11*1*{sent}*14##"]
    assert installation.tuner[1]["frequency"] % sound_diffusion.FREQUENCY_STEP == 0


@pytest.mark.parametrize(
    ("key", "frame"),
    [
        ("seek_up", "*22*5#*2#1##"),
        ("seek_down", "*22*6#*2#1##"),
        ("next_preset", "*22*9#*2#1##"),
        ("previous_preset", "*22*10#*2#1##"),
    ],
)
def test_the_tuner_buttons_send_the_frame_verified_on_hardware(installation, key, frame):
    asyncio.run(installation.tuner_entity(key).async_press())

    assert installation.handler.sent == [frame]


def test_the_tuner_buttons_address_their_own_source():
    installation = Installation(amplifiers=[(2, 2, "Radio")], source=3)

    asyncio.run(installation.tuner_entity("seek_up", source=3).async_press())

    assert installation.handler.sent == ["*22*5#*2#3##"]


def test_the_tuner_entities_follow_the_gateway_connection(installation):
    _entities = list(installation.tuner_entities.values())
    assert all(_entity.available is True for _entity in _entities)

    installation.handler._set_connected(False)

    assert all(_entity.available is False for _entity in _entities)
    assert all(_entity.written_states >= 1 for _entity in _entities)


def test_the_number_asks_the_tuner_when_no_amplifier_did(installation):
    asyncio.run(installation.tuner_entity("frequency").async_update())

    assert installation.handler.status_requests == ["*#22*5#2#1*11##"]


def test_the_number_does_not_ask_again_after_an_amplifier_did(installation):
    asyncio.run(installation.entity(7, 1).async_update())
    _booted = len(installation.handler.status_requests)

    asyncio.run(installation.tuner_entity("frequency").async_update())

    assert installation.handler.status_requests[_booted:] == []


def test_a_tuner_button_has_nothing_to_update(installation):
    asyncio.run(installation.tuner_entity("seek_up").async_update())

    assert installation.handler.status_requests == []


def test_a_reconnection_asks_the_tuner_once_for_every_entity_reading_it(installation):
    installation.handler._set_connected(False)

    asyncio.run(installation.handler.reconnected())

    assert installation.handler.status_requests.count("*#22*5#2#1*11##") == 1


# --------------------------------------------------------------------------- #
# The station `select` of the tuner device
# --------------------------------------------------------------------------- #


def test_the_station_select_belongs_to_the_tuner_device(installation):
    _station = installation.tuner_entity("station")
    _frequency = installation.tuner_entity("frequency")

    assert _station._attr_device_info["identifiers"] == _frequency._attr_device_info["identifiers"]
    # `has_entity_name`: "Tuner FM" + "Station" gives `select.tuner_fm_station`.
    assert _station._attr_name == "Station"
    assert _station._attr_unique_id == f"{MAC}-22-2#1-station"
    assert _station._attr_icon == "mdi:playlist-music"
    assert _station._attr_should_poll is False


def test_the_station_options_are_the_source_list_of_the_amplifiers(installation):
    assert installation.tuner_entity("station").options == installation.entity(7, 1).source_list


def test_the_station_options_follow_the_gateway_station_table():
    installation = Installation(radio_stations={"106.0": "SUD RADIO", "97.3": "NOSTALGIE"})

    assert installation.tuner_entity("station").options == ["NOSTALGIE", "SUD RADIO"]


def test_the_selected_station_is_the_one_the_tuner_is_on(installation):
    _station = installation.tuner_entity("station")
    assert _station.current_option is None

    installation.replay(["*#22*5#2#1*11*1*10600*14##"])

    assert _station.current_option == "SUD RADIO"
    assert _station.state == "SUD RADIO"


def test_the_selected_station_tolerates_the_half_step_of_the_band(installation):
    """±0.05 MHz, as `station_name` matches: 105.95 is still 106.0."""
    installation.replay(["*#22*5#2#1*5*1*10595##"])

    assert installation.tuner_entity("station").current_option == "SUD RADIO"


def test_a_frequency_the_table_does_not_carry_selects_nothing(installation):
    """A tuner between two stations has nothing to select, and says so."""
    installation.replay(["*#22*5#2#1*5*1*8830##"])

    assert installation.tuner_entity("station").current_option is None
    assert installation.tuner_entity("station").state is None


def test_selecting_a_station_on_the_select_writes_the_scratch_preset(installation):
    asyncio.run(installation.tuner_entity("station").async_select_option("FRANCE CULTURE"))

    assert installation.handler.sent == ["*#22*5#2#1*#11*1*9770*14##"]


def test_the_select_and_the_amplifier_send_the_very_same_frame(installation):
    asyncio.run(installation.tuner_entity("station").async_select_option("FRANCE CULTURE"))
    _from_the_select = list(installation.handler.sent)
    installation.handler.sent.clear()

    asyncio.run(installation.entity(7, 1).async_select_source("FRANCE CULTURE"))

    assert installation.handler.sent == _from_the_select


def test_selecting_a_station_on_the_select_is_reflected_before_the_bus_answers(installation):
    _station = installation.tuner_entity("station")
    _station.written_states = 0

    asyncio.run(_station.async_select_option("FRANCE CULTURE"))

    assert _station.current_option == "FRANCE CULTURE"
    assert _station.written_states == 1
    assert installation.tuner[1] == {"modulation": 1, "frequency": 9770, "station": 15}


def test_selecting_a_station_on_the_select_refreshes_the_amplifiers_too(installation):
    for _entity in installation.entities.values():
        _entity.written_states = 0

    asyncio.run(installation.tuner_entity("station").async_select_option("NOSTALGIE"))

    assert all(_entity.written_states == 1 for _entity in installation.entities.values())
    assert installation.entity(7, 1).extra_state_attributes["station_name"] == "NOSTALGIE"


def test_selecting_a_station_the_table_does_not_carry_is_refused_on_the_select(installation):
    with pytest.raises(ha_stubs.ServiceValidationError):
        asyncio.run(installation.tuner_entity("station").async_select_option("RADIO NULLE PART"))

    assert installation.handler.sent == []


def test_the_select_addresses_its_own_source():
    installation = Installation(amplifiers=[(2, 2, "Radio")], source=2)

    asyncio.run(installation.tuner_entity("station", source=2).async_select_option("FRANCE CULTURE"))

    assert installation.handler.sent == ["*#22*5#2#2*#11*1*9770*14##"]


def test_the_select_shows_what_the_tuner_is_on(installation):
    installation.replay(["*#22*5#2#1*11*1*10280*2##", RDS_SKYROCK])

    assert installation.tuner_entity("station").extra_state_attributes == {
        "frequency_mhz": 102.8,
        "preset": 2,
        "rds_name": "SKYROCK",
    }


def test_the_select_of_a_tuner_that_never_answered_shows_nothing(installation):
    assert installation.tuner_entity("station").extra_state_attributes == {}


def test_a_tuner_event_writes_the_select(installation):
    _station = installation.tuner_entity("station")
    _station.written_states = 0

    installation.replay(["*#22*5#2#1*11*1*10600*14##"])
    assert _station.written_states == 1

    # Nothing moved, so nothing is written.
    installation.replay(["*#22*5#2#1*11*1*10600*14##"])
    assert _station.written_states == 1


def test_a_tuner_event_of_another_source_leaves_the_select_alone():
    installation = Installation(source=lambda area, point: 1 if area == 2 else 2)
    _first = installation.tuner_entity("station", source=1)
    _second = installation.tuner_entity("station", source=2)
    _first.written_states = 0
    _second.written_states = 0

    installation.replay(["*#22*5#2#2*11*1*9730*15##"])

    assert _first.written_states == 0
    assert _second.written_states == 1
    assert _first.current_option is None
    assert _second.current_option == "NOSTALGIE"


def test_the_select_asks_the_tuner_when_nothing_else_did(installation):
    asyncio.run(installation.tuner_entity("station").async_update())

    assert installation.handler.status_requests == ["*#22*5#2#1*11##"]
    assert installation.handler.sent == ["*22*31*2#1##"]


def test_the_select_does_not_ask_again_after_an_amplifier_did(installation):
    asyncio.run(installation.entity(7, 1).async_update())
    _booted = len(installation.handler.status_requests)

    asyncio.run(installation.tuner_entity("station").async_update())

    assert installation.handler.status_requests[_booted:] == []


def test_the_select_is_there_whatever_the_amplifiers_are_doing(installation):
    """It drives the tuner, so it has nothing to do with a speaker being on."""
    installation.replay(CAPTURE)

    assert all(_entity.state != PLAYING for _entity in installation.entities.values() if _entity is not installation.entity(2, 2))
    assert installation.tuner_entity("station").current_option == "SUD RADIO"
    assert installation.tuner_entity("station").available is True


def test_the_registry_prune_rebuilds_the_unique_id_of_every_entity(installation):
    """`__init__.py` extrapolates unique ids out of `hass.data` when it prunes.

    An entity whose id it cannot rebuild is removed from the registry on every
    restart, and comes back with a `_2` suffix. The six entities of a tuner
    device therefore have to sit under keys of their own.
    """
    _platforms = installation.data[DOMAIN][MAC][const.CONF_PLATFORMS]
    _configured = []
    for _platform in _platforms:
        for _device in _platforms[_platform]:
            for _entity_name in _platforms[_platform][_device][const.CONF_ENTITIES]:
                if _entity_name != _platform:
                    _configured.append(f"{MAC}-{_device}-{_entity_name}")
                else:
                    _configured.append(f"{MAC}-{_device}")

    _live = [_entity._attr_unique_id for _entity in list(installation.entities.values()) + list(installation.tuner_entities.values())]

    assert len(set(_live)) == len(_live), "two entities cannot share a unique id"
    assert sorted(set(_live)) == sorted(set(_configured))
