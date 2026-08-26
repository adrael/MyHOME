"""OpenWebNet WHO=8 (video door entry) parsing and frame building.

OWNd 0.7.48 does not model WHO=8 (nor WHO=6 or 7): ``OWNEvent.parse`` returns
the raw string for every ``*8*…`` / ``*#8*…`` event. Everything WHO=8 specific
therefore lives here, and this module — like ``sound_diffusion.py`` — is free of
any Home Assistant or OWNd import so it can be imported and tested on its own.

The frames were captured on the installation this fork was written against
(gateway F454, entrance panel 20, indoor unit 21, gate strike on activation
address 20, 2026-08-26). No address is hard-coded into the integration: the
entrance, lock and camera addresses all come from the configuration file, and
the numbers here are only defaults.

Two frames look alike and mean opposite things:

* ``*8*1#1#<mm>#<iu>*<x>##`` is a **ring** — someone pressed the doorbell;
* ``*8*1#5#<mm>#<area>*<x>##`` is an **auto-on** — someone is looking at the
  camera, and nothing rang.

The second field after ``1#`` is the discriminator: ``1`` is a call, ``5`` is a
view. Reading a view as a ring would fire the doorbell every time the panel is
watched, so the two parse to different types and only the ring feeds the event
entity.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, Union

#: Default entrance-panel address, and the default gate-strike activation
#: address. Both are configurable; 20 is what the reference installation uses.
DEFAULT_ENTRANCE_ADDRESS = 20

#: Default camera WHERE for the WHO=7 activation frame: ``4000`` is camera 0.
DEFAULT_CAMERA_WHERE = 4000


# --------------------------------------------------------------------------- #
# Events
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class DoorbellRing:
    """``*8*1#1#<mm>#<iu>*<x>##`` — the doorbell was pressed.

    ``entrance`` is the WHERE of the frame (``<x>``), **not** the entrance-panel
    address: the ring does not carry it. The panel identity arrives a moment
    later in a :class:`CallerId` frame, so a ring must never be matched against a
    configured ``entrance_address``.
    """

    entrance: int
    iu: int
    mmtype: int


@dataclass(frozen=True)
class AutoOn:
    """``*8*1#5#<mm>#<area>*<x>##`` — a camera view, not a ring.

    ``area`` is the entrance-panel address the view is of (20 on the reference
    installation). Kept apart from :class:`DoorbellRing` on purpose: only the
    ring rings.
    """

    area: int
    mmtype: int


@dataclass(frozen=True)
class CallerId:
    """``*8*9#1#<mm>*<ep>##`` — which entrance panel is calling.

    ``entrance`` is the panel address (``<ep>``): this is the only event whose
    ``entrance`` is the configured ``entrance_address``.
    """

    entrance: int


@dataclass(frozen=True)
class SessionEnd:
    """``*8*3#<kind>#<mm>*<addr>##`` — an audio/video session ended.

    ``kind`` is ``1`` after a call and ``5`` after a view. Either way it is the
    signal that the call-in-progress sensor can go off.
    """

    kind: int
    mmtype: int
    address: int


@dataclass(frozen=True)
class LockPulse:
    """``*8*19*<a>##`` (on) / ``*8*20*<a>##`` (release) — the strike moved.

    Emitted as an echo when the gate is opened, from Home Assistant or from the
    panel; ``address`` is the activation address.
    """

    address: int
    on: bool


VideoDoorEntryEvent = Union[DoorbellRing, AutoOn, CallerId, SessionEnd, LockPulse]

#: Event types that ring the doorbell entity.
RING_EVENTS = (DoorbellRing,)

#: Event types that end a call, taking the call-in-progress sensor off.
SESSION_END_EVENTS = (SessionEnd,)


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #

# Anchored on the WHAT shape: a ring and a view share the leading `1#` and only
# the second field (1 = call, 5 = view) tells them apart.
_RING = re.compile(r"^\*8\*1#1#(?P<mm>\d+)#(?P<iu>\d+)\*(?P<x>\d+)##$")
_AUTO_ON = re.compile(r"^\*8\*1#5#(?P<mm>\d+)#(?P<area>\d+)\*(?P<x>\d+)##$")
_CALLER_ID = re.compile(r"^\*8\*9#1#(?P<mm>\d+)\*(?P<ep>\d+)##$")
_SESSION_END = re.compile(r"^\*8\*3#(?P<kind>\d+)#(?P<mm>\d+)\*(?P<addr>\d+)##$")
_LOCK_ON = re.compile(r"^\*8\*19\*(?P<a>\d+)##$")
_LOCK_OFF = re.compile(r"^\*8\*20\*(?P<a>\d+)##$")


def parse_video_door_entry(raw: str) -> Optional[VideoDoorEntryEvent]:
    """Parse a WHO=8 frame, returning ``None`` when it carries nothing to act on.

    ``None`` is returned for the WHO=6 legacy mirror frames and the WHO=7 camera
    frames, for the visualisation variant ``*8*2#1#…##``, for the observed but
    unexplained ``*8*100#…##``, for the ``*#8**35*…##`` indoor-unit status, and
    for anything that is not a WHO=8 command frame.
    """
    if not raw:
        return None

    raw = raw.strip()

    _match = _RING.match(raw)
    if _match:
        return DoorbellRing(
            entrance=int(_match.group("x")),
            iu=int(_match.group("iu")),
            mmtype=int(_match.group("mm")),
        )

    _match = _AUTO_ON.match(raw)
    if _match:
        return AutoOn(
            area=int(_match.group("area")),
            mmtype=int(_match.group("mm")),
        )

    _match = _CALLER_ID.match(raw)
    if _match:
        return CallerId(entrance=int(_match.group("ep")))

    _match = _SESSION_END.match(raw)
    if _match:
        return SessionEnd(
            kind=int(_match.group("kind")),
            mmtype=int(_match.group("mm")),
            address=int(_match.group("addr")),
        )

    _match = _LOCK_ON.match(raw)
    if _match:
        return LockPulse(address=int(_match.group("a")), on=True)

    _match = _LOCK_OFF.match(raw)
    if _match:
        return LockPulse(address=int(_match.group("a")), on=False)

    return None


# --------------------------------------------------------------------------- #
# Frame builders
# --------------------------------------------------------------------------- #


def open_lock(address: int) -> tuple:
    """The two frames that open the gate strike, in the order to send them.

    Verified on hardware: the web ``videoControlGate_open`` put ``*8*19*20##``
    on the bus. The strike is a pulse — energise, then release — so this returns
    both frames; send them in order (the sending workers are FIFO with the
    default single worker).
    """
    return (f"*8*19*{address}##", f"*8*20*{address}##")


def stair_light_on(address: int) -> str:
    """Turn the staircase light on (``*8*21*<a>##``). Not verified on hardware."""
    return f"*8*21*{address}##"


def stair_light_off(address: int) -> str:
    """Turn the staircase light off (``*8*22*<a>##``). Not verified on hardware."""
    return f"*8*22*{address}##"


def activate_camera(where: int = DEFAULT_CAMERA_WHERE) -> str:
    """Start a video session so a snapshot can be pulled (``*7*0*<where>##``).

    ``where`` is ``4000`` plus the camera number. The camera stream is only live
    while a session is open — a call, or this frame — so a snapshot is taken
    right after sending it. Verified on hardware: ``*7*0*4000##`` opened the
    session and ``telecamera.php`` then returned a live frame.
    """
    return f"*7*0*{where}##"
