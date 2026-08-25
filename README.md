# MyHOME
MyHOME integration for Home-Assistant

## Installation
The integration is able to install the gateway via the Home-Assistant graphical user interface, configuring the different devices needs to be done in YAML files however.

Some common gateways should be auto-discovered, but it is still possible to force the inclusion of a gateway not discovered. One limitation however is that the gateway needs to be in the same network as your Home-Assistant instance.

It is possible that upon first install (and updates), the OWNd listener process crashes and you do not get any status feedback on your devices. If such is the case, a restart of Home Assistant should solve the issue.

## BEWARE

If you've been using this integration in version 0.8 and prior, configuration structure has changed and you need to create and populate the appropriate config file. See below for instructions.


## Configuration and use

Please find the [configuration](https://github.com/anotherjulien/MyHOME/wiki/Configuration) on the project's wiki!  
[Advanced uses](https://github.com/anotherjulien/MyHOME/wiki/Advanced-uses) are also listed in the wiki.


## Sound Diffusion (WHO=22)

This fork adds a `media_player` platform for MyHOME sound diffusion amplifiers.
Each amplifier becomes one `media_player` entity supporting on/off, volume set
and volume step, and next/previous station.

All amplifiers of an installation usually share the same source (a single tuner),
so changing station on one amplifier changes it for all of them. The integration
reflects that: the tuning information is read once per gateway and shown on every
amplifier entity listening to that source.

### Configuration

Amplifiers are declared in `/config/myhome.yaml`, under the gateway they belong
to. `where` is the amplifier's address, `3#<area>#<point>`, with the area and the
point both in `[1-9]`.

```yaml
villa:
  mac: "00:03:50:11:22:33"
  media_player:
    ampli_cuisine:          { where: "3#7#1", name: "Radio Cuisine" }
    ampli_suite:            { where: "3#2#1", name: "Radio Suite" }
    ampli_suite_sdb:        { where: "3#2#2", name: "Radio Suite SDB" }
    ampli_bureau_julie:     { where: "3#3#1", name: "Radio Bureau Julie" }
    ampli_bureau_julie_sdb: { where: "3#3#2", name: "Radio Bureau Julie SDB" }
    ampli_gym:              { where: "3#4#1", name: "Radio Gym" }
    ampli_chambre_ami:      { where: "3#5#1", name: "Radio Chambre Ami" }
    ampli_chambre_ami_sdb:  { where: "3#5#2", name: "Radio Chambre Ami SDB" }
    ampli_bureau_raph:      { where: "3#6#1", name: "Radio Bureau Raph" }
    ampli_bureau_raph_sdb:  { where: "3#6#2", name: "Radio Bureau Raph SDB" }
    # ampli_tablette:       { where: "3#1#1", name: "Radio Tablette" }
```

Restart Home Assistant after editing `myhome.yaml`: the file is read when the
config entry is set up, not watched.

Available options, per amplifier:

| Option         | Default          | Description                                             |
| -------------- | ---------------- | ------------------------------------------------------- |
| `where`        | *required*       | Amplifier address, `3#<area>#<point>`, area/point in [1-9] |
| `name`         | *required*       | Device name; the entity id is derived from it            |
| `who`          | `"22"`           | Leave it alone, it is here for symmetry with the other platforms |
| `entity_name`  | `None`           | Entity name, when it should differ from the device name  |
| `source`       | `1`              | Source (tuner) this amplifier listens to, `[1-4]`        |
| `icon`         | *device class*   | Entity icon; left out, the speaker device class picks one |
| `manufacturer` | `BTicino S.p.A.` | Device manufacturer                                      |
| `model`        | `None`           | Device model                                             |

And one option on the gateway itself:

| Option           | Default           | Description                                    |
| ---------------- | ----------------- | ---------------------------------------------- |
| `radio_stations` | FM band, Bordeaux | Frequency (MHz) to station name, see below      |

### Station names

`media_title` reads e.g. `106.0 MHz · SUD RADIO`. The tuner only reports a
frequency, so the name comes from a table matched with a ±0.05 MHz tolerance.
The built-in table covers the FM band around Bordeaux and **is overwritten on
every update**: to keep your own, set the `radio_stations` option on the gateway
rather than editing `sound_diffusion.py`.

```yaml
villa:
  mac: "00:03:50:11:22:33"
  radio_stations:
    "106.0": SUD RADIO
    "97.3": NOSTALGIE
    "94.3": EUROPE 2
  media_player:
    ampli_cuisine: { where: "3#7#1", name: "Radio Cuisine" }
```

Frequencies not listed simply show without a name (`97.3 MHz`).

### Attributes

Each amplifier exposes `area`, `point` and `source_id`, plus `raw_volume` (the
bus' 0-31 value) once it is known and, while it is playing, `frequency_mhz`,
`station_name` and `preset`. Attributes without a value are left out, so an
amplifier that is off carries only its addressing.

### Behaviour & limitations

- **The tuner is shared per source.** Changing station on one amplifier changes
  it on every amplifier listening to that source. There is no way around it: the
  bus has one tuner.
- **Volume is a 0-31 integer**, so the slider moves in 32 steps. Home Assistant's
  0..1 level is rounded to the nearest of them.
- **No mute, no pause, no source selection.** The amplifiers of this
  installation expose none of it; only on/off, volume and station.
- **Entity ids** come from the device name, as usual: `name: "Radio Cuisine"`
  gives `media_player.radio_cuisine`.
- **Availability** follows the gateway connection: every amplifier goes
  unavailable while the gateway is unreachable. Entities are created before the
  listener connects, so they start out unavailable and come back with the first
  frame the bus sends them — the answer to the status request issued at startup,
  in the normal case.
- **Groups**: a `platform: group` media player is fine for on/off and volume,
  but **never send next/previous track to a group**. Each member would ask the
  shared tuner for the next station and it would jump once per member. Drive the
  station from a single reference amplifier instead, as the dashboard below does.

```yaml
# configuration.yaml — on/off and volume only
media_player:
  - platform: group
    name: Radio Suite (pièce)
    entities:
      - media_player.radio_suite
      - media_player.radio_suite_sdb
```

### Dashboard

[`examples/dashboard-radios.yaml`](examples/dashboard-radios.yaml) is a ready to
paste "Radios" view: the shared tuner at the top with its two station buttons,
then one card per room with a volume slider and explicit on/off buttons, and a
"turn everything off" button. Adapt the entity ids to your own `name:` values.

### Experimental / not verified on hardware

Everything below is built from the Legrand WHO=22 specification and was never
seen on the bus of the installation this fork was developed against. It may
behave differently, or not at all.

- **`volume_set`** writes dimension 1 (`*#22*3#<a>#<p>*#1*<volume>##`). Only the
  relative steps (WHAT 3 and 4) were observed; the write is not echoed back as
  an event, which is why the entity updates optimistically.
- **WHAT 35** (`amplifier_on`, "turn on and select that source"). The
  integration sends the observed WHAT 1 form instead.
- **The spec form of the station commands** (`*22*9#*2#<source>##`). The
  integration sends the observed `*22*9*5#3#<area>#<point>##` instead.
- **AM display.** Any modulation other than FM is printed in kHz, untested.
- **Area and general commands.** `*22*<what>#<mm>#<a>*4#<area>##` and
  `*22*<what>#<mm>#<a>*0##` are read as "turn this area on/off" and "turn
  everything on/off" and are reflected on the amplifiers they address, all of
  them in the general case. Neither was seen on the bus; if the frames mean
  something else, a single frame flips the state of every amplifier at once.
- **Setting a frequency** has no dedicated service. The existing
  `myhome.send_message` service can write dimension 11 on a source:

```yaml
action: myhome.send_message
data:
  gateway: "00:03:50:11:22:33"
  message: "*#22*5#2#1*#11*1*10600*14##"   # source 1, FM, 106.00 MHz, preset 14
```

### Migrating from upstream (anotherjulien/MyHOME)

The domain stays `myhome`, so your config entry and your `myhome.yaml` are kept
as they are: there is nothing to reconfigure, and the other platforms behave
exactly as before.

Through HACS:

1. In HACS, open the MyHOME integration, choose *Remove*, and keep the
   integration files if HACS offers to.
2. Add `adrael/MyHOME` as a custom repository, of type *Integration*.
3. Install MyHOME from that repository.
4. Restart Home Assistant.
5. Add a `media_player:` block to `myhome.yaml` and restart again.

Manually: replace the contents of `/config/custom_components/myhome/` with this
repository's `custom_components/myhome/`, then restart.

To roll back, reinstall the upstream integration **and comment out the
`media_player:` block of `myhome.yaml`** before restarting: upstream does not
know that key and will refuse the file.

### Tests

The WHO=22 parser, the frame builders, the configuration schema and the gateway
dispatch are covered by plain pytest, with Home Assistant stubbed:

```sh
pip install -r requirements-dev.txt
pytest
```
