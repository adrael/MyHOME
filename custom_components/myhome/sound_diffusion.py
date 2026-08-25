"""OpenWebNet WHO=22 (sound diffusion) parsing and frame building.

OWNd 0.7.48 does not model WHO=22: ``OWNEvent.parse`` returns the raw string for
every ``*22*…`` / ``*#22*…`` event, and dimension *requests* come back as a
generic ``OWNCommand``. Everything WHO=22 specific therefore lives here.

This module is deliberately free of any Home Assistant or OWNd import so it can
be imported and tested on its own.

Addressing (Legrand WHO_22 v1.1):
    source              ``2#<source>``
    amplifier           ``3#<area>#<point>``
    area                ``4#<area>``
    general / emitter   ``5#<emitter address>``
    all sources         ``6``
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, Union

#: Highest volume value accepted by an amplifier (dimension 1).
MAX_VOLUME = 31

#: Multimedia type used by every command issued by this integration (stereo).
MMTYPE_STEREO = 4

#: Modulation values carried by dimensions 5 and 11 (Legrand WHO_22 v1.1).
MODULATION_FM = 1
MODULATION_AM_LW = 2
MODULATION_AM_MW = 3
MODULATION_AM_SW = 4

#: Tolerance, in hundredths of MHz, when matching a frequency to a station name.
STATION_MATCH_TOLERANCE = 5

#: FM band around Bordeaux, keyed by frequency in hundredths of MHz.
#: Mirrors ``STATIONS`` in the villa-marques dashboard configuration.
STATIONS = {
    8770: "MOUV'",
    8810: "RADIO CAMPUS",
    8850: "M RADIO",
    8890: "RCF",
    8970: "FRANCE INTER",
    9010: "LA CLÉ DES ONDES",
    9070: "RIG",
    9130: "O2 RADIO",
    9180: "FUN RADIO",
    9220: "RADIO CLASSIQUE",
    9260: "ENJOY 33",
    9350: "FRANCE MUSIQUE",
    9430: "EUROPE 2",
    9490: "NOVA",
    9530: "CHÉRIE FM",
    9620: "ARL",
    9670: "FIP",
    9730: "NOSTALGIE",
    9770: "FRANCE CULTURE",
    9820: "RIRE & CHANSONS",
    9960: "RFM",
    10010: "FRANCE BLEU",
    10080: "WIT FM",
    10240: "NRJ",
    10280: "SKYROCK",
    10330: "FOREVER",
    10370: "BLACK BOX",
    10420: "RMC",
    10460: "EUROPE 1",
    10510: "RTL",
    10550: "FRANCE INFO",
    10600: "SUD RADIO",
    10640: "RADIO ORIENT",
    10680: "RTL 2",
    10730: "BFM BUSINESS",
}


# --------------------------------------------------------------------------- #
# Addressing
# --------------------------------------------------------------------------- #


def amplifier_device_id(area: int, point: int) -> str:
    """Key an amplifier is stored under in ``hass.data``.

    It has to match what ``validate.py`` builds out of the configuration file,
    which is ``f"{who}-{where}"`` with the WHERE normalised to ``3#<area>#<point>``.
    """
    return f"22-3#{area}#{point}"


# --------------------------------------------------------------------------- #
# Events
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class AmplifierState:
    """``*#22*3#<a>#<p>*12*<state>*<mmtype>##`` — amplifier status (dimension 12)."""

    area: int
    point: int
    is_on: bool
    mmtype: int


@dataclass(frozen=True)
class AmplifierVolume:
    """``*#22*3#<a>#<p>*1*<volume>##`` — amplifier volume (dimension 1)."""

    area: int
    point: int
    volume: int


