"""Tests for the configuration file validator, focused on the WHO=22 schema."""

import copy
import os
import re
import sys

import pytest
import yaml
from voluptuous import Invalid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ha_stubs  # noqa: E402

validate = ha_stubs.load("validate")
const = ha_stubs.load("const")
sound_diffusion = ha_stubs.load("sound_diffusion")

MAC = "00:03:50:11:22:33"
REPOSITORY = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# --------------------------------------------------------------------------- #
# Amplifier WHERE
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("configured", "expected"),
    [("3#2#2", "3#2#2"), ("3#7#1", "3#7#1"), ("3#9#9", "3#9#9")],
)
def test_amplifier_where(configured, expected):
    assert validate.Amplifier()(configured) == expected


@pytest.mark.parametrize(
    "configured",
    [
        "2#2",  # short form: too easy to confuse with a point-to-point WHERE
        "3#0#1",  # area 0 is the "general" address, not an amplifier
        "3#1#0",
        "3#10#1",
        "3#2",
        "3#2#2#4",
        "3##2",
        "22",
        "",
    ],
)
def test_amplifier_where_rejects(configured):
    with pytest.raises(Invalid):
        validate.Amplifier()(configured)


def test_amplifier_repr():
    assert repr(validate.Amplifier()) == "Amplifier()"


# --------------------------------------------------------------------------- #
# media_player schema
# --------------------------------------------------------------------------- #


def test_media_player_schema_keys_devices_like_the_sound_diffusion_helper():
    result = validate.media_player_schema({"ampli_suite_sdb": {"where": "3#2#2", "name": "Radio Suite SDB"}})
    assert list(result) == [sound_diffusion.amplifier_device_id(2, 2)]
    assert result["22-3#2#2"][const.CONF_WHERE] == "3#2#2"
    assert result["22-3#2#2"][const.CONF_WHO] == "22"


def test_media_player_schema_defaults():
    result = validate.media_player_schema({"ampli": {"where": "3#7#1", "name": "Radio Cuisine"}})["22-3#7#1"]
    assert result[const.CONF_SOURCE] == 1
    assert result[const.CONF_ICON] is None
    assert result[const.CONF_ENTITY_NAME] is None
    assert result[const.CONF_DEVICE_MODEL] is None


def test_media_player_schema_keeps_a_configured_icon():
    result = validate.media_player_schema({"ampli": {"where": "3#7#1", "name": "Radio", "icon": "mdi:radio"}})
    assert result["22-3#7#1"][const.CONF_ICON] == "mdi:radio"


@pytest.mark.parametrize("source", [1, 2, 3, 4])
def test_media_player_schema_accepts_every_source(source):
    result = validate.media_player_schema({"ampli": {"where": "3#7#1", "name": "Radio", "source": source}})
    assert result["22-3#7#1"][const.CONF_SOURCE] == source


@pytest.mark.parametrize("source", [0, 5, 9])
def test_media_player_schema_rejects_out_of_range_sources(source):
    with pytest.raises(Invalid):
        validate.media_player_schema({"ampli": {"where": "3#7#1", "name": "Radio", "source": source}})


# --------------------------------------------------------------------------- #
# radio_stations gateway option
# --------------------------------------------------------------------------- #


def test_radio_stations_are_keyed_by_hundredths_of_mhz():
    assert validate.RadioStations()({"106.0": "SUD RADIO", "97.3": "NOSTALGIE"}) == {
        10600: "SUD RADIO",
        9730: "NOSTALGIE",
    }


def test_radio_stations_accept_unquoted_yaml_floats_and_integers():
    """`106.0:` in YAML is a float key, `106:` an integer one."""
    assert validate.RadioStations()(yaml.safe_load("106.0: SUD RADIO\n97: AUTRE\n")) == {
        10600: "SUD RADIO",
        9700: "AUTRE",
    }


@pytest.mark.parametrize("table", [{"not a frequency": "X"}, "106.0", ["106.0"]])
def test_radio_stations_reject_garbage(table):
    with pytest.raises(Invalid):
        validate.RadioStations()(table)


