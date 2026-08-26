"""End to end dispatch for video door entry: raw WHO=8 frames in, entity states out.

Home Assistant is stubbed (see `ha_stubs`); everything else is the real code:
`gateway.handle_video_door_entry`, the WHO=8 parser, `event.MyHOMEDoorbell` and
`binary_sensor.MyHOMEVideoDoorEntryCall`.

The frames are captured from a test installation (F454, entrance panel 20,
indoor unit 21, gate strike on activation address 20).
"""

import os
import sys
import types

import pytest
import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ha_stubs  # noqa: E402

const = ha_stubs.load("const")
validate = ha_stubs.load("validate")
gateway = ha_stubs.load("gateway")
event = ha_stubs.load("event")
binary_sensor = ha_stubs.load("binary_sensor")

DOMAIN = const.DOMAIN
MAC = "00:03:50:11:22:33"

# The real call sequence, in the order the bus emitted it.
RING = "*8*1#1#4#21*4##"
CALLER_ID = "*8*9#1#4*20##"
AUTO_ON = "*8*1#5#4#20*10##"
SESSION_END = "*8*3#1#4*410##"      # end of a call (kind 1): drops the sensor
VIEW_END = "*8*3#5#4*420##"         # end of an auto-on (kind 5): must not drop it
LOCK_ON = "*8*19*20##"
LOCK_OFF = "*8*20*20##"


class FakeGateway(gateway.MyHOMEGatewayHandler):
    """The real handler, without the config entry and the sockets."""

    def __init__(self, hass):
        self.hass = hass
        self.is_connected = True
        self.generate_events = False
        self.gateway = types.SimpleNamespace(serial=MAC, log_id="[test]", host="192.168.0.10")
        self.sent = []


def configuration_file(with_panel=True, with_camera=False) -> str:
    _lines = [
        "house:",
        f'  mac: "{MAC}"',
        "  media_player:",
        '    ampli_2_2: { where: "3#2#2", name: "Radio", source: 1 }',
    ]
    if with_panel:
        _lines += [
            "  video_door_entry:",
            "    entrance_panel:",
            '      name: "Portillon"',
            "      entrance_address: 20",
        ]
        if with_camera:
            _lines.append('      camera_password: "deadbeef"')
    return "\n".join(_lines) + "\n"


class Installation:
    """A stubbed `hass` holding one gateway and its video door entry entities."""

    def __init__(self, with_panel=True, with_camera=False):
        self.data = {DOMAIN: validate.config_schema(yaml.safe_load(configuration_file(with_panel, with_camera)))}
        self.handler = FakeGateway(self)
        self.data[DOMAIN][MAC][const.CONF_ENTITY] = self.handler
        self._platforms = self.data[DOMAIN][MAC][const.CONF_PLATFORMS]

        self.doorbell = None
        self.call = None
        if with_panel:
            _event_device_id, _event_device = next(iter(self._platforms["event"].items()))
            self.doorbell = event.MyHOMEDoorbell(
                hass=self,
                device_id=_event_device_id,
                who=_event_device[const.CONF_WHO],
                where=_event_device[const.CONF_WHERE],
                name=_event_device["name"],
                entity_name=_event_device[const.CONF_ENTITY_NAME],
                manufacturer=_event_device[const.CONF_MANUFACTURER],
                model=_event_device[const.CONF_DEVICE_MODEL],
                gateway=self.handler,
            )
            self.doorbell.hass = self
            _event_device[const.CONF_ENTITIES]["event"] = self.doorbell

            _sensor_device_id, _sensor_device = next(iter(self._platforms["binary_sensor"].items()))
            self.call = binary_sensor.MyHOMEVideoDoorEntryCall(
                hass=self,
                device_id=_sensor_device_id,
                who=_sensor_device[const.CONF_WHO],
                where=_sensor_device[const.CONF_WHERE],
                name=_sensor_device["name"],
                entity_name=_sensor_device[const.CONF_ENTITY_NAME],
                call_timeout=_sensor_device[const.CONF_CALL_TIMEOUT],
                manufacturer=_sensor_device[const.CONF_MANUFACTURER],
                model=_sensor_device[const.CONF_DEVICE_MODEL],
                gateway=self.handler,
            )
            self.call.hass = self
            _sensor_device[const.CONF_ENTITIES]["call"] = self.call

    def rings(self) -> int:
        return len(getattr(self.doorbell, "triggered_events", []))

    def replay(self, frames):
        for _frame in frames:
            self.handler.handle_video_door_entry(_frame)


@pytest.fixture(name="installation")
def installation_fixture():
    return Installation()


# --------------------------------------------------------------------------- #
# The ring, and the auto-on that must not be one
# --------------------------------------------------------------------------- #


def test_a_ring_fires_the_doorbell_once(installation):
    installation.replay([RING])
    assert installation.rings() == 1
    assert installation.doorbell.last_event_type == "ring"
    assert installation.call.is_on is True


def test_an_auto_on_does_not_fire_the_doorbell(installation):
    installation.replay([AUTO_ON])
    assert installation.rings() == 0
    assert installation.call.is_on is False


def test_the_caller_id_and_the_lock_echo_do_not_fire_the_doorbell(installation):
    installation.replay([CALLER_ID, LOCK_ON, LOCK_OFF])
    assert installation.rings() == 0


def test_replaying_the_real_sequence(installation):
    """Ring, caller id, an auto-on, then the session end.

    The doorbell rings exactly once, the sensor goes on with the ring and off
    with the session end, and the auto-on in the middle rings nothing.
    """
    installation.handler.handle_video_door_entry(RING)
    assert installation.rings() == 1
    assert installation.call.is_on is True

    installation.handler.handle_video_door_entry(CALLER_ID)
    installation.handler.handle_video_door_entry(AUTO_ON)
    assert installation.rings() == 1, "the auto-on did not ring"
    assert installation.call.is_on is True

    installation.handler.handle_video_door_entry(SESSION_END)
    assert installation.rings() == 1
    assert installation.call.is_on is False