@dataclass(frozen=True)
class AmplifierCommand:
    """``*22*<what>[#<param>…]*3#<a>#<p>##`` — command addressed to one amplifier.

    Reflecting these lets an entity update immediately instead of waiting for the
    dimension 12 reply that the bus sends a moment later.

    The WHAT parameters are kept raw in ``params`` because their meaning depends
    on the WHAT: ``1#<mmtype>#<area>`` for on/off, ``3#<step>`` for volume,
    ``35#<mmtype>#<area>#<source>`` for "on, on that source".
    """

    area: int
    point: int
    what: int
    params: tuple = ()

    #: WHATs whose first parameter is the multimedia type.
    _MMTYPE_WHATS = (0, 1, 2, 21, 34, 35)
    #: WHATs whose first parameter is a volume step.
    _STEP_WHATS = (3, 4)

    @property
    def is_on(self) -> Optional[bool]:
        """``True``/``False`` for the on/off WHATs, ``None`` when unrelated."""
        if self.what in (1, 34, 35):
            return True
        if self.what == 0:
            return False
        return None

    @property
    def mmtype(self) -> Optional[int]:
        """Multimedia type, when the WHAT carries one."""
        if self.what in self._MMTYPE_WHATS and len(self.params) > 0:
            return self.params[0]
        return None

    @property
    def area_param(self) -> Optional[int]:
        """Area repeated in the WHAT parameters (0 in the OFF frames of the bus)."""
        if self.what in self._MMTYPE_WHATS and len(self.params) > 1:
            return self.params[1]
        return None

    @property
    def source(self) -> Optional[int]:
        """Source selected by WHAT 35 (``35#<mmtype>#<area>#<source>``)."""
        if self.what == 35 and len(self.params) > 2:
            return self.params[2]
        return None

    @property
    def step(self) -> Optional[int]:
        """Volume step of WHAT 3 (up) and 4 (down)."""
        if self.what in self._STEP_WHATS and len(self.params) > 0:
            return self.params[0]
        return None


@dataclass(frozen=True)
class SourceCommand:
    """``*22*<what>[#<param>…]*2#<source>##`` — command addressed to a source.

    ``*22*1#4#2*2#1##`` shares its WHAT with the amplifier ON frame and only the
    WHERE tells them apart, hence the separate type.
    """

    source: int
    what: int
    mmtype: Optional[int]
    area_param: Optional[int]

    @property
    def is_on(self) -> Optional[bool]:
        if self.what in (1, 34, 35):
            return True
        if self.what == 0:
            return False
        return None


@dataclass(frozen=True)
class AreaCommand:
    """``*22*<what>#<mmtype>#<area param>*4#<area>##`` — on/off for a whole area.

    Only the on/off WHATs are modelled: a volume or station command addressed to
    an area tells us nothing we can reflect without knowing each amplifier.
    """

    area: int
    what: int
    mmtype: Optional[int]

    @property
    def is_on(self) -> Optional[bool]:
        if self.what == 1:
            return True
        if self.what == 0:
            return False
        return None


@dataclass(frozen=True)
class GeneralCommand:
    """``*22*<what>#<mmtype>#<area param>*0##`` — on/off for the whole installation."""

    what: int
    mmtype: Optional[int]
    area_param: Optional[int]

    @property
    def is_on(self) -> Optional[bool]:
        if self.what == 1:
            return True
        if self.what == 0:
            return False
        return None


@dataclass(frozen=True)
class SourceRouted:
    """``*22*2#<mmtype>#<area>*5#2#<source>##`` — "source turned on" event."""

    source: int
    area: int
    mmtype: int


@dataclass(frozen=True)
class SourceFrequency:
    """``*#22*5#2#<s>*5*<modulation>*<frequency>##`` — dimension 5."""

    source: int
    modulation: int
    frequency: int


@dataclass(frozen=True)
class SourceFrequencyStation:
    """``*#22*5#2#<s>*11*<modulation>*<frequency>*<station>##`` — dimension 11."""

    source: int
    modulation: int
    frequency: int
    station: int


@dataclass(frozen=True)
class SourceStation:
    """``*#22*5#2#<s>*6*<station>##`` — dimension 6."""

    source: int
    station: int


@dataclass(frozen=True)
class SourceState:
    """``*#22*5#2#<s>*12*<state>*<mmtype>##`` — source status (dimension 12)."""

    source: int
    is_on: bool
    mmtype: int