def test_radio_stations_are_stored_beside_the_platforms_not_among_them():
    """A gateway option must not end up looking like a platform to set up."""
    result = validate.config_schema(
        {
            "villa": {
                "mac": MAC,
                "radio_stations": {"106.0": "SUD RADIO"},
                "media_player": {"ampli": {"where": "3#7#1", "name": "Radio Cuisine"}},
            }
        }
    )
    mac = list(result)[0]
    assert const.CONF_RADIO_STATIONS not in result[mac][const.CONF_PLATFORMS]
    assert list(result[mac][const.CONF_PLATFORMS]) == ["media_player"]
    assert result[mac][const.CONF_RADIO_STATIONS] == {10600: "SUD RADIO"}


def test_radio_stations_are_optional():
    result = validate.config_schema(
        {"villa": {"mac": MAC, "media_player": {"ampli": {"where": "3#7#1", "name": "Radio Cuisine"}}}}
    )
    mac = list(result)[0]
    assert const.CONF_RADIO_STATIONS not in result[mac]


def test_the_configured_table_feeds_station_name():
    table = validate.RadioStations()({"106.0": "MA RADIO"})
    assert sound_diffusion.station_name(10600, table) == "MA RADIO"
# --------------------------------------------------------------------------- #
# The examples of the README have to validate
# --------------------------------------------------------------------------- #


def _yaml_blocks(path):
    with open(path, encoding="utf-8") as _file:
        return re.findall(r"```yaml\n(.*?)```", _file.read(), re.S)


def _readme_examples():
    _candidates = []
    for _block in _yaml_blocks(os.path.join(REPOSITORY, "README.md")):
        _parsed = yaml.safe_load(_block)
        if isinstance(_parsed, dict) and all(isinstance(_value, dict) and "mac" in _value for _value in _parsed.values()):
            _candidates.append(_parsed)
    return _candidates


def test_the_readme_myhome_yaml_example_validates():
    _candidates = _readme_examples()

    assert _candidates, "the README should show at least one complete myhome.yaml example"
    for _example in _candidates:
        _result = validate.config_schema(copy.deepcopy(_example))
        assert _result, _example


# --------------------------------------------------------------------------- #
# The dashboard example has to address the amplifiers of the README
# --------------------------------------------------------------------------- #


def _entity_id(name):
    """What Home Assistant slugifies a device name into.

    `has_entity_name` with no entity name of its own: the entity id is the
    device name, which is what `myhome_device.py` sets up.
    """
    return "media_player." + re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", name.lower())).strip("_")


def _readme_amplifiers():
    """The entity ids of the fullest `media_player` example of the README, in order."""
    _blocks = [_block for _example in _readme_examples() for _block in _example.values() if "media_player" in _block]
    _biggest = max(_blocks, key=lambda _block: len(_block["media_player"]))
    return [_entity_id(_amplifier["name"]) for _amplifier in _biggest["media_player"].values()]


def _dashboard_view():
    with open(os.path.join(REPOSITORY, "examples", "dashboard-radios.yaml"), encoding="utf-8") as _file:
        return yaml.safe_load(_file)["views"][0]


def _referenced_entities(node, found=None):
    """Every entity the dashboard points at, under any of the keys that carry one."""
    found = [] if found is None else found
    if isinstance(node, dict):
        for _key, _value in node.items():
            if _key in ("entity", "entity_id"):
                found.extend([_value] if isinstance(_value, str) else _value)
            else:
                _referenced_entities(_value, found)
    elif isinstance(node, list):
        for _item in node:
            _referenced_entities(_item, found)
    return found


def _dashboard_cards():
    return [_card for _section in _dashboard_view()["sections"] for _card in _section["cards"]]


def test_the_dashboard_addresses_exactly_the_amplifiers_of_the_readme():
    _expected = _readme_amplifiers()

    assert len(_expected) == 10
    assert set(_referenced_entities(_dashboard_view())) == set(_expected)


def test_the_dashboard_lists_the_rooms_in_the_order_of_the_readme():
    """One order for the whole documentation, so the three lists cannot drift."""
    _expected = _readme_amplifiers()

    _tiles = [_card["entity"] for _card in _dashboard_cards() if _card.get("type") == "tile"]
    assert _tiles == _expected

    _all_off = [_card for _card in _dashboard_cards() if _card.get("type") == "button" and "every amplifier off" in _card["name"]]
    assert len(_all_off) == 1
    assert _all_off[0]["tap_action"]["target"]["entity_id"] == _expected
