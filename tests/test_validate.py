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
tuner = ha_stubs.load("tuner")

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
            "house": {
                "mac": MAC,
                "radio_stations": {"106.0": "SUD RADIO"},
                "media_player": {"ampli": {"where": "3#7#1", "name": "Radio Cuisine"}},
            }
        }
    )
    mac = list(result)[0]
    assert const.CONF_RADIO_STATIONS not in result[mac][const.CONF_PLATFORMS]
    # `number` and `button` are the tuner the amplifier listens to, derived.
    assert list(result[mac][const.CONF_PLATFORMS]) == ["media_player", "number", "button"]
    assert result[mac][const.CONF_RADIO_STATIONS] == {10600: "SUD RADIO"}


def test_radio_stations_are_optional():
    result = validate.config_schema(
        {"house": {"mac": MAC, "media_player": {"ampli": {"where": "3#7#1", "name": "Radio Cuisine"}}}}
    )
    mac = list(result)[0]
    assert const.CONF_RADIO_STATIONS not in result[mac]


def test_the_configured_table_feeds_station_name():
    table = validate.RadioStations()({"106.0": "MA RADIO"})
    assert sound_diffusion.station_name(10600, table) == "MA RADIO"


# --------------------------------------------------------------------------- #
# tuning_preset gateway option
# --------------------------------------------------------------------------- #


def _gateway(**options):
    result = validate.config_schema(
        {"house": {"mac": MAC, "media_player": {"ampli": {"where": "3#7#1", "name": "Radio Cuisine"}}, **options}}
    )
    return result[list(result)[0]]


def test_tuning_preset_defaults_to_the_last_preset():
    assert _gateway()[const.CONF_TUNING_PRESET] == sound_diffusion.DEFAULT_TUNING_PRESET == 15


@pytest.mark.parametrize("preset", [1, 7, 15])
def test_tuning_preset_accepts_the_whole_range(preset):
    assert _gateway(tuning_preset=preset)[const.CONF_TUNING_PRESET] == preset


def test_tuning_preset_is_coerced_from_a_string():
    assert _gateway(tuning_preset="12")[const.CONF_TUNING_PRESET] == 12


@pytest.mark.parametrize("preset", [0, -1, 16, 99])
def test_tuning_preset_rejects_what_the_tuner_has_no_slot_for(preset):
    with pytest.raises(Invalid):
        _gateway(tuning_preset=preset)


def test_tuning_preset_is_stored_beside_the_platforms_not_among_them():
    """It carries a default, so it reaches every gateway, amplifiers or not."""
    result = _gateway(tuning_preset=3)

    assert const.CONF_TUNING_PRESET not in result[const.CONF_PLATFORMS]
    assert list(result[const.CONF_PLATFORMS]) == ["media_player", "number", "button"]


def test_a_gateway_without_amplifiers_gets_no_extra_platform():
    result = validate.config_schema({"house": {"mac": MAC, "light": {"lamp": {"where": "12", "name": "Lamp"}}}})
    mac = list(result)[0]

    assert const.CONF_TUNING_PRESET not in result[mac][const.CONF_PLATFORMS]
    assert result[mac][const.CONF_TUNING_PRESET] == 15
# --------------------------------------------------------------------------- #
# The tuner devices derived out of the amplifiers
# --------------------------------------------------------------------------- #


def _amplifiers(**sources):
    """A gateway whose amplifiers listen to the sources given, by device key."""
    return validate.config_schema(
        {
            "house": {
                "mac": MAC,
                "media_player": {_key: {"where": f"3#{_index + 2}#1", "name": _key.title(), "source": _source} for _index, (_key, _source) in enumerate(sources.items())},
            }
        }
    )[MAC][const.CONF_PLATFORMS]


def test_a_tuner_device_is_derived_for_the_source_of_the_amplifiers():
    _platforms = _amplifiers(kitchen=1, bedroom=1)

    assert list(_platforms["number"]) == ["22-2#1"]
    assert _platforms["number"]["22-2#1"][const.CONF_WHO] == "22"
    assert _platforms["number"]["22-2#1"][const.CONF_WHERE] == "2#1"
    assert _platforms["number"]["22-2#1"][const.CONF_SOURCE] == 1
    assert _platforms["number"]["22-2#1"]["name"] == "Tuner FM"
    assert _platforms["number"]["22-2#1"][const.CONF_ENTITIES] == {}


def test_the_device_id_is_the_one_the_sound_diffusion_helper_builds():
    _platforms = _amplifiers(kitchen=1)

    assert list(_platforms["number"]) == [sound_diffusion.tuner_device_id(1)]


def test_one_tuner_device_per_distinct_source_however_many_amplifiers():
    _platforms = _amplifiers(kitchen=1, bedroom=2, bathroom=2)

    assert sorted(_platforms["number"]) == ["22-2#1", "22-2#2"]
    assert [_platforms["number"][_device]["name"] for _device in sorted(_platforms["number"])] == ["Tuner FM 1", "Tuner FM 2"]


