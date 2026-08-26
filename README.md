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
and volume step, next/previous station, and picking a station by name from the
source list.

The tuner behind them gets a device of its own — a station dropdown, a frequency
in MHz and four buttons, see [Tuner entities](#tuner-entities). Nothing to
configure: it is derived from the amplifiers you already declared. The name the
station broadcasts over RDS is read too, and shown wherever the station table
has nothing to say.

The integration needs Home Assistant 2024.3 or later. The example dashboard
needs 2025.1 or later (the `media-player-volume-slider` tile feature); the
station dropdown on a tile needs 2026.5 (`media-player-source`) and
`show_mute_button` only matters on 2026.6 and above. The Source menu of the
more-info dialog needs none of that.

All amplifiers of an installation usually share the same source (a single tuner),
so changing station on one amplifier changes it for all of them. The integration
reflects that: the tuning information is read once per gateway and shown on every
amplifier entity listening to that source.

### Configuration

Amplifiers are declared in `/config/myhome.yaml`, under the gateway they belong
to. `where` is the amplifier's address, `3#<area>#<point>`, with the area and the
point both in `[1-9]`.

```yaml
house:
  mac: "00:03:50:11:22:33"
  media_player:
    ampli_cuisine:          { where: "3#7#1", name: "Radio Cuisine" }
    ampli_suite:            { where: "3#2#1", name: "Radio Suite" }
    ampli_suite_sdb:        { where: "3#2#2", name: "Radio Suite SDB" }
    ampli_office_1:         { where: "3#3#1", name: "Radio Office 1" }
    ampli_office_1_sdb:     { where: "3#3#2", name: "Radio Office 1 SDB" }
    ampli_gym:              { where: "3#4#1", name: "Radio Gym" }
    ampli_chambre_ami:      { where: "3#5#1", name: "Radio Chambre Ami" }
    ampli_chambre_ami_sdb:  { where: "3#5#2", name: "Radio Chambre Ami SDB" }
    ampli_office_2:         { where: "3#6#1", name: "Radio Office 2" }
    ampli_office_2_sdb:     { where: "3#6#2", name: "Radio Office 2 SDB" }
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

And two options on the gateway itself:

| Option           | Default           | Description                                                       |
| ---------------- | ----------------- | ----------------------------------------------------------------- |
| `radio_stations` | FM band, Bordeaux | Frequency (MHz) to station name, see below                        |
| `tuning_preset`  | `15`              | Preset (1-15) selecting a station overwrites, see below            |

### Station names

`media_title` reads e.g. `106.0 MHz · SUD RADIO`. The tuner only reports a
frequency, so the name comes from a table matched with a ±0.05 MHz tolerance.
The built-in table covers the FM band around Bordeaux and **is overwritten on
every update**: to keep your own, set the `radio_stations` option on the gateway
rather than editing `sound_diffusion.py`.

```yaml
house:
  mac: "00:03:50:11:22:33"
  radio_stations:
    "106.0": SUD RADIO
    "97.3": NOSTALGIE
    "94.3": EUROPE 2
  media_player:
    ampli_cuisine: { where: "3#7#1", name: "Radio Cuisine" }
```

Frequencies not listed simply show without a name (`101.1 MHz`). Keys are read
as hundredths of MHz, so `106`, `106.0` and `106.004` are the same station:
listing two of them is refused at startup rather than keeping whichever came
last.

### Selecting a station

Every amplifier exposes the station table as its source list, so a station can
be picked by name rather than stepped through:

```yaml
action: media_player.select_source
target:
  entity_id: media_player.radio_cuisine
data:
  source: FRANCE INTER
```

The list is sorted by frequency and holds the names of the table — the built-in
one, or `radio_stations` when the gateway sets it. A name carried by two
frequencies is suffixed with its own (`RELAIS (97.3)`), since Home Assistant
tells two sources apart by their label alone.

**This overwrites one preset of your tuner.** An FM tuner has no "go to
106.0 MHz" command: the only way there is to write the frequency into one of its
fifteen presets, which retunes it at once. The integration therefore always
writes the *same* scratch preset — `tuning_preset`, 15 by default — so the
fourteen others keep whatever you stored in them. Set `tuning_preset` to
whichever slot you are happy to lose:

```yaml
house:
  mac: "00:03:50:11:22:33"
  tuning_preset: 15
```

Two consequences of it being a preset:

- After picking a station the tuner sits on `tuning_preset`, so the next
  **station +** press moves to the preset after it — from 15 it wraps back
  round to preset 1. That is the tuner cycling through its fifteen slots, not
  the integration losing its place.
- Selecting a station **does not turn an amplifier on**, exactly like
  next/previous station: the tuner is shared by the whole installation, and
  which amplifiers play it is a separate question.

`source` is scoped to the **tuner**, like `frequency_mhz` and `preset`: every
amplifier names the station the shared box is on, playing it or not.
`source_list` is always there and selecting works with the amplifier off, so a
dropdown on a switched-off amplifier shows what it would play rather than
nothing at all. `media_channel` is the amplifier-scoped one, and does go quiet
when it stops.

### Tuner entities

The amplifiers are speakers. The box behind them — the one that holds the
frequency and the fifteen presets — is a device of its own, **Tuner FM**, with
six entities:

| Entity | What it does | Frame |
| ------ | ------------ | ----- |
| `select.tuner_fm_station` | The station, picked by name out of the table. The same list and the same frame as an amplifier's Source menu | `*#22*5#2#<s>*#11*1*<freq>*<n>##` |
| `number.tuner_fm_frequency` | The frequency in MHz, 87.5 to 108.0 in 0.05 steps. Reading it is what the tuner reports; setting it retunes | `*#22*5#2#<s>*#11*1*<freq>*<n>##` |
| `button.tuner_fm_seek_up` | Scan upwards to the next station the tuner catches | `*22*5#*2#<s>##` |
| `button.tuner_fm_seek_down` | Scan downwards | `*22*6#*2#<s>##` |
| `button.tuner_fm_next_preset` | Next of the fifteen presets | `*22*9#*2#<s>##` |
| `button.tuner_fm_previous_preset` | Previous preset | `*22*10#*2#<s>##` |

They appear under **Settings > Devices & services > MyHOME**, as a device next
to the amplifiers, and are created as soon as one `media_player` is configured:
nothing is added to `myhome.yaml`. The source of each amplifier says which tuner
it listens to, so a house whose amplifiers all sit on source 1 gets one device
called *Tuner FM*; a bus with several gets *Tuner FM 1*, *Tuner FM 2*, … and one
set of entities each (`number.tuner_fm_2_frequency`, and so on).

`select.tuner_fm_station` is `media_player.select_source` on the box rather than
on a speaker: the same station labels, the same scratch preset, the same frame.
It is the one to drive from a dashboard or an automation — an installation whose
amplifiers all listen to one tuner has ten Source menus doing the same thing, and
one Station select saying so.

```yaml
action: select.select_option
target:
  entity_id: select.tuner_fm_station
data:
  option: FRANCE CULTURE
```

Its state is the station the tuner is on, matched to the table within 0.05 MHz,
and *unknown* while the tuner sits on a frequency the table does not carry —
after a seek, typically. It carries `frequency_mhz`, `preset` and `rds_name` as
attributes, and it is available whenever the gateway is, whatever the amplifiers
are doing.

Setting the frequency is `media_player.select_source` without the station table:

```yaml
action: number.set_value
target:
  entity_id: number.tuner_fm_frequency
data:
  value: 101.1
```

**It spends the same scratch preset** — `tuning_preset`, 15 by default — for the
same reason: an FM tuner is only sent to a frequency by having it written into
one of its slots. Everything said under "Selecting a station" applies unchanged,
including that it does not turn any amplifier on.

The two **seek** buttons are the tuner's own automatic scan, and they are the
only control here that is not a preset. Seeking upwards reports the frequency it
landed on and nothing else, so pressing either of them clears the `preset`
attribute straight away and it stays away until the tuner sits on a slot again
(seeking downwards past one puts it back). That is the tuner, not the
integration losing count.

The entities follow the gateway connection like the amplifiers do, and they are
tuner-scoped throughout: the frequency and the station are what the shared box is
on, whether a single amplifier is playing them or not.

### RDS

The tuner tells us what the station calls itself. **Verified on hardware**
(2026-08-26): asked once per source with `*22*31*2#<s>##`, it answers
`*#22*5#2#<s>*10*<c1>*…*<c8>##` — eight ASCII codes, the RDS *programme service*
name — and keeps sending one per text it receives, station changes included. The
request is repeated only after a reconnection; nothing polls it, and there is no
reading it on demand: the dimension 10 *request* is refused by the gateway.

It surfaces as the `rds_name` attribute of every amplifier of that source and of
`select.tuner_fm_station`, and as the station name itself — `media_channel`,
`station_name`, the second half of `media_title` — **wherever the station table
carries nothing at that frequency**:

| Frequency | Table | RDS | `media_title` |
| --------- | ----- | --- | ------------- |
| 97.7 | `FRANCE CULTURE` | anything | `97.7 MHz · FRANCE CULTURE` |
| 88.3 | — | `SKYROCK` | `88.3 MHz · SKYROCK` |
| 88.3 | — | — | `88.3 MHz` |

The table wins because it is what you configured: it names a station the way the
rest of your dashboard does, and a tuner sitting between two frequencies cannot
make it drift. RDS covers what the table does not.

`rds_name` is empty until the radio sends something — a tuner that has just been
retuned sends eight spaces, which is held as no name at all — and it is dropped
as soon as the frequency moves, the new one arriving a moment later. Like the
frequency and the preset it describes the shared box, so it is published whether
an amplifier is playing or not.

Nothing stops the stream: `*22*32*2#<s>##` works (it answers `*25*0*0*0##`, a
dimension neither the spec nor this integration knows anything about) but the
integration never sends it. Eight characters now and then cost nothing, and the
wall controls read the same tuner.

### Attributes

Each amplifier exposes `area`, `point` and `source_id`, plus `raw_volume` (the
bus' 0-31 value) once it is known. The tuner is one box shared by the whole
installation, so `frequency_mhz`, `station_name`, `rds_name` and `preset` are
published as soon as they are known, **whether that amplifier is playing or
not** — a dashboard can show the station with the whole house switched off.
`modulation` is added only when it is not FM (2 long wave, 3 medium wave, 4 short
wave).

Attributes without a value are left out, so an amplifier of a gateway whose
tuner never answered carries only its addressing.

`preset` disappears when one of the seek buttons is pressed. Seeking upwards
reports the new frequency and nothing else — verified on hardware — so the slot
number we hold would be stale, and it is dropped rather than shown as if it were
still true. The frequency and the station name stay; the preset comes back on
the next frame that carries one. A seek done at a *wall control* is invisible to
us, so the preset shown until then is the one the tuner started from.

What comes out of *this* amplifier is a different matter: `media_title`,
`media_channel` and `media_content_type` are `None` unless it is playing.

### Behaviour & limitations

- **The tuner is shared per source.** Changing station on one amplifier changes
  it on every amplifier listening to that source. There is no way around it: the
  bus has one tuner.
- **Volume is a 0-31 integer**, so the slider moves in 32 steps. Home Assistant's
  0..1 level is rounded to the nearest of them.
- **No mute, no pause.** The integration offers on/off, volume and station, and
  nothing else. Home Assistant's "source" is used for the *stations* of the
  tuner; moving an amplifier to another *bus source* does work (WHAT 35, see
  below) but is not exposed as a feature.
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
- **Frames of systems this fork does not support are ignored quietly.** Video
  door entry (WHO 6 and 7) and door entry (WHO 8) are modelled by neither OWNd
  0.7.48 nor this integration: `OWNEvent.parse` has no branch for them and hands
  the frame back as raw text, exactly as it does for WHO=22. `*6*10*4000##` and
  `*8*19*20##` were both seen on this bus. They are logged at debug level as
  *Ignoring unsupported WHO*, rather than warned about once per call or per
  press. A WHO nobody expected still warns.
- **OWNd cannot parse a time write without a timezone** (WHO=13), which a
  gateway sends on its own: its parser raises an `IndexError`, `get_next`
  answers nothing and logs *Event session crashed.* with a traceback. The
  listener already treats that as "one frame lost, the socket is fine"; the
  traceback is downgraded to debug (`OWNd could not read a frame`), since it is
  an upstream bug about a frame this integration does not read. Everything else
  OWNd logs is left alone.
- **An entity disabled in the registry comes back on the next restart**, enabled.
  This is upstream behaviour and this fork does not change it: on every setup,
  `__init__.py` prunes the registry of what it cannot find in `hass.data`, and
  `hass.data` is filled by the entities *as they are added*. A disabled entity is
  never added, so its unique id is missing from that list, its registry entry is
  removed as an orphan — and it is created afresh, enabled, the next time round.
  **Hide** the entity instead of disabling it (a hidden entity is still added, so
  it survives the prune), or take the device out of `myhome.yaml` altogether.
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
paste "Radios" view: the shared tuner at the top, then one tile per amplifier
grouped by room. Tapping a tile's icon toggles that amplifier, tapping the tile
opens its more-info dialog, and the slider sets the volume.

The Tuner section is the tuner device and nothing else: what it is playing on
three attribute rows, `select.tuner_fm_station` as a dropdown (the
`select-options` tile feature), `number.tuner_fm_frequency` as a slider (the
`numeric-input` tile feature, Home Assistant 2024.11+), the four tuner buttons,
and a "turn every amplifier off" button. Only the attribute rows read an
amplifier, and only to display — every control there addresses the tuner, which
is the point: one tuner, one place to drive it, no risk of sending a station
step once per member of a group.

The kitchen tile keeps the station dropdown of the *amplifier*
(`media-player-source`, Home Assistant 2026.5+) as well, for the room where one
usually reaches for it. On an older Home Assistant, drop that feature and use
`select.tuner_fm_station`, or the Source menu of any amplifier's more-info
dialog.

Paste the `- title: Radios` item into the `views:` list of your own dashboard
(raw configuration editor) rather than over the whole file, and adapt the entity
ids to your own `name:` values.

### Verified on hardware

Two sessions against the installation this fork was written for (gateway F454,
amplifier `3#2#2`, FM tuner `2#1`, 2026-08-25 and 2026-08-26) put every frame
the integration sends on the bus, and both forms of the commands that had two:

| Frame | What the bus did |
| ----- | ---------------- |
| `*22*1#4#<a>*3#<a>#<p>##` — turn on | on; dimension 12 and the volume follow within ~150 ms |
| `*22*0#4#<a>*3#<a>#<p>##` — turn off, spec form | off (`*12*0*10`) |
| `*22*0#4#0*3#<a>#<p>##` — turn off, wall form | off, exactly the same |
| `*#22*3#<a>#<p>*#1*<v>##` — set volume | **absolute**: 10 then 14 leaves it on 14, not 24; echoed within ~150 ms, which is all the optimistic write hides |
| `*22*9#*2#<s>##`, `*22*10#*2#<s>##` — station ± | the tuner moves; dimensions 5, 11 and 6 follow within ~200 ms |
| `*22*9*5#3#<a>#<p>##` — station +, wall form | moves it too |
| `*22*5#*2#<s>##` — seek up, automatic | the tuner jumps to the next station it catches and answers `*#22*5#2#1*5*1*10730##` — **dimension 5 alone**, no 11 and no 6, so the preset it was on is left behind |
| `*22*6#*2#<s>##` — seek down, automatic | same, plus `*#22*5#2#1*11*1*10680*15##` when the frequency falls back onto a stored preset |
| `*#22*5#2#<s>*#11*<mod>*<freq>*<n>##` — retune | retunes at once (~250 ms) **and overwrites preset `n + 1`**: `*0` came back as `*11*1*8970*1##`, so preset 15 is written as `*14` |
| `*22*35#4#<a>#<s>*3#<a>#<p>##` — on, on that source | on; two routing events follow |
| `*22*31*2#<s>##` — start RDS | the tuner answers `*#22*5#2#<s>*10*<c1>*…*<c8>##` within ~350 ms, then one per RDS text it receives, station changes included |
| `*22*32*2#<s>##` — stop RDS | answered `*#22*5#2#<s>*25*0*0*0##`; **dimension 25 is unknown** — it is in neither the spec nor this integration, and what it means is anyone's guess |
| `*#22*3#<a>#<p>*12##`, `*#22*3#<a>#<p>*1##`, `*#22*5#2#<s>*11##` — requests | answered, **even with the amplifier off** |

Two consequences worth knowing:

- **Every command comes back from the bus in under 300 ms**, carrying its new
  value. Whatever an amplifier says after a command is therefore what it is
  doing now — a wall switch pressed a tenth of a second later is applied, not
  taken for a late echo.
- **A request addressed to one source is answered by all of them.** Sources 2 to
  4 exist on this bus and are tuned to something; the amplifiers listening to
  source 1 ignore what they say.
- **The tuner holds fifteen presets and cycles through them.** Stepping past
  preset 15 lands on preset 1, which is why selecting a station spends the last
  slot by default.
- **A scan says less than a preset step does.** Seeking upwards reports a
  frequency and stops there, so the preset number we hold is stale — see the
  `preset` attribute above. A preset *step*, on the other hand, answers with a
  frequency (dimension 5) and then its slot (dimension 11) about 20 ms later,
  which is why the frequency alone is not read as "the preset is gone". The band
  was driven from 87.7 to 107.3 MHz, every frequency accepted.

The RDS commands are **not** in the form the specification gives them.
`*22*31#<s>##` and `*22*32#<s>##` (§3.1.10 and §3.1.11, the source as a WHAT
parameter) are refused by the gateway — NACK, no event — while the same WHATs
addressed to the source as a WHERE, `*22*31*2#<s>##`, are accepted. Reading
dimension 10 is refused in both forms (`*#22*5#2#1*10##` and `*#22*2#1*10##`), so
the stream is the only way to that name.

The four frames the tuner buttons send (`*22*5#`, `*22*6#`, `*22*9#`, `*22*10#`,
all addressed `*2#<source>##`) end on an empty WHAT parameter. OWNd builds them
but marks them invalid, and the `myhome.send_message` service refuses what is
marked invalid: none of the four can be sent by hand through that service, only
by pressing the button — or, for the two station ones, by the amplifier's
next/previous track. Writing dimension 11, which the frequency uses, has no such
parameter and goes through `send_message` fine.

### Experimental / not verified on hardware

The following was built from the Legrand WHO=22 specification and never seen on
that bus. It may behave differently, or not at all.

- **Area commands.** `*22*<what>#<mm>#<a>*4#<area>##` is read as "turn this
  area on/off" and reflected on the amplifiers of that area. The spec lists the
  address, no command session uses it and it was never seen on the bus; the
  amplifiers report their own state a moment later either way.
- **AM display.** Any modulation other than FM is printed in kHz, untested; the
  installation this was written against only has an FM tuner.
- **Seeking by a given step** (`frequency_seek_up(step=…)`). The automatic
  form, which the two seek buttons send, is verified; passing a step is not.
- **Memorising the current frequency on a preset** (`store_station`, WHAT 33).
  Untried, and it overwrites a preset of your installation. Writing dimension
  11, which `select_source` and `number.set_value` use, is verified and does not
  need it.

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

To roll back, reinstall the upstream integration **and comment out the
`media_player:`, `radio_stations:` and `tuning_preset:` keys of
`myhome.yaml`** before restarting: upstream knows none of them and will refuse
the file.

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

- **Settings > Devices & services > MyHOME** lists one device per amplifier,
  plus the *Tuner FM* device. If it lists none, the `media_player:` block is
  under the wrong gateway key in
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
  member. `select_source` is absolute and safe to repeat, but it still moves the
  whole house.
- **Picking a station changed my preset 15.** It is meant to: see "Selecting a
  station" and the `tuning_preset` option. Setting
  `number.tuner_fm_frequency` spends the same slot.
- **The Preset row went blank after a seek.** The tuner left the slot it was on
  and only reports a frequency; see "Tuner entities". It comes back on the next
  frame carrying a slot number.
- **Sources 2 to 4 answer on the bus** and show up in a debug log. The
  amplifiers listening to source 1 ignore them.

### Tests

The WHO=22 and WHO=8 parsers, the frame builders, the configuration schema and
the gateway dispatch are covered by plain pytest, with Home Assistant stubbed:

```sh
pip install -r requirements-dev.txt
pytest
```

## Video door entry (WHO=8)

A BTicino/Legrand video door entry system (WHO=8) exposed as four standard Home
Assistant entities per entrance panel. **Verified on hardware** (gateway F454,
entrance panel 20, indoor unit 21, gate strike on activation address 20,
2026-08-26): the doorbell ring, the auto-on, the session end and the gate-open
echo were all seen on the bus, and the web control that opens the gate put
`*8*19*20##` on it. Everything but the camera wiring through Home Assistant is
confirmed end to end; see "Verified on hardware" below for what is not.

Neither OWNd 0.7.48 nor this integration used to model WHO=8: the frames reached
the listener as raw text and were logged as *Ignoring unsupported WHO*. They now
feed these entities **when — and only when — a `video_door_entry:` block is
configured**. On an installation without one, nothing changes: WHO 6, 7 and 8
stay quiet debug lines.

### Entities

Per entrance panel, keyed `8-<entrance_address>`:

- **`event.<name>_doorbell`** — an `event` entity, device class `doorbell`,
  firing a single `ring` event each time the bell is pressed. This is the one to
  trigger automations on; see the example below.
- **`button.<name>_open`** — pulses the gate strike open (`*8*19*<addr>##` then
  the release `*8*20*<addr>##`).
- **`binary_sensor.<name>_call_in_progress`** — device class `running`, on from
  the ring until the bus reports the session ended, with a safety timeout
  (`call_timeout`, 60 s) in case the end is never sent.
- **`camera.<name>_camera`** — a still from the panel's own `telecamera.php`,
  created only when a `camera_password` is set. The panel's camera is live only
  during a call or an auto-on, so a snapshot opens a video session first; it is
  taken at most once every two seconds, since the panel saturates under load.

A ring (`*8*1#1#…`) and an **auto-on** (`*8*1#5#…`, someone looking at the
camera) look alike and mean opposite things: only the ring rings. The panel
address travels in a separate caller-id frame, so a ring cannot be tied to one
panel — on the usual single-panel install it reaches the one that is there.

### Configuration

Under a gateway, next to `media_player:` and the others:

```yaml
# myhome.yaml
video_door_entry:
  entrance_panel:                # the device key; one block per panel
    name: "Front gate"
    entrance_address: 20         # entrance panel (EP) address, default 20
    lock_address: 20             # gate-strike activation address, default = entrance_address
    camera_where: 4000           # 4000 + camera number, default 4000
    camera_password: "0123456789abcdef0123456789abcdef"   # in clear or MD5 of the OPEN bus password; omit to skip the camera
    camera_host: 192.168.0.10    # optional, default = the gateway host
    verify_ssl: false            # the panel serves the snapshot with a self-signed cert
    call_timeout: 60             # seconds before the call sensor gives up on a missing session end
```

Nothing here is baked into the code: every address, the camera password and the
host come from the file. `camera_password` is the value the panel's own web page
sends as `CAM_PASSWD` — usually the MD5 of the OPEN bus password. Keep it in
`secrets.yaml` and reference it with `camera_password: !secret f454_cam_password`.

### Example automation — ring to a phone with a snapshot

An `event` entity fires by bumping its state, so trigger on a state change and
attach the camera image:

```yaml
automation:
  - alias: Doorbell ring notification
    trigger:
      - platform: state
        entity_id: event.front_gate_doorbell
    condition: "{{ trigger.to_state.state not in ['unknown', 'unavailable'] }}"
    action:
      - service: notify.mobile_app_your_phone
        data:
          message: "Someone at the front gate"
          data:
            image: "/api/camera_proxy/camera.front_gate_camera"
```

### Dashboard

[`examples/dashboard-videophone.yaml`](examples/dashboard-videophone.yaml) is a
ready-to-paste card: the camera as a picture-glance with the Open button on it,
the doorbell event and the call-in-progress sensor below. Entity ids follow the
`name:` of the panel, exactly as the amplifiers do.

### Limitations & verified on hardware

- **No audio, no conversation.** The F454 carries no two-way audio to Home
  Assistant; this integration rings, shows a picture and opens the gate, and
  that is all. Talking to whoever rang is done at the indoor unit.
- **The camera is live only during a session.** Outside a call or an auto-on the
  panel returns a black ~1.2 KB frame. The camera entity opens a session before
  each snapshot, but a snapshot taken with nobody there is still black.
- **Do not run several sending workers with the gate button.** The two open
  frames (energise, release) are queued in order and, with the default single
  `command_worker_count`, leave the gateway in order. Configure more workers and
  the order is no longer guaranteed, which can leave the strike energised.
- **Verified on hardware**: the ring / auto-on / caller-id / session-end frames,
  and that `*8*19*20##` opens the strike (the web control produced it on the
  bus). **Not yet verified from Home Assistant**: that pressing the Open button
  actually drives the gate, and that a snapshot returns a live frame during a
  call — both are *read from the protocol*, not exercised through this
  integration.
