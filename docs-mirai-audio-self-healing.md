# Mirai speaker audio self-healing

Installs `scripts/mirai-audio-guard.py` as `~/.local/bin/mirai-audio-guard`
and `systemd/mirai-audio-guard.service` as an enabled `systemd --user` unit.

### Behavior
- Observes selected PipeWire audio sink, mute state, and explicit user intent.
- Only heals unsolicited mute on Mirai's exact internal-speaker sink (after
  rechecking selected device and mute status to avoid transient races).
- Never changes default device, per-app stream, volume, mic, spatial effects,
  hardware device profiles, or UE Boombox routing.
- `mirai-audio-guard set toggle` is installed in Hyprland's
  XF86AudioMute and SUPER+SHIFT+M bindings.
- The Caelestia `Audio.setStreamMuted` output path is integrated so buttons
  record intentional mutes. Input mute / individual app mute are unchanged.
- Explicit mute intent persists across login/reboot. Unmuting clears it.
- Recovers after user login or PipeWire/WirePlumber restarts.
- Uses bounded 3-second health checks with timeout and harmless retries if
  the audio backend restarts (avoids recursive client-event feedback).
- `mirai-audio-guard status`: read-only JSON health check.
- `mirai-audio-guard check`: one-shot targeted heal.
- Logs recovery to `journalctl --user -u mirai-audio-guard`.

Intentionally muting via an application that bypasses all integrated system
mute controls cannot be distinguished from an accidental external mute. Use
Caelestia or the hardware mute key for persistent deliberate mute.

### Validation
`python3 -m unittest discover -s tests -p 'test_mirai_audio_guard.py' -v`
Tests mock the audio backend and never mute actual user playback.

### Rollback
`systemctl --user disable --now mirai-audio-guard.service`.
Restore QML and Hypr keys from the 20261020 backups only after checking for
subsequent edits. Do not remove other audio services.
