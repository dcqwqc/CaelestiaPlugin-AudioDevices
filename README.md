# CaelestiaPlugin-AudioDevices

`dcqwqc/audiodevices` turns Caelestia's raw PipeWire device lists into a few
friendly choices — in the **native** selectors (Nexus › Audio and the bar's
audio popout), not just on a separate page.

| Before | After |
|---|---|
| Meteor Lake-P HD Audio Controller Speaker | Laptop speakers |
| Meteor Lake-P HD Audio Controller HDMI / DisplayPort 1–3 Output | hidden until a display is connected, then *External display N (HDMI/DP)* |
| Meteor Lake-P HD Audio Controller Digital Microphone | Built-in microphone |
| Meteor Lake-P HD Audio Controller Stereo Microphone | *Headset microphone (3.5 mm)*, shown when plugged in |
| Caelestia Spatial Audio (Pan) | Spatial Audio (Pan), with *Laptop speakers · via Spatial Audio* |
| bluez_output.… | the Bluetooth device alias, as soon as it connects |

## Features

- **Rename, hide/unhide, group** each output and input in the plugin's
  settings page. Everything is stored by a stable key: the ALSA card plus UCM
  port (`alsa:sof-hda-dsp:sink:Headphones`), the Bluetooth address
  (`bluez:AA:BB:…:sink`) or the PipeWire `node.name`. Numeric ids are never
  stored, so names survive reboots, replugging and profile switches.
- **Friendly defaults** (toggleable): automatic names for speakers,
  headphones, microphones, HDMI/DP and Bluetooth. Disconnected displays,
  unplugged jacks and inactive virtual or filter routes are hidden. A *Show N
  hidden* row reveals them on demand.
- **The active device is always listed**, even when hidden — including the
  Spatial Audio virtual sink and the physical device it plays through.
- **Groups are presentation-only.** Devices with the same group name *and*
  direction share one row; outputs and inputs never mix. The row always
  selects a real member: the one in use, else the one you last picked in
  settings, else the first one that is plugged in. Revealing shows every
  member individually.
- **Speakers ⇄ Headphones profile switching.** On this laptop, Speaker and
  Headphones live in mutually exclusive HiFi profiles. If the other port is
  plugged in or available, it is offered as *Switches the sound card profile*.
  Selecting it switches the profile by name — preferring the profile that
  keeps the most current ports, and never `off` or `pro-audio` — then waits
  for the real node. If the node does not appear, it restores the previous
  profile. Nothing switches profiles on its own or just to inspect them.
- **Spatial Audio aware.** When Spatial Audio is the default output, choosing a
  physical output keeps Spatial Audio in the path (option *Keep Spatial Audio
  in the path*). Its controller only picks its physical sink when it
  activates, and its output stream is `dont-reconnect`, so the helper uses the
  controller's documented CLI: `stop` → set the default to the new device →
  `configure {"enabled": true}`. It then checks the controller's status. If
  Spatial Audio does not follow, the new device becomes the direct default
  and you get a warning rather than silence. Selecting the device Spatial
  Audio already plays on does nothing.

## Layout

```
manifest.json, Settings.qml       plugin metadata + persisted settings
Main.qml                          provider registered with the shell hook; snapshots, selection
SettingsUi.qml                    rename / hide / group / use, plus status
lib/AudioModel.js                 pure classification, persistence keys, grouping, selection plan
scripts/audio-devices-helper.py   pactl snapshot + verified select (profile, default, Spatial)
scripts/shell-integration.sh      apply | remove | status of the core hook (idempotent, with backups)
integration/shell-integration.patch   the core hook, against caelestia shell 41f1ad5c
tests/test_model.mjs, tests/test_helper.py
```

### Core hook

The patch adds `services/AudioPresentation.qml`, a provider slot that falls
back to the untouched raw lists when no plugin is registered. It also changes:

- `AudioDeviceList.qml`: a new opt-in `kind` property, with entries, sublabels
  and a reveal row.
- `AudioPage.qml`: `kind: "sink"/"source"`.
- `bar/popouts/Audio.qml`: entries and a reveal link.
- `services/Audio.qml`: *Now using …* toasts use friendly names.

`AudioDeviceList` without `kind` behaves exactly as before.

`shell-integration.sh` applies the patch with `git apply` only when
`--check` passes. It backs files up to
`~/.local/state/caelestia-audio-devices/backups/` and logs each change in
`integration.log`. If the shell files have drifted, it refuses rather than
half-patching. Re-running `install.sh` is safe: an already-applied patch is
detected and skipped.

## Install / remove

```
./install.sh     # runs the tests, symlinks ~/.local/share/caelestia/plugins/audio-devices,
                 # applies the core hook (Quickshell hot-reloads once), enables the plugin
./uninstall.sh   # disables, reverts the hook, removes the symlink; keeps saved names
```

Neither script restarts PipeWire/WirePlumber or changes the default device or
card profile.

## Tests

```
node --test tests/test_model.mjs   # classification, keys, persistence, groups, Bluetooth,
                                   # duplicates, hidden-but-active, alternates, selection plans
python3 tests/test_helper.py       # profile choice, rollback, unplugged ports, Spatial reroute
                                   # and its fallback (fake pactl/controller; no PipeWire touched)
```

## Limitations

- Port availability comes from `pactl` (pipewire-pulse). Without it, nodes
  still list, but nothing is auto-hidden for being unplugged.
- A Spatial Audio reroute briefly restarts its filter (about a second of
  silence). While the controller restarts, it also re-applies its own
  hardware-gain normalisation to the new physical sink.
- UCM port names (Speaker/Headphones/HDMI1…) drive the friendly names. Unusual
  cards fall back to their PipeWire description with the vendor prefix
  stripped.
