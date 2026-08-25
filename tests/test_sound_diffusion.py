"""Tests for the pure-python WHO=22 (sound diffusion) parser and frame builders.

The module under test must stay importable without Home Assistant and without
OWNd, so it is loaded straight from its path instead of through the
``custom_components.myhome`` package (whose ``__init__`` pulls in HA).
"""

import importlib.util
import os
import sys

import pytest

_MODULE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "custom_components",
    "myhome",
    "sound_diffusion.py",
)
_SPEC = importlib.util.spec_from_file_location("myhome_sound_diffusion", _MODULE_PATH)
sd = importlib.util.module_from_spec(_SPEC)
# `dataclasses` resolves annotations through `sys.modules[cls.__module__]`, so
# the module has to be registered before it is executed.
sys.modules[_SPEC.name] = sd
_SPEC.loader.exec_module(sd)


# --------------------------------------------------------------------------- #
# Parsing: amplifier frames
# --------------------------------------------------------------------------- #


def test_parse_amplifier_state_on():
    event = sd.parse_sound_diffusion("*#22*3#2#2*12*1*4##")
    assert event == sd.AmplifierState(area=2, point=2, is_on=True, mmtype=4)


def test_parse_amplifier_state_off():
    event = sd.parse_sound_diffusion("*#22*3#2#1*12*0*10##")
    assert event == sd.AmplifierState(area=2, point=1, is_on=False, mmtype=10)


def test_parse_amplifier_volume():
    assert sd.parse_sound_diffusion("*#22*3#2#2*1*18##") == sd.AmplifierVolume(area=2, point=2, volume=18)
    assert sd.parse_sound_diffusion("*#22*3#2#2*1*19##") == sd.AmplifierVolume(area=2, point=2, volume=19)
    assert sd.parse_sound_diffusion("*#22*3#2#1*1*17##") == sd.AmplifierVolume(area=2, point=1, volume=17)


def test_parse_amplifier_volume_tolerates_trailing_star():
    assert sd.parse_sound_diffusion("*#22*3#2#2*1*18*##") == sd.AmplifierVolume(area=2, point=2, volume=18)


def test_parse_amplifier_on_command():
    event = sd.parse_sound_diffusion("*22*1#4#2*3#2#2##")
    assert event == sd.AmplifierCommand(area=2, point=2, what=1, params=(4, 2))
    assert (event.mmtype, event.area_param) == (4, 2)
    assert event.is_on is True


def test_parse_amplifier_on_command_second_amplifier_same_area():
    event = sd.parse_sound_diffusion("*22*1#4#2*3#2#1##")
    assert event == sd.AmplifierCommand(area=2, point=1, what=1, params=(4, 2))
    assert event.is_on is True


def test_parse_amplifier_off_command():
    """The wall command emits area 0 in the OFF frame, WHERE stays specific."""
    event = sd.parse_sound_diffusion("*22*0#4#0*3#2#1##")
    assert event == sd.AmplifierCommand(area=2, point=1, what=0, params=(4, 0))
    assert (event.mmtype, event.area_param) == (4, 0)
    assert event.is_on is False


def test_parse_amplifier_volume_up_command():
    event = sd.parse_sound_diffusion("*22*3#1*3#2#2##")
    assert event == sd.AmplifierCommand(area=2, point=2, what=3, params=(1,))
    assert event.step == 1
    assert event.mmtype is None
    assert event.is_on is None


def test_parse_amplifier_volume_down_command():
    event = sd.parse_sound_diffusion("*22*4#1*3#2#2##")
    assert event == sd.AmplifierCommand(area=2, point=2, what=4, params=(1,))
    assert event.step == 1
    assert event.is_on is None


def test_parse_amplifier_on_follow_me_and_on_source():
    assert sd.parse_sound_diffusion("*22*34#4#2*3#2#2##").is_on is True
    assert sd.parse_sound_diffusion("*22*35#4#2#1*3#2#2##").is_on is True


def test_amplifier_command_source_is_the_third_what_parameter_of_what_35():
    event = sd.parse_sound_diffusion("*22*35#4#2#1*3#2#2##")
    assert event.params == (4, 2, 1)
    assert event.source == 1
    assert event.step is None


def test_amplifier_command_source_is_none_for_other_whats():
    assert sd.parse_sound_diffusion("*22*1#4#2*3#2#2##").source is None
    assert sd.parse_sound_diffusion("*22*3#1*3#2#2##").source is None


