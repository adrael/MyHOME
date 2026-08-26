"""OpenWebNet WHO=22 (sound diffusion) parsing and frame building.

OWNd 0.7.48 does not model WHO=22: ``OWNEvent.parse`` returns the raw string for
every ``*22*…`` / ``*#22*…`` event, and dimension *requests* come back as a
generic ``OWNCommand``. Everything WHO=22 specific therefore lives here.

This module is deliberately free of any Home Assistant or OWNd import so it can
be imported and tested on its own.

Every frame builder says whether it was verified on hardware. "Verified" means
one session against the installation this fork was written for (gateway F454,
amplifier ``3#2#2``, FM tuner ``2#1``, 2026-08-25): the frame was sent and the
bus answered what it should, within 300 ms.

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

#: Number of frequency presets an FM tuner holds (F500N, verified on hardware:
#: preset 15 is followed by preset 1).
MAX_STATION_PRESET = 15

#: Preset :func:`set_frequency` overwrites when the integration tunes to an
#: arbitrary station. The last one, so the presets a user is likely to reach for
#: with the station buttons keep their place.
DEFAULT_TUNING_PRESET = MAX_STATION_PRESET

#: FM band, in hundredths of MHz: the range the `number` entity offers.
#:
#: Band II as it is allocated in Europe. The hardware session of 2026-08-26
#: actually drove the tuner from 87.7 to 107.3, every frequency in between
#: accepted; the two ends of the band itself were not tried, and the tuner is
#: the one that decides what it does with them.
MIN_FREQUENCY = 8750
MAX_FREQUENCY = 10800

#: Channel spacing offered by the `number` entity, in hundredths of MHz: 50 kHz,
#: the raster the frequency table itself is written on. Every frequency of the
#: hardware session sits on 100 kHz, so the half step was not exercised; the
#: tuner rounds to whatever it can reach and reports it back.
FREQUENCY_STEP = 5

#: Modulation values carried by dimensions 5 and 11 (Legrand WHO_22 v1.1).
MODULATION_FM = 1
MODULATION_AM_LW = 2
MODULATION_AM_MW = 3
MODULATION_AM_SW = 4

#: Tolerance, in hundredths of MHz, when matching a frequency to a station name.
STATION_MATCH_TOLERANCE = 5

#: FM band around Bordeaux, keyed by frequency in hundredths of MHz.
#: Override it per gateway with the ``radio_stations`` configuration option
#: rather than editing this table, which every update overwrites.
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


def tuner_device_id(source: int) -> str:
    """Key the device of a source (a tuner) is stored under in ``hass.data``.

    Built the same way as :func:`amplifier_device_id`, out of the WHERE of a
    source: ``2#<source>``. Unlike the amplifiers, no line of the configuration
    file declares it — `validate.py` derives one per distinct source of the
    amplifiers that are configured.
    """
    return f"22-2#{source}"


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

    The spec table (§2.3) lists ``4#<area>`` as a WHERE; no command session of
    chapter 3 uses it, it was never observed on the bus and it is **not verified
    on hardware**. It is kept because the blast radius is one area and the
    dimension 12 events of each amplifier follow within a moment, correcting
    whatever we got wrong.

    Only the on/off WHATs are modelled: a volume or station command addressed to
    an area tells us nothing we can reflect without knowing each amplifier. The
    two WHAT parameters are mandatory, so a frame we cannot read in full never
    flips a whole area.
    """

    area: int
    what: int
    mmtype: int

    @property
    def is_on(self) -> bool:
        return self.what == 1


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
    """``*#22*5#2#<s>*6*<station>##`` — dimension 6.

    ``station`` is optional because the integration builds one of these with no
    station at all: a seek button forgets the preset it is leaving, and this is
    the event that says so. The bus never sends that form.
    """

    source: int
    station: Optional[int]


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
    SourceCommand,
    SourceRouted,
    SourceFrequency,
    SourceFrequencyStation,
    SourceStation,
    SourceState,
]

AMPLIFIER_EVENTS = (AmplifierState, AmplifierVolume, AmplifierCommand)
BROADCAST_EVENTS = (AreaCommand,)