SoundDiffusionEvent = Union[
    AmplifierState,
    AmplifierVolume,
    AmplifierCommand,
    AreaCommand,
    GeneralCommand,
    SourceCommand,
    SourceRouted,
    SourceFrequency,
    SourceFrequencyStation,
    SourceStation,
    SourceState,
]

AMPLIFIER_EVENTS = (AmplifierState, AmplifierVolume, AmplifierCommand)
BROADCAST_EVENTS = (AreaCommand, GeneralCommand)
SOURCE_EVENTS = (
    SourceCommand,
    SourceRouted,
    SourceFrequency,
    SourceFrequencyStation,
    SourceStation,
    SourceState,
)


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #

# Every pattern is anchored on its WHERE: the WHAT alone cannot tell an
# amplifier frame from a source frame.
_AMPLIFIER = r"3#(?P<area>\d+)#(?P<point>\d+)"
_SOURCE = r"(?:5#2#|2#)(?P<source>\d+)"

_AMPLIFIER_STATE = re.compile(rf"^\*#22\*{_AMPLIFIER}\*12\*(?P<state>\d+)\*(?P<mmtype>\d+)##$")
_AMPLIFIER_VOLUME = re.compile(rf"^\*#22\*{_AMPLIFIER}\*1\*(?P<volume>\d+)\*?##$")
_AMPLIFIER_COMMAND = re.compile(rf"^\*22\*(?P<what>\d+)(?P<what_param>(?:#\d+)*)\*{_AMPLIFIER}##$")

_SOURCE_STATE = re.compile(rf"^\*#22\*{_SOURCE}\*12\*(?P<state>\d+)\*(?P<mmtype>\d+)##$")
_SOURCE_FREQUENCY = re.compile(rf"^\*#22\*{_SOURCE}\*5\*(?P<modulation>\d+)\*(?P<frequency>\d+)##$")
_SOURCE_FREQUENCY_STATION = re.compile(
    rf"^\*#22\*{_SOURCE}\*11\*(?P<modulation>\d+)\*(?P<frequency>\d+)\*(?P<station>\d+)##$"
)
_SOURCE_STATION = re.compile(rf"^\*#22\*{_SOURCE}\*6\*(?P<station>\d+)##$")
_SOURCE_ROUTED = re.compile(r"^\*22\*(?:2|21)#(?P<mmtype>\d+)#(?P<area>\d+)\*5#2#(?P<source>\d+)##$")
_SOURCE_COMMAND = re.compile(r"^\*22\*(?P<what>\d+)(?P<what_param>(?:#\d+)*)\*2#(?P<source>\d+)##$")

_AREA_COMMAND = re.compile(r"^\*22\*(?P<what>\d+)(?P<what_param>(?:#\d+)*)\*4#(?P<area>\d+)##$")
_GENERAL_COMMAND = re.compile(r"^\*22\*(?P<what>\d+)(?P<what_param>(?:#\d+)*)\*0##$")

#: WHATs an area or general command is reflected for: only on/off tell us a state.
_BROADCAST_WHATS = (0, 1)


def _what_params(raw: str) -> tuple:
    """Split a ``#a#b`` WHAT parameter suffix into a tuple of ints."""
    return tuple(int(_part) for _part in raw.split("#") if _part != "")