# --------------------------------------------------------------------------- #
# Parsing: area and general commands
# --------------------------------------------------------------------------- #


def test_parse_area_command():
    event = sd.parse_sound_diffusion("*22*1#4#2*4#2##")
    assert event == sd.AreaCommand(area=2, what=1, mmtype=4)
    assert event.is_on is True


def test_parse_area_command_off():
    event = sd.parse_sound_diffusion("*22*0#4#0*4#3##")
    assert event == sd.AreaCommand(area=3, what=0, mmtype=4)
    assert event.is_on is False


@pytest.mark.parametrize("raw", ["*22*3#1*4#2##", "*22*9*4#2##", "*22*22#1*4#2##"])
def test_parse_area_command_only_handles_on_off(raw):
    """Volume or station commands addressed to an area carry no state to reflect."""
    assert sd.parse_sound_diffusion(raw) is None


@pytest.mark.parametrize(
    "raw",
    [
        "*22*0*4#2##",  # no parameters at all
        "*22*1*4#2##",
        "*22*1#4*4#2##",  # multimedia type only
        "*22*0#4#0#1*4#2##",  # one parameter too many
    ],
)
def test_parse_area_command_requires_the_full_parameter_form(raw):
    """`<what>#<mmtype>#<area>` is what the spec table shows; anything else is not it.

    A bare `*22*0*4#2##` would otherwise turn a whole area off on a frame whose
    meaning we do not know.
    """
    assert sd.parse_sound_diffusion(raw) is None


@pytest.mark.parametrize("raw", ["*22*1#4#0*0##", "*22*0#4#0*0##", "*22*0*0##"])
def test_a_general_command_is_not_modelled(raw):
    """WHERE `0` is not a sound diffusion address: general is `5#<sender>`."""
    assert sd.parse_sound_diffusion(raw) is None


# --------------------------------------------------------------------------- #
# Parsing: source frames
# --------------------------------------------------------------------------- #


def test_parse_source_on_command_is_not_an_amplifier_command():
    """`*22*1#4#2*2#1##` shares its WHAT with the amplifier ON frame."""
    event = sd.parse_sound_diffusion("*22*1#4#2*2#1##")
    assert event == sd.SourceCommand(source=1, what=1, mmtype=4, area_param=2)
    assert not isinstance(event, sd.AmplifierCommand)


def test_parse_source_routed():
    event = sd.parse_sound_diffusion("*22*2#4#2*5#2#1##")
    assert event == sd.SourceRouted(source=1, area=2, mmtype=4)


def test_parse_source_routed_what_21():
    event = sd.parse_sound_diffusion("*22*21#4#2*5#2#1##")
    assert event == sd.SourceRouted(source=1, area=2, mmtype=4)


def test_parse_source_frequency():
    event = sd.parse_sound_diffusion("*#22*5#2#1*5*1*10600##")
    assert event == sd.SourceFrequency(source=1, modulation=1, frequency=10600)


def test_parse_source_frequency_short_where():
    event = sd.parse_sound_diffusion("*#22*2#1*5*1*9730##")
    assert event == sd.SourceFrequency(source=1, modulation=1, frequency=9730)


def test_parse_source_frequency_station():
    event = sd.parse_sound_diffusion("*#22*5#2#1*11*1*10600*14##")
    assert event == sd.SourceFrequencyStation(source=1, modulation=1, frequency=10600, station=14)


def test_parse_source_frequency_station_short_where():
    event = sd.parse_sound_diffusion("*#22*2#1*11*1*10600*14##")
    assert event == sd.SourceFrequencyStation(source=1, modulation=1, frequency=10600, station=14)


def test_parse_source_station():
    assert sd.parse_sound_diffusion("*#22*2#1*6*14##") == sd.SourceStation(source=1, station=14)
    assert sd.parse_sound_diffusion("*#22*5#2#1*6*15##") == sd.SourceStation(source=1, station=15)


def test_parse_source_state():
    assert sd.parse_sound_diffusion("*#22*5#2#1*12*1*4##") == sd.SourceState(source=1, is_on=True, mmtype=4)
    assert sd.parse_sound_diffusion("*#22*2#1*12*0*10##") == sd.SourceState(source=1, is_on=False, mmtype=10)


