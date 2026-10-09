#!/usr/bin/env bash
# Installs dcqwqc/audiodevices. Safe to re-run. Never restarts PipeWire/WirePlumber,
# never changes the default device or card profile.
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
plugins="${XDG_DATA_HOME:-$HOME/.local/share}/caelestia/plugins"
link="$plugins/audio-devices"

echo "Running tests..."
node --test "$root/tests/test_model.mjs" >/dev/null
python3 "$root/tests/test_helper.py" >/dev/null 2>&1 || { python3 "$root/tests/test_helper.py"; exit 1; }
"$root/scripts/audio-devices-helper.py" snapshot >/dev/null

chmod 0755 "$root/scripts/"*.py "$root/scripts/"*.sh
mkdir -p "$plugins"
if [ -e "$link" ] && [ "$(readlink -f "$link")" != "$root" ]; then
    echo "$link exists and is not this checkout; leaving it alone." >&2
    exit 1
fi
ln -sfn "$root" "$link"

# Shell first applies the core hook (Quickshell hot-reloads once), then the plugin registers.
"$root/scripts/shell-integration.sh" apply
python3 "$root/scripts/plugin-enable.py" enable
echo "Installed dcqwqc/audiodevices. Configure it in Caelestia settings > Plugins > AudioDevices."