def parse_sound_diffusion(raw: str) -> Optional[SoundDiffusionEvent]:
    """Parse a WHO=22 frame, returning ``None`` when it carries nothing usable.

    ``None`` is returned for the legacy WHO=16 duplicates the bus emits next to
    every sound diffusion frame, for valueless dimension requests, and for the
    ``*22*9*5#3#<a>#<p>##`` style frames whose effect is reported right after by
    the dimension 5/11/6 replies.
    """
    if not raw:
        return None

    raw = raw.strip()

    _match = _AMPLIFIER_STATE.match(raw)
    if _match:
        return AmplifierState(
            area=int(_match.group("area")),
            point=int(_match.group("point")),
            is_on=_match.group("state") == "1",
            mmtype=int(_match.group("mmtype")),
        )

    _match = _AMPLIFIER_VOLUME.match(raw)
    if _match:
        return AmplifierVolume(
            area=int(_match.group("area")),
            point=int(_match.group("point")),
            volume=int(_match.group("volume")),
        )

    _match = _AMPLIFIER_COMMAND.match(raw)
    if _match:
        return AmplifierCommand(
            area=int(_match.group("area")),
            point=int(_match.group("point")),
            what=int(_match.group("what")),
            params=_what_params(_match.group("what_param")),
        )

    _match = _SOURCE_STATE.match(raw)
    if _match:
        return SourceState(
            source=int(_match.group("source")),
            is_on=_match.group("state") == "1",
            mmtype=int(_match.group("mmtype")),
        )

    _match = _SOURCE_FREQUENCY_STATION.match(raw)
    if _match:
        return SourceFrequencyStation(
            source=int(_match.group("source")),
            modulation=int(_match.group("modulation")),
            frequency=int(_match.group("frequency")),
            station=int(_match.group("station")),
        )

    _match = _SOURCE_FREQUENCY.match(raw)
    if _match:
        return SourceFrequency(
            source=int(_match.group("source")),
            modulation=int(_match.group("modulation")),
            frequency=int(_match.group("frequency")),
        )

    _match = _SOURCE_STATION.match(raw)
    if _match:
        return SourceStation(
            source=int(_match.group("source")),
            station=int(_match.group("station")),
        )

    _match = _SOURCE_ROUTED.match(raw)
    if _match:
        return SourceRouted(
            source=int(_match.group("source")),
            area=int(_match.group("area")),
            mmtype=int(_match.group("mmtype")),
        )

    _match = _SOURCE_COMMAND.match(raw)
    if _match:
        _params = _what_params(_match.group("what_param"))
        return SourceCommand(
            source=int(_match.group("source")),
            what=int(_match.group("what")),
            mmtype=_params[0] if len(_params) > 0 else None,
            area_param=_params[1] if len(_params) > 1 else None,
        )

    _match = _AREA_COMMAND.match(raw)
    if _match and int(_match.group("what")) in _BROADCAST_WHATS:
        _params = _what_params(_match.group("what_param"))
        return AreaCommand(
            area=int(_match.group("area")),
            what=int(_match.group("what")),
            mmtype=_params[0] if len(_params) > 0 else None,
        )

    _match = _GENERAL_COMMAND.match(raw)
    if _match and int(_match.group("what")) in _BROADCAST_WHATS:
        _params = _what_params(_match.group("what_param"))
        return GeneralCommand(
            what=int(_match.group("what")),
            mmtype=_params[0] if len(_params) > 0 else None,
            area_param=_params[1] if len(_params) > 1 else None,
        )

    return None


# --------------------------------------------------------------------------- #
# Frame builders
# --------------------------------------------------------------------------- #


def amplifier_on_simple(area: int, point: int) -> str:
    """Turn an amplifier on, in the exact form captured on the bus."""
    return f"*22*1#{MMTYPE_STEREO}#{area}*3#{area}#{point}##"


def amplifier_on(area: int, point: int, source: int = 1) -> str:
    """Turn an amplifier on and select a source (WHAT 35). Not verified on the bus."""
    return f"*22*35#{MMTYPE_STEREO}#{area}#{source}*3#{area}#{point}##"


def amplifier_off(area: int, point: int) -> str:
    """Turn an amplifier off, spec form (the area parameter repeats the area)."""
    return f"*22*0#{MMTYPE_STEREO}#{area}*3#{area}#{point}##"


def amplifier_off_bus(area: int, point: int) -> str:
    """Turn an amplifier off, in the exact form captured on the bus (area 0)."""
    return f"*22*0#{MMTYPE_STEREO}#0*3#{area}#{point}##"


def volume_up(area: int, point: int, step: int = 1) -> str:
    return f"*22*3#{step}*3#{area}#{point}##"


def volume_down(area: int, point: int, step: int = 1) -> str:
    return f"*22*4#{step}*3#{area}#{point}##"


def volume_set(area: int, point: int, volume: int) -> str:
    """Write dimension 1 (volume, 0-31) on an amplifier."""
    volume = max(0, min(MAX_VOLUME, int(volume)))
    return f"*#22*3#{area}#{point}*#1*{volume}##"


