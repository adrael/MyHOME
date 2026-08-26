"""Tests for the pure-python WHO=8 (video door entry) parser and frame builders.

Loaded straight from its path, like ``test_sound_diffusion.py``: the module
under test must stay importable without Home Assistant and without OWNd.

Every frame below is from the capture of the villa this fork was written
against (F454, entrance panel 20, indoor unit 21, gate strike on activation
address 20), and is the ground truth the parser is measured against.
"""

import importlib.util
import os
import sys

_MODULE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "custom_components",
    "myhome",
    "video_door_entry.py",
)
_SPEC = importlib.util.spec_from_file_location("myhome_video_door_entry", _MODULE_PATH)
vde = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = vde
_SPEC.loader.exec_module(vde)


# --------------------------------------------------------------------------- #
# Parsing: a doorbell ring vs an auto-on (the distinction that matters)
# --------------------------------------------------------------------------- #


def test_parse_doorbell_ring():
    """`*8*1#1#…` is a ring; the `1#1#` (call) is what tells it from a view."""
    event = vde.parse_video_door_entry("*8*1#1#4#21*4##")
    assert event == vde.DoorbellRing(entrance=4, iu=21, mmtype=4)


def test_parse_auto_on_is_not_a_ring():
    """`*8*1#5#…` is somebody looking at the camera, not a sonnette."""
    event = vde.parse_video_door_entry("*8*1#5#4#20*10##")
    assert event == vde.AutoOn(area=20, mmtype=4)
    assert not isinstance(event, vde.DoorbellRing)


def test_a_ring_and_an_auto_on_are_different_types():
    _ring = vde.parse_video_door_entry("*8*1#1#4#21*4##")
    _view = vde.parse_video_door_entry("*8*1#5#4#20*10##")
    assert type(_ring) is vde.DoorbellRing
    assert type(_view) is vde.AutoOn


# --------------------------------------------------------------------------- #
# Parsing: the other frames of a call
# --------------------------------------------------------------------------- #


def test_parse_caller_id_carries_the_panel_address():
    """Only `CallerId.entrance` is the entrance-panel address (20 here)."""
    event = vde.parse_video_door_entry("*8*9#1#4*20##")
    assert event == vde.CallerId(entrance=20)


def test_the_ring_does_not_carry_the_panel_address():
    """The ring's `entrance` is its WHERE (4), not the panel (20).

    The panel identity arrives in the separate caller-id frame; a ring cannot be
    matched to a configured `entrance_address` and must not be compared to one.
    """
    assert vde.parse_video_door_entry("*8*1#1#4#21*4##").entrance == 4
    assert vde.parse_video_door_entry("*8*9#1#4*20##").entrance == 20


def test_parse_session_end_after_a_call():
    assert vde.parse_video_door_entry("*8*3#1#4*410##") == vde.SessionEnd(kind=1, mmtype=4, address=410)


def test_parse_session_end_after_a_view():
    assert vde.parse_video_door_entry("*8*3#5#4*420##") == vde.SessionEnd(kind=5, mmtype=4, address=420)


def test_parse_lock_pulse_on():
    assert vde.parse_video_door_entry("*8*19*20##") == vde.LockPulse(address=20, on=True)


def test_parse_lock_pulse_release():
    assert vde.parse_video_door_entry("*8*20*20##") == vde.LockPulse(address=20, on=False)


def test_lock_pulse_reads_an_arbitrary_activation_address():
    assert vde.parse_video_door_entry("*8*19*11##") == vde.LockPulse(address=11, on=True)


# --------------------------------------------------------------------------- #
# Parsing: frames that carry nothing to act on
# --------------------------------------------------------------------------- #


def test_the_view_variant_is_ignored():
    """`*8*2#1#4*10##` — a visualisation variant with no area; not a ring."""
    assert vde.parse_video_door_entry("*8*2#1#4*10##") is None


def test_the_observed_unknown_frame_is_ignored():
    """`*8*100#5#4*20##` — observed, meaning unknown; a rejection by decision."""
    assert vde.parse_video_door_entry("*8*100#5#4*20##") is None


def test_the_iu_status_dimension_is_ignored():
    assert vde.parse_video_door_entry("*#8**35*0*0*0##") is None


def test_who_six_and_seven_are_ignored():
    """WHO=6 mirror frames and WHO=7 camera frames parse to nothing here."""
    assert vde.parse_video_door_entry("*6*10*4000##") is None
    assert vde.parse_video_door_entry("*6*23*4000##") is None
    assert vde.parse_video_door_entry("*7*0*4000##") is None
    assert vde.parse_video_door_entry("*#7*1*0##") is None


def test_empty_and_junk_are_ignored():
    assert vde.parse_video_door_entry("") is None
    assert vde.parse_video_door_entry("not a frame") is None
    assert vde.parse_video_door_entry("*22*1#4#2*3#2#2##") is None


# --------------------------------------------------------------------------- #
# Frame builders
# --------------------------------------------------------------------------- #


def test_open_lock_is_the_two_frames_the_bus_produced():
    """Verified on hardware: the web `videoControlGate_open` put `*8*19*20##`
    on the bus. The strike is a pulse: energise, then release."""
    assert vde.open_lock(20) == ("*8*19*20##", "*8*20*20##")


def test_open_lock_takes_the_activation_address():
    assert vde.open_lock(11) == ("*8*19*11##", "*8*20*11##")


def test_activate_camera_defaults_to_4000():
    assert vde.activate_camera() == "*7*0*4000##"


def test_activate_camera_takes_a_where():
    assert vde.activate_camera(4001) == "*7*0*4001##"


def test_stair_light_builders():
    assert vde.stair_light_on(20) == "*8*21*20##"
    assert vde.stair_light_off(20) == "*8*22*20##"