def test_the_tuner_is_declared_on_both_platforms_it_spreads_over():
    _platforms = _amplifiers(kitchen=1)

    assert "22-2#1" in _platforms["number"]
    assert "22-2#1" in _platforms["button"]
    # A device dict of its own per platform: `button.py` deletes its own on
    # unload, and must not empty the `number` platform on its way out.
    assert _platforms["number"]["22-2#1"] is not _platforms["button"]["22-2#1"]


def test_a_gateway_without_amplifiers_gets_no_tuner_platform():
    _platforms = validate.config_schema({"house": {"mac": MAC, "light": {"lamp": {"where": "12", "name": "Lamp"}}}})[MAC][const.CONF_PLATFORMS]

    assert "number" not in _platforms
    # `button` is there, but for the lock buttons of the light.
    assert all(_device[const.CONF_WHO] != "22" for _device in _platforms["button"].values())


def test_the_lock_buttons_of_a_light_are_not_taken_for_a_tuner():
    _platforms = validate.config_schema(
        {
            "house": {
                "mac": MAC,
                "light": {"lamp": {"where": "12", "name": "Lamp"}},
                "media_player": {"ampli": {"where": "3#7#1", "name": "Radio"}},
            }
        }
    )[MAC][const.CONF_PLATFORMS]

    assert sorted(_platforms["button"]) == ["1-12", "22-2#1"]
    assert _platforms["button"]["1-12"][const.CONF_WHO] == "1"
    assert _platforms["button"]["22-2#1"][const.CONF_WHO] == "22"


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


#: The five entities of the tuner device, as `validate.py` and `tuner.py` name
#: them once Home Assistant has slugified "Tuner FM" + the entity name.
TUNER_ENTITIES = [
    "number.tuner_fm_frequency",
    "button.tuner_fm_seek_up",
    "button.tuner_fm_seek_down",
    "button.tuner_fm_next_preset",
    "button.tuner_fm_previous_preset",
]


def _dashboard_features(entity):
    return [_feature for _card in _dashboard_cards() if _card.get("entity") == entity for _feature in _card.get("features", [])]


def test_the_documented_tuner_entity_ids_are_the_ones_the_code_produces():
    """`has_entity_name`: Home Assistant slugifies the device name plus the entity's.

    Neither the device name nor the four button names can drift without the
    entity ids of the README and of the dashboard drifting with them.
    """
    _device_name = _amplifiers(kitchen=1)["number"]["22-2#1"]["name"]

    def _slug(platform, entity_name):
        return platform + "." + re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", f"{_device_name} {entity_name}".lower())).strip("_")

    assert _slug("number", "Frequency") == "number.tuner_fm_frequency"
    assert [_slug("button", _name) for _key, _name, *_ in tuner.TUNER_BUTTONS] == TUNER_ENTITIES[1:]


def test_the_readme_documents_every_tuner_entity():
    with open(os.path.join(REPOSITORY, "README.md"), encoding="utf-8") as _file:
        _readme = _file.read()

    for _entity in TUNER_ENTITIES:
        assert f"`{_entity}`" in _readme, f"{_entity} is created but never documented"


def test_the_dashboard_addresses_exactly_the_amplifiers_of_the_readme():
    _expected = _readme_amplifiers()
    _referenced = _referenced_entities(_dashboard_view())

    assert len(_expected) == 10
    assert set(_entity for _entity in _referenced if _entity.startswith("media_player.")) == set(_expected)


def test_the_dashboard_carries_the_five_tuner_entities():
    """One tuner, one section: the frequency and the four buttons, nothing twice."""
    _referenced = _referenced_entities(_dashboard_view())
    _tuner = [_entity for _entity in _referenced if not _entity.startswith("media_player.")]

    assert sorted(_tuner) == sorted(TUNER_ENTITIES)
    assert len(_tuner) == len(set(_tuner)), "a station control repeated is a station moved twice"


def test_the_dashboard_drives_the_frequency_with_a_slider():
    assert _dashboard_features("number.tuner_fm_frequency") == [{"type": "numeric-input", "style": "slider"}]


def test_the_dashboard_keeps_the_station_dropdown_on_the_kitchen_tile():
    _features = _dashboard_features("media_player.radio_cuisine")

    assert {"type": "media-player-source"} in _features
    assert [_card["entity"] for _card in _dashboard_cards() if {"type": "media-player-source"} in _card.get("features", [])] == [
        "media_player.radio_cuisine"
    ]


def test_the_dashboard_lists_the_rooms_in_the_order_of_the_readme():
    """One order for the whole documentation, so the three lists cannot drift."""
    _expected = _readme_amplifiers()

    _tiles = [_card["entity"] for _card in _dashboard_cards() if _card.get("type") == "tile" and _card["entity"].startswith("media_player.")]
    assert _tiles == _expected

    _all_off = [_card for _card in _dashboard_cards() if _card.get("type") == "button" and "every amplifier off" in _card["name"]]
    assert len(_all_off) == 1
    assert _all_off[0]["tap_action"]["target"]["entity_id"] == _expected