#: Source events worth dispatching: the ones that feed the shared tuner store.
#:
#: ``SourceCommand``, ``SourceRouted`` and ``SourceState`` are parsed all the
#: same — they make a debug log readable — but they tell an amplifier nothing it
#: does not already learn from its own dimension 12, and the bus emits them in
#: bursts (a single WHAT 35 command answered with both a ``21#…`` and a ``2#…``
#: routing event, verified on hardware).
SOURCE_EVENTS = (
    SourceFrequency,
    SourceFrequencyStation,
    SourceStation,
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

#: Only on/off, and only in the full ``<what>#<mmtype>#<area>`` parameter form:
#: a frame we cannot read in full must not turn a whole area off.
_AREA_COMMAND = re.compile(r"^\*22\*(?P<what>[01])#(?P<mmtype>\d+)#(?P<area_param>\d+)\*4#(?P<area>\d+)##$")


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
    if _match:
        return AreaCommand(
            area=int(_match.group("area")),
            what=int(_match.group("what")),
            mmtype=int(_match.group("mmtype")),
        )

    return None


# --------------------------------------------------------------------------- #
# Frame builders
# --------------------------------------------------------------------------- #


def amplifier_on_simple(area: int, point: int) -> str:
    """Turn an amplifier on (WHAT 1), the form captured on the bus.

    Verified on hardware (F454, 2026-08-25): answered with dimension 12 and the
    volume within about 150 ms. This is what the integration sends.
    """
    return f"*22*1#{MMTYPE_STEREO}#{area}*3#{area}#{point}##"


def amplifier_on(area: int, point: int, source: int = 1) -> str:
    """Turn an amplifier on and select a source (WHAT 35).

    Verified on hardware; it also makes the bus emit the routing events
    ``*22*21#<mm>#<area>*5#2#<source>##`` and ``*22*2#…``, which say the source
    was switched on for that area. Kept as an alternative: the integration turns
    an amplifier on with WHAT 1 and leaves the source where it was.
    """
    return f"*22*35#{MMTYPE_STEREO}#{area}#{source}*3#{area}#{point}##"


def amplifier_off(area: int, point: int) -> str:
    """Turn an amplifier off, spec form (the area parameter repeats the area).

    Verified on hardware, and what the integration sends.
    """
    return f"*22*0#{MMTYPE_STEREO}#{area}*3#{area}#{point}##"


def amplifier_off_bus(area: int, point: int) -> str:
    """Turn an amplifier off, in the exact form captured on the bus (area 0).

    The area parameter is 0, outside the ``[1-9]`` range the spec gives it. This
    was captured as the echo of a wall command and verified on hardware: both
    forms turn the amplifier off, answered with ``*12*0*10`` alike. Kept as an
    alternative to the spec form :func:`amplifier_off`.
    """
    return f"*22*0#{MMTYPE_STEREO}#0*3#{area}#{point}##"


def volume_up(area: int, point: int, step: int = 1) -> str:
    return f"*22*3#{step}*3#{area}#{point}##"


def volume_down(area: int, point: int, step: int = 1) -> str:
    return f"*22*4#{step}*3#{area}#{point}##"


def volume_set(area: int, point: int, volume: int) -> str:
    """Write dimension 1 (volume, 0-31) on an amplifier.

    Verified absolute on hardware: writing 10 then 14 left the amplifier at 14,
    not at 24, and the bus echoed ``*#22*3#<a>#<p>*1*<volume>##`` within about
    150 ms.
    """
    volume = max(0, min(MAX_VOLUME, int(volume)))
    return f"*#22*3#{area}#{point}*#1*{volume}##"


def station_next(source: int = 1) -> str:
    """Next station, spec form (§3.1.5). What this integration sends.

    Verified on hardware: the tuner moves to the next preset and answers with
    dimensions 5, 11 and 6 within about 200 ms.

    It trails an empty WHAT parameter, which ``OWNCommand`` accepts but flags
    ``is_valid = False``. The ``myhome.send_message`` service checks that flag
    and refuses the frame; ``gateway.send()``, which is what the integration
    uses, does not.
    """
    return f"*22*9#*2#{source}##"


def station_previous(source: int = 1) -> str:
    """Previous station, spec form (§3.1.5). See :func:`station_next`."""
    return f"*22*10#*2#{source}##"


def station_next_from_amplifier(area: int, point: int) -> str:
    """Next station, addressed as general with the amplifier as the emitter.

    ``*22*9*5#3#<a>#<p>##`` was captured as an *event*, emitted by the wall
    control towards the clients; replayed as a command it works all the same,
    verified on hardware. Kept as an alternative: the integration addresses the
    source, which is the thing that moves.
    """
    return f"*22*9*5#3#{area}#{point}##"


def station_previous_from_amplifier(area: int, point: int) -> str:
    """Previous station. See :func:`station_next_from_amplifier`."""
    return f"*22*10*5#3#{area}#{point}##"


def frequency_seek_up(source: int = 1, step: Optional[int] = None) -> str:
    """Seek up, automatically (``step`` omitted) or by a given frequency step.

    Spec form (§3.1.5). The automatic form is verified on hardware 2026-08-26:
    ``*22*5#*2#1##`` moved the tuner to the next station it caught, and answered
    with ``*#22*5#2#1*5*1*10730##`` — **dimension 5 alone**, no dimension 11 and
    no dimension 6, so the preset the tuner was on is left behind and nothing on
    the bus ever says so. That is what ``tuner.MyHOMETunerButton.async_press``
    drops it for, on the press rather than on the frame: a preset *step* is
    answered by a dimension 5 too, and reading that one as a scan had every
    station change blink the preset away and back.

    Passing a ``step`` is untried; without one the WHAT parameter is empty, as in
    :func:`station_next`, which ``OWNCommand`` flags ``is_valid = False``.
    """
    return f"*22*5#{step if step is not None else ''}*2#{source}##"


def frequency_seek_down(source: int = 1, step: Optional[int] = None) -> str:
    """Seek down. Spec form (§3.1.5), see :func:`frequency_seek_up`.

    Verified on hardware the same day, and it says more than seeking up does:
    ``*22*6#*2#1##`` answered with dimension 5 and then, the frequency having
    fallen back onto a stored preset, ``*#22*5#2#1*11*1*10680*15##``.
    """
    return f"*22*6#{step if step is not None else ''}*2#{source}##"


def store_station(source: int, station: int) -> str:
    """Memorise the current frequency on preset ``station``.

    Spec form, **not verified on hardware**: it overwrites a preset of the
    installation, which is not something to try to find out.
    """
    return f"*22*33#{station}*2#{source}##"


def set_frequency(source: int, frequency: int, station_index: int, modulation: int = MODULATION_FM) -> str:
    """Retune a source, storing the frequency in one of its presets.

    ``station_index`` is **0-based**, unlike every other station number of this
    module: the tuner writes the frequency into preset ``station_index + 1``.
    Verified on hardware 2026-08-26 — ``*#22*5#2#1*#11*1*8970*0##`` was answered
    with ``*#22*5#2#1*11*1*8970*1##``, and ``*14`` writes preset 15.

    So this **overwrites a preset of the installation**, and it retunes the
    source immediately: the bus answers with dimension 5 and dimension 11 within
    about 250 ms. The integration always writes the same scratch preset, the
    ``tuning_preset`` option of the gateway, so that selecting a station leaves
    the other fourteen alone.

    Unlike the station commands this frame has no empty WHAT parameter, so
    ``myhome.send_message`` accepts it too.
    """
    return f"*#22*5#2#{source}*#11*{modulation}*{frequency}*{station_index}##"


# Every request below was verified on hardware, and answered even with the
# amplifier off — a switched-off amplifier still reports the volume it holds.
# The source requests are answered by every source of the installation, not only
# by the one addressed.


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
    _entry = _closest_station(frequency, table)
    return _entry[1] if _entry else None


def station_label(frequency: Optional[int], table: Optional[dict] = None) -> Optional[str]:
    """Label of the station at ``frequency``, as :func:`station_entries` writes it.

    The name on its own, unless the table carries it at more than one frequency.
    """
    _entry = _closest_station(frequency, table)
    return _entry[2] if _entry else None


def _closest_station(frequency: Optional[int], table: Optional[dict]):
    """Entry of ``table`` nearest to ``frequency``, within the match tolerance."""
    if frequency is None:
        return None
    _best = None
    _best_distance = STATION_MATCH_TOLERANCE + 1
    for _entry in station_entries(table):
        _distance = abs(_entry[0] - frequency)
        if _distance <= STATION_MATCH_TOLERANCE and _distance < _best_distance:
            _best = _entry
            _best_distance = _distance
    return _best


def station_entries(table: Optional[dict] = None) -> list:
    """``(frequency, name, label)`` for every station of ``table``, by frequency.

    ``table`` maps a frequency in hundredths of MHz to a station name, and
    defaults to the built-in FM band, exactly as :func:`station_name` does.

    The label is what a user picks from: the station name on its own, suffixed
    with its frequency when the same name is carried by more than one of them,
    since Home Assistant identifies a source by its label alone.
    """
    if table is None:
        table = STATIONS
    _occurrences = {}
    for _name in table.values():
        _occurrences[str(_name)] = _occurrences.get(str(_name), 0) + 1
    _entries = []
    for _frequency, _name in sorted(table.items()):
        _name = str(_name)
        _label = _name if _occurrences[_name] == 1 else f"{_name} ({_megahertz(_frequency)})"
        _entries.append((_frequency, _name, _label))
    return _entries


def _megahertz(frequency: int) -> str:
    """``8970`` as ``89.7``, ``10245`` as ``102.45``."""
    _decimals = 1 if frequency % 10 == 0 else 2
    return f"{frequency / 100:.{_decimals}f}"


def format_frequency(frequency: Optional[int], modulation: int = MODULATION_FM) -> Optional[str]:
    """Human readable frequency, e.g. ``106.0 MHz`` or ``102.45 MHz``.

    FM frequencies are carried in hundredths of MHz; a trailing zero is dropped
    so the common case reads ``106.0 MHz`` rather than ``106.00 MHz``. Every
    other modulation is an AM band, whose values are kHz. The AM branch is
    **not verified on hardware**: the installation only has an FM tuner.
    """
    if frequency is None:
        return None
    if modulation != MODULATION_FM:
        return f"{frequency} kHz"
    return f"{_megahertz(frequency)} MHz"