def test_parse_capture_sequence_presets():
    """Presets seen on the bus: 14 -> 106.00, 15 -> 97.30, 1 -> 94.30."""
    assert sd.parse_sound_diffusion("*#22*5#2#1*11*1*9730*15##") == sd.SourceFrequencyStation(
        source=1, modulation=1, frequency=9730, station=15
    )
    assert sd.parse_sound_diffusion("*#22*5#2#1*11*1*9430*1##") == sd.SourceFrequencyStation(
        source=1, modulation=1, frequency=9430, station=1
    )


# --------------------------------------------------------------------------- #
# Parsing: frames that must be ignored
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "raw",
    [
        # Legacy WHO=16 duplicates emitted alongside every WHO=22 frame.
        "*16*3*22##",
        "*16*3*121##",
        "*16*13*21##",
        "*#16*22*1*18##",
        "*#16*101*6*0*106000##",
        "*#16*101*7*0*14##",
        # Dimension requests carry no value.
        "*#22*3#2#2*1##",
        "*#22*3#2#2*12##",
        "*#22*5#2#1*11##",
        "*#22*5#2#1##",
        # Station change requested from an amplifier: the resulting frequency and
        # station arrive right after as dim 5/11/6 frames, so nothing to report.
        "*22*9*5#3#2#2##",
        "*22*10*5#3#2#2##",
        # Echoes of our own dimension *writes*: `*#<dim>` is a write, not a value.
        "*#22*3#2#2*#1*18##",
        "*#22*5#2#1*#11*1*10600*14##",
        "*#22*5#2#1*#5*1*10600##",
        # Other WHOs and garbage.
        "*1*1*77##",
        "*#4*1*0*0250##",
        "",
        "not a frame",
        "*22*##",
    ],
)
def test_parse_returns_none(raw):
    assert sd.parse_sound_diffusion(raw) is None


def test_parse_accepts_trailing_whitespace():
    assert sd.parse_sound_diffusion(" *#22*3#2#2*1*18## ") == sd.AmplifierVolume(area=2, point=2, volume=18)


# --------------------------------------------------------------------------- #
# Device id helper
# --------------------------------------------------------------------------- #


def test_amplifier_device_id():
    assert sd.amplifier_device_id(2, 2) == "22-3#2#2"
    assert sd.amplifier_device_id(7, 1) == "22-3#7#1"


def test_amplifier_device_id_matches_the_parsed_event():
    event = sd.parse_sound_diffusion("*#22*3#6#2*12*1*4##")
    assert sd.amplifier_device_id(event.area, event.point) == "22-3#6#2"


# --------------------------------------------------------------------------- #
# Builders
# --------------------------------------------------------------------------- #


def test_amplifier_on_simple():
    assert sd.amplifier_on_simple(2, 2) == "*22*1#4#2*3#2#2##"
    assert sd.amplifier_on_simple(7, 1) == "*22*1#4#7*3#7#1##"


def test_amplifier_on_with_source():
    assert sd.amplifier_on(2, 2) == "*22*35#4#2#1*3#2#2##"
    assert sd.amplifier_on(3, 1, source=2) == "*22*35#4#3#2*3#3#1##"


def test_amplifier_off():
    assert sd.amplifier_off(2, 1) == "*22*0#4#2*3#2#1##"


def test_amplifier_off_bus():
    """Exact form captured on the bus (area 0)."""
    assert sd.amplifier_off_bus(2, 1) == "*22*0#4#0*3#2#1##"


def test_volume_up_down():
    assert sd.volume_up(2, 2) == "*22*3#1*3#2#2##"
    assert sd.volume_down(2, 2) == "*22*4#1*3#2#2##"
    assert sd.volume_up(6, 1, step=3) == "*22*3#3*3#6#1##"
    assert sd.volume_down(6, 1, step=3) == "*22*4#3*3#6#1##"


def test_volume_set():
    assert sd.volume_set(2, 2, 18) == "*#22*3#2#2*#1*18##"
    assert sd.volume_set(7, 1, 0) == "*#22*3#7#1*#1*0##"
    assert sd.volume_set(7, 1, 31) == "*#22*3#7#1*#1*31##"


def test_volume_set_clamps():
    assert sd.volume_set(7, 1, -5) == "*#22*3#7#1*#1*0##"
    assert sd.volume_set(7, 1, 99) == "*#22*3#7#1*#1*31##"


def test_station_next_previous_spec_form():
    assert sd.station_next() == "*22*9#*2#1##"
    assert sd.station_previous() == "*22*10#*2#1##"
    assert sd.station_next(source=2) == "*22*9#*2#2##"