def station_next(source: int = 1) -> str:
    """Next station, spec form (§3.1.5).

    Not yet confirmed on hardware; the bus-observed form ``*22*9*5#3#a#p##``
    (:func:`station_next_from_amplifier`) is used by default.
    """
    return f"*22*9#*2#{source}##"


def station_previous(source: int = 1) -> str:
    """Previous station, spec form (§3.1.5).

    Not yet confirmed on hardware; the bus-observed form ``*22*10*5#3#a#p##``
    (:func:`station_previous_from_amplifier`) is used by default.
    """
    return f"*22*10#*2#{source}##"


def station_next_from_amplifier(area: int, point: int) -> str:
    """Next station, addressed as general with the amplifier as emitter.

    This is the form the wall command emitted on the bus, so it is the one this
    integration sends.
    """
    return f"*22*9*5#3#{area}#{point}##"


def station_previous_from_amplifier(area: int, point: int) -> str:
    return f"*22*10*5#3#{area}#{point}##"


def frequency_seek_up(source: int = 1, step: Optional[int] = None) -> str:
    """Seek up, automatically (``step`` omitted) or by a given frequency step.

    Spec form (§3.1.5), not yet confirmed on hardware.
    """
    return f"*22*5#{step if step is not None else ''}*2#{source}##"


def frequency_seek_down(source: int = 1, step: Optional[int] = None) -> str:
    """Seek down. Spec form (§3.1.5), not yet confirmed on hardware."""
    return f"*22*6#{step if step is not None else ''}*2#{source}##"


def store_station(source: int, station: int) -> str:
    """Memorise the current frequency on preset ``station``."""
    return f"*22*33#{station}*2#{source}##"


def set_frequency(source: int, frequency: int, station: int, modulation: int = MODULATION_FM) -> str:
    """Write dimension 11 on a source: modulation, frequency (x100) and preset."""
    return f"*#22*5#2#{source}*#11*{modulation}*{frequency}*{station}##"


def request_amplifier_state(area: int, point: int) -> str:
    return f"*#22*3#{area}#{point}*12##"


def request_amplifier_volume(area: int, point: int) -> str:
    return f"*#22*3#{area}#{point}*1##"


def request_source_frequency_station(source: int = 1) -> str:
    return f"*#22*5#2#{source}*11##"


def request_source_frequency(source: int = 1) -> str:
    return f"*#22*5#2#{source}*5##"


def request_global_status(source: int = 1) -> str:
    """Status request returning dimension 12 for every source and amplifier."""
    return f"*#22*5#2#{source}##"


# --------------------------------------------------------------------------- #
# Station helpers
# --------------------------------------------------------------------------- #


def station_name(frequency: Optional[int], table: Optional[dict] = None) -> Optional[str]:
    """Name of the station broadcasting at ``frequency`` (hundredths of MHz).

    ``table`` maps a frequency in hundredths of MHz to a station name; it
    defaults to the built-in FM band around Bordeaux. A gateway can override it
    through the ``radio_stations`` option of the configuration file.
    """
    if frequency is None:
        return None
    if table is None:
        table = STATIONS
    _best = None
    _best_distance = STATION_MATCH_TOLERANCE + 1
    for _frequency, _name in table.items():
        _distance = abs(_frequency - frequency)
        if _distance <= STATION_MATCH_TOLERANCE and _distance < _best_distance:
            _best = _name
            _best_distance = _distance
    return _best


def format_frequency(frequency: Optional[int], modulation: int = MODULATION_FM) -> Optional[str]:
    """Human readable frequency, e.g. ``106.0 MHz`` or ``102.45 MHz``.

    FM frequencies are carried in hundredths of MHz; a trailing zero is dropped
    so the common case reads ``106.0 MHz`` rather than ``106.00 MHz``. Every
    other modulation is an AM band, whose values are kHz. The AM branch is
    unverified: the installation only has an FM tuner.
    """
    if frequency is None:
        return None
    if modulation != MODULATION_FM:
        return f"{frequency} kHz"
    _decimals = 1 if frequency % 10 == 0 else 2
    return f"{frequency / 100:.{_decimals}f} MHz"
