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

Requires Home Assistant 2024.10 or later.

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
| `who`          | `"22"`           | WHO of the platform; present for symmetry with the others, and only `"22"` is accepted |
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

Frequencies not listed simply show without a name (`101.1 MHz`).

### Attributes

Each amplifier exposes `area`, `point` and `source_id`, plus `raw_volume` (the
bus' 0-31 value) once it is known. The tuner is one box shared by the whole
installation, so `frequency_mhz`, `station_name` and `preset` are published as
soon as they are known, **whether that amplifier is playing or not** — a
dashboard can show the station with the whole house switched off. `modulation`
is added only when it is not FM (2 long wave, 3 medium wave, 4 short wave).

Attributes without a value are left out, so an amplifier of a gateway whose
tuner never answered carries only its addressing.

What comes out of *this* amplifier is a different matter: `media_title`,
`media_channel` and `media_content_type` are `None` unless it is playing.

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
- **The state is `playing`, not `on`.** A media player that reports `on` gets
  its next/previous buttons hidden by the Home Assistant cards, so an amplifier
  that is playing reports `playing`. In templates and conditions, write
  `is_state('media_player.radio_cuisine', 'playing')`.
- **Availability** follows the gateway connection: every amplifier goes
  unavailable while the gateway is unreachable, and comes back as soon as the
  listener reconnects. After an outage every amplifier and the tuner are asked
  for their state again, since the bus went on living without us.
- **Groups**: a `platform: group` media player is fine for on/off and volume,
  but **never send next/previous track to a group**. Each member would ask the
  shared tuner for the next station and it would jump once per member. Drive the
  station from a single reference amplifier instead, as the dashboard below does.

```yaml
# configuration.yaml — on/off and volume only
media_player:
  - platform: group
    name: Radio Suite (room)
    entities:
      - media_player.radio_suite
      - media_player.radio_suite_sdb
```

### Dashboard

[`examples/dashboard-radios.yaml`](examples/dashboard-radios.yaml) is a ready to
paste "Radios" view: the shared tuner at the top with its two station buttons,
then one section per room with a volume slider and, where a room holds two
amplifiers, a pair of on/off buttons — plus a "turn every amplifier off" button.

Paste the `- title: Radios` item into the `views:` list of your own dashboard
(raw configuration editor) rather than over the whole file, and adapt the entity
ids to your own `name:` values. The station buttons address the kitchen
amplifier and nothing else, for the reason given just above.

### Experimental / not verified on hardware

Everything below is built from the Legrand WHO=22 specification and was never
seen on the bus of the installation this fork was developed against. It may
behave differently, or not at all.

- **`volume_set`** writes dimension 1 (`*#22*3#<a>#<p>*#1*<volume>##`). Only the
  relative steps (WHAT 3 and 4) were observed; the write is not echoed back as
  an event, which is why the entity updates optimistically.
- **WHAT 35** (`amplifier_on`, "turn on and select that source"). The
  integration sends the observed WHAT 1 form instead.
- **The spec form of the station and seek commands** (`*22*9#*2#<source>##`,
  `*22*5#*2#<source>##`). They end on an empty WHAT parameter, which OWNd builds
  but marks invalid; nothing reads that mark before sending, so
  `myhome.send_message` does put them on the bus — what the gateway makes of
  them is the unknown. The integration sends the observed
  `*22*9*5#3#<area>#<point>##` instead, which is itself a frame that was
  captured going the other way: the wall control announcing a station change to
  the clients, replayed here as a command.
- **AM display.** Any modulation other than FM is printed in kHz, untested; the
  installation this was written against only has an FM tuner.
- **Turning off with an area parameter of 0** (`*22*0#4#0*3#<a>#<p>##`), which
  is outside the `[1-9]` range of the spec. It is what the wall command emitted,
  so it is what the integration sends.
- **Area commands.** `*22*<what>#<mm>#<a>*4#<area>##` is read as "turn this
  area on/off" and reflected on the amplifiers of that area. The spec lists the
  address, no command session uses it and it was never seen on the bus; the
  amplifiers report their own state a moment later either way.
- **Setting a frequency** has no dedicated service. The existing
  `myhome.send_message` service can write dimension 11 on a source:

```yaml
action: myhome.send_message
data:
  gateway: "00:03:50:11:22:33"
  message: "*#22*5#2#1*#11*1*10600*14##"   # source 1, FM, 106.00 MHz, preset 14
```

### Installing / migrating from upstream (anotherjulien/MyHOME)

The domain stays `myhome`, so your config entry and your `myhome.yaml` are kept
as they are: there is nothing to reconfigure, and the other platforms behave
exactly as before.

HACS installs a repository's default branch or one of its releases. This fork's
`master` carries the sound diffusion platform once the work is merged; until
then, install manually.

Through HACS, without removing anything first:

1. HACS > 3-dot menu > *Custom repositories*, add `adrael/MyHOME` with the
   *Integration* type.
2. Open MyHOME in HACS and *Download* — it installs over the upstream copy, in
   the same `custom_components/myhome/` folder.
3. Add the `media_player:` block to `myhome.yaml` **now**, so one restart is
   enough.
4. Restart Home Assistant.

Manually, which is what you want before the merge: back up
`/config/custom_components/myhome/`, replace its contents with this repository's
`custom_components/myhome/`, add the `media_player:` block to `myhome.yaml`, and
restart.

To roll back, reinstall the upstream integration **and comment out both the
`media_player:` and the `radio_stations:` keys of `myhome.yaml`** before
restarting: upstream knows neither and will refuse the file.

### Tests

The WHO=22 parser, the frame builders, the configuration schema and the gateway
dispatch are covered by plain pytest, with Home Assistant stubbed:

```sh
pip install -r requirements-dev.txt
pytest
```