def test_a_second_ring_fires_again(installation):
    installation.replay([RING, SESSION_END, RING])
    assert installation.rings() == 2
    assert installation.call.is_on is True


# --------------------------------------------------------------------------- #
# Configured vs not
# --------------------------------------------------------------------------- #


def test_a_gateway_without_a_panel_does_not_handle_the_frame():
    installation = Installation(with_panel=False)
    assert installation.handler.handle_video_door_entry(RING) is False


def test_a_configured_gateway_handles_even_a_frame_it_ignores(installation):
    """A frame that parses to nothing is still "handled": no debug spam, no ring."""
    assert installation.handler.handle_video_door_entry("*8*100#5#4*20##") is True
    assert installation.rings() == 0
    assert installation.call.is_on is False


def test_dispatch_after_the_config_entry_was_unloaded_does_not_raise(installation):
    del installation.data[DOMAIN][MAC]
    assert installation.handler.handle_video_door_entry(RING) is False


def test_dispatch_while_the_config_entry_is_being_reloaded_does_not_raise(installation):
    installation.data[DOMAIN][MAC] = {}
    assert installation.handler.handle_video_door_entry(RING) is False


# --------------------------------------------------------------------------- #
# Entity details
# --------------------------------------------------------------------------- #


def test_the_doorbell_declares_the_doorbell_device_class(installation):
    assert installation.doorbell.device_class == ha_stubs.EventDeviceClass.DOORBELL
    assert installation.doorbell.event_types == ["ring"]
    assert installation.doorbell._attr_unique_id == f"{MAC}-8-20"


def test_the_call_sensor_is_a_running_sensor(installation):
    assert installation.call.device_class == ha_stubs.BinarySensorDeviceClass.RUNNING
    assert installation.call._attr_unique_id == f"{MAC}-8-20-call"


def test_two_panels_on_the_same_entrance_address_are_refused():
    """They would key onto one device id and one would be silently dropped."""
    _cfg = (
        "house:\n"
        f'  mac: "{MAC}"\n'
        "  video_door_entry:\n"
        "    gate: { name: Gate, entrance_address: 20 }\n"
        "    door: { name: Door, entrance_address: 20 }\n"
    )
    with pytest.raises(Exception):
        validate.config_schema(yaml.safe_load(_cfg))


def test_two_panels_on_different_addresses_are_both_kept():
    _cfg = (
        "house:\n"
        f'  mac: "{MAC}"\n'
        "  video_door_entry:\n"
        "    gate: { name: Gate, entrance_address: 20 }\n"
        "    door: { name: Door, entrance_address: 21 }\n"
    )
    _platforms = validate.config_schema(yaml.safe_load(_cfg))[MAC]["platforms"]
    assert sorted(_platforms["event"].keys()) == ["8-20", "8-21"]


def test_the_camera_platform_appears_only_with_a_password():
    without = Installation(with_panel=True, with_camera=False)
    assert "camera" not in without._platforms

    withcam = Installation(with_panel=True, with_camera=True)
    assert list(withcam._platforms["camera"].keys()) == ["8-20"]


# --------------------------------------------------------------------------- #
# The call sensor's safety timeout, and the call-vs-view session end
# --------------------------------------------------------------------------- #


class _Timer:
    """Captures `async_call_later` calls and the cancels it hands out.

    The real helper schedules a callback on the loop and returns a cancel
    callable; here nothing is scheduled — a test fires the captured action by
    hand — and every cancel handed out records that it was called.
    """

    def __init__(self):
        self.scheduled = []  # (delay, action) per arm
        self.cancelled = 0

    def schedule(self, hass, delay, action):
        self.scheduled.append((delay, action))

        def _cancel():
            self.cancelled += 1

        return _cancel


def test_the_safety_timeout_takes_the_call_off(installation, monkeypatch):
    """No session end arrives; the timeout drops the call on its own."""
    _timer = _Timer()
    monkeypatch.setattr(binary_sensor, "async_call_later", _timer.schedule)

    installation.replay([RING])
    assert installation.call.is_on is True

    (_delay, _action), = _timer.scheduled
    assert _delay == 60  # the default call_timeout
    _action(None)  # fire it as the loop would
    assert installation.call.is_on is False


def test_a_second_ring_does_not_stack_timeouts(installation, monkeypatch):
    """A re-ring cancels the first timeout before arming the next one."""
    _timer = _Timer()
    monkeypatch.setattr(binary_sensor, "async_call_later", _timer.schedule)

    installation.replay([RING, RING])
    assert len(_timer.scheduled) == 2
    assert _timer.cancelled == 1


def test_a_call_end_cancels_the_timeout(installation, monkeypatch):
    _timer = _Timer()
    monkeypatch.setattr(binary_sensor, "async_call_later", _timer.schedule)

    installation.replay([RING, SESSION_END])
    assert installation.call.is_on is False
    assert _timer.cancelled == 1


def test_a_view_end_does_not_take_the_call_off(installation, monkeypatch):
    """`*8*3#5#…` (kind 5) closes an auto-on and must not drop a live call."""
    _timer = _Timer()
    monkeypatch.setattr(binary_sensor, "async_call_later", _timer.schedule)

    installation.replay([RING, VIEW_END])
    assert installation.call.is_on is True
    # The timeout is left armed: only a call end (or the timeout) may drop it.
    assert _timer.cancelled == 0