def test_station_next_previous_from_amplifier():
    assert sd.station_next_from_amplifier(2, 2) == "*22*9*5#3#2#2##"
    assert sd.station_previous_from_amplifier(2, 2) == "*22*10*5#3#2#2##"


def test_frequency_seek():
    assert sd.frequency_seek_up() == "*22*5#*2#1##"
    assert sd.frequency_seek_down() == "*22*6#*2#1##"
    assert sd.frequency_seek_up(source=1, step=5) == "*22*5#5*2#1##"
    assert sd.frequency_seek_down(source=1, step=5) == "*22*6#5*2#1##"


def test_store_station():
    assert sd.store_station(1, 14) == "*22*33#14*2#1##"


def test_set_frequency():
    assert sd.set_frequency(1, 10600, 14) == "*#22*5#2#1*#11*1*10600*14##"
    assert sd.set_frequency(1, 9730, 15, modulation=1) == "*#22*5#2#1*#11*1*9730*15##"


def test_requests():
    assert sd.request_amplifier_state(2, 2) == "*#22*3#2#2*12##"
    assert sd.request_amplifier_volume(2, 2) == "*#22*3#2#2*1##"
    assert sd.request_source_frequency_station(1) == "*#22*5#2#1*11##"
    assert sd.request_source_frequency(1) == "*#22*5#2#1*5##"
    assert sd.request_global_status() == "*#22*5#2#1##"


def test_builders_round_trip_through_the_parser():
    """Every builder that produces an event-shaped frame must parse back."""
    assert sd.parse_sound_diffusion(sd.amplifier_on_simple(2, 2)) == sd.AmplifierCommand(
        area=2, point=2, what=1, params=(4, 2)
    )
    assert sd.parse_sound_diffusion(sd.amplifier_off_bus(2, 1)) == sd.AmplifierCommand(
        area=2, point=1, what=0, params=(4, 0)
    )
    assert sd.parse_sound_diffusion(sd.amplifier_on(2, 2, source=1)).source == 1
    assert sd.parse_sound_diffusion(sd.volume_up(2, 2)).what == 3


# --------------------------------------------------------------------------- #
# Station table helpers
# --------------------------------------------------------------------------- #


def test_station_name_exact():
    assert sd.station_name(10600) == "SUD RADIO"
    assert sd.station_name(9730) == "NOSTALGIE"
    assert sd.station_name(9430) == "EUROPE 2"
    assert sd.station_name(8770) == "MOUV'"
    assert sd.station_name(10730) == "BFM BUSINESS"


def test_station_name_within_tolerance():
    assert sd.station_name(10605) == "SUD RADIO"
    assert sd.station_name(10595) == "SUD RADIO"


def test_station_name_outside_tolerance():
    assert sd.station_name(10610) is None
    assert sd.station_name(8000) is None


def test_format_frequency():
    assert sd.format_frequency(10600) == "106.0 MHz"
    assert sd.format_frequency(9730) == "97.3 MHz"
    assert sd.format_frequency(8770) == "87.7 MHz"
    assert sd.format_frequency(10600, sd.MODULATION_FM) == "106.0 MHz"


def test_format_frequency_keeps_two_decimals_when_needed():
    assert sd.format_frequency(10245) == "102.45 MHz"
    assert sd.format_frequency(10001) == "100.01 MHz"


def test_format_frequency_is_khz_for_every_am_band():
    assert sd.format_frequency(10600, sd.MODULATION_AM_LW) == "10600 kHz"
    assert sd.format_frequency(10600, sd.MODULATION_AM_MW) == "10600 kHz"
    assert sd.format_frequency(10600, sd.MODULATION_AM_SW) == "10600 kHz"


def test_format_frequency_of_none():
    assert sd.format_frequency(None) is None


def test_station_name_with_a_custom_table():
    table = {10600: "MA RADIO", 9010: "AUTRE"}
    assert sd.station_name(10600, table) == "MA RADIO"
    assert sd.station_name(10602, table) == "MA RADIO"
    assert sd.station_name(9730, table) is None
    # The built-in table is untouched by the override.
    assert sd.station_name(9730) == "NOSTALGIE"


def test_station_name_with_an_empty_table():
    assert sd.station_name(10600, {}) is None


def test_stations_table_is_consistent():
    assert len(sd.STATIONS) == 35
    assert all(isinstance(key, int) for key in sd.STATIONS)
    assert sd.STATIONS[10600] == "SUD RADIO"
