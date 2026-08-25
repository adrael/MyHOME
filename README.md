# What's up?

I'm afraid it's time to be blunt, I cannot maintain this integration any longer, not in any meaningful way at least.

I'm open for someone to take over this and OWNd's repositories.  
I'd strongly prefer someone who has extensive experience with a proper development workflow, since I feel that's something that has been missing from this project.  
I'd love for this to become a core integration one day but I have no idea how much work would be needed to achieve that.

Anyway, If you think you can take over code ownership for this, let me know.

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

The integration needs Home Assistant 2024.3 or later. The example dashboard
needs 2025.1 or later (the `media-player-volume-slider` tile feature);
`show_mute_button` only matters on 2026.6 and above.

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
- **No mute, no pause, no source selection.** The integration offers on/off,
  volume and station, and nothing else. Selecting a source does work on the bus
  (WHAT 35, see below); it is simply not exposed as a feature.
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
then one section per room with a volume slider and a pair of on/off buttons —
plus a "turn every amplifier off" button. Every room gets the pair: tapping a
tile's icon does not toggle a media player.

Paste the `- title: Radios` item into the `views:` list of your own dashboard
(raw configuration editor) rather than over the whole file, and adapt the entity
ids to your own `name:` values. The station buttons address the kitchen
amplifier and nothing else, for the reason given just above.

### Verified on hardware

One session against the installation this fork was written for (gateway F454,
amplifier `3#2#2`, FM tuner `2#1`, 2026-08-25) put every frame the integration
sends on the bus, and both forms of the commands that had two:

| Frame | What the bus did |
| ----- | ---------------- |
| `*22*1#4#<a>*3#<a>#<p>##` — turn on | on; dimension 12 and the volume follow within ~150 ms |
| `*22*0#4#<a>*3#<a>#<p>##` — turn off, spec form | off (`*12*0*10`) |
| `*22*0#4#0*3#<a>#<p>##` — turn off, wall form | off, exactly the same |
| `*#22*3#<a>#<p>*#1*<v>##` — set volume | **absolute**: 10 then 14 leaves it on 14, not 24; echoed within ~150 ms, which is all the optimistic write hides |
| `*22*9#*2#<s>##`, `*22*10#*2#<s>##` — station ± | the tuner moves; dimensions 5, 11 and 6 follow within ~200 ms |
| `*22*9*5#3#<a>#<p>##` — station +, wall form | moves it too |
| `*22*35#4#<a>#<s>*3#<a>#<p>##` — on, on that source | on; two routing events follow |
| `*#22*3#<a>#<p>*12##`, `*#22*3#<a>#<p>*1##`, `*#22*5#2#<s>*11##` — requests | answered, **even with the amplifier off** |

Two consequences worth knowing:

- **Every command comes back from the bus in under 300 ms**, carrying its new
  value. Whatever an amplifier says after a command is therefore what it is
  doing now — a wall switch pressed a tenth of a second later is applied, not
  taken for a late echo.
- **A request addressed to one source is answered by all of them.** Sources 2 to
  4 exist on this bus and are tuned to something; the amplifiers listening to
  source 1 ignore what they say.

The station commands the integration sends (`*22*9#*2#<source>##` and its
previous) end on an empty WHAT parameter. OWNd builds the frame but marks it
invalid, and the `myhome.send_message` service refuses what is marked invalid:
these two cannot be sent by hand through that service, only by the entity.

### Experimental / not verified on hardware

The following was built from the Legrand WHO=22 specification and never seen on
that bus. It may behave differently, or not at all.

- **Area commands.** `*22*<what>#<mm>#<a>*4#<area>##` is read as "turn this
  area on/off" and reflected on the amplifiers of that area. The spec lists the
  address, no command session uses it and it was never seen on the bus; the
  amplifiers report their own state a moment later either way.
- **AM display.** Any modulation other than FM is printed in kHz, untested; the
  installation this was written against only has an FM tuner.
- **Seeking a frequency** (`frequency_seek_up` / `_down`) and **memorising a
  preset** (`store_station`). The first is untried, the second overwrites a
  preset of your installation.
- **Setting a frequency** has no dedicated service. The existing
  `myhome.send_message` service can write dimension 11 on a source — this frame
  carries no empty WHAT parameter, so the service accepts it:

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

Through HACS, without removing anything first:

1. HACS > 3-dot menu > *Custom repositories*, add `adrael/MyHOME` with the
   *Integration* type.
2. Open MyHOME in HACS and *Download* — it installs over the upstream copy, in
   the same `custom_components/myhome/` folder.
3. Add the `media_player:` block to `myhome.yaml` **now**, so one restart is
   enough.
4. Restart Home Assistant.

HACS installs a repository's default branch, which for this fork is `master`
and carries the sound diffusion platform.

Manually, if you would rather not add a custom repository: back up
`/config/custom_components/myhome/`, replace its contents with this repository's
`custom_components/myhome/`, add the `media_player:` block to `myhome.yaml`, and
restart.

To roll back, reinstall the upstream integration **and comment out both the
`media_player:` and the `radio_stations:` keys of `myhome.yaml`** before
restarting: upstream knows neither and will refuse the file.

### First run

Turn the integration's logging up for the first test, in `configuration.yaml`:

```yaml
logger:
  default: warning
  logs:
    custom_components.myhome: debug
```

Every WHO=22 frame the bus emits is then printed, which is the only way to see
what your amplifiers actually answer. Put it back to `warning` once it works:
the sound diffusion bus is chatty.

What to check after the restart:

- **Settings > Devices & services > MyHOME** lists one device per amplifier. If
  it lists none, the `media_player:` block is under the wrong gateway key in
  `myhome.yaml` — it belongs under the gateway whose `mac:` matches your
  config entry. Remember `myhome.yaml` is read when the config entry is set up,
  so every edit needs a restart.
- **The amplifiers are `unavailable`.** That is the gateway session being down,
  not a configuration problem: the entities come back on their own as soon as a
  frame reaches the listener again, and their state is asked for anew.

A short FAQ of what surprises people first:

- **The state is `playing`, never `on`.** See the note above; write
  `is_state('media_player.radio_cuisine', 'playing')`.
- **The station shows no name**, only a frequency: that frequency is not in the
  station table. Add it under the `radio_stations` option of the gateway.
- **Changing station moves the whole house.** There is one tuner. That is the
  installation, not the integration.
- **Never send next/previous track to a group.** The station would jump once per
  member.
- **Sources 2 to 4 answer on the bus** and show up in a debug log. The
  amplifiers listening to source 1 ignore them.

### Tests

The WHO=22 parser, the frame builders, the configuration schema and the gateway
dispatch are covered by plain pytest, with Home Assistant stubbed:

```sh
pip install -r requirements-dev.txt
pytest
```
