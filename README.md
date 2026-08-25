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
amplifier entity.

### Configuration

In `myhome.yaml`, under the gateway's MAC address. `where` is the amplifier's
address, `3#<area>#<point>`; the short `<area>#<point>` form is accepted too.

```yaml
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
  ampli_tablette:         { where: "3#1#1", name: "Radio Tablette" }
```

Available options:

| Option         | Default        | Description                                              |
| -------------- | -------------- | -------------------------------------------------------- |
| `where`        | *required*     | Amplifier address, `3#<area>#<point>`                     |
| `name`         | *required*     | Device name                                               |
| `entity_name`  | `None`         | Entity name, when it should differ from the device name   |
| `source`       | `1`            | Source (tuner) this amplifier listens to                  |
| `icon`         | `mdi:speaker`  | Entity icon                                               |
| `manufacturer` | `BTicino S.p.A.` | Device manufacturer                                     |
| `model`        | `None`         | Device model                                              |

### Grouping amplifiers per room

Rooms with several amplifiers (a bedroom and its bathroom, for instance) are
best driven as one entity, using Home Assistant's built-in group platform in
`configuration.yaml`:

```yaml
media_player:
  - platform: group
    name: Radio Suite (pièce)
    entities:
      - media_player.radio_suite
      - media_player.radio_suite_sdb
```

### Attributes

Each amplifier exposes `area`, `point`, `frequency_mhz`, `station_name`,
`preset`, `modulation`, `source_id` and `raw_volume` (the bus' 0-31 value).
`media_title` reads e.g. `106.0 MHz · SUD RADIO`; the station names come from a
table of the FM band around Bordeaux in `sound_diffusion.py` and are matched to
the tuner's frequency with a ±0.05 MHz tolerance. Adapt that table to your area.

### Setting a frequency

No dedicated service is provided. The existing `myhome.send_message` service can
write a frequency and its preset directly:

```yaml
service: myhome.send_message
data:
  message: "*#22*5#2#1*#11*1*10600*14##"   # source 1, FM, 106.00 MHz, preset 14
```
