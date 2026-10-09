#!/usr/bin/env bash
# Removes dcqwqc/audiodevices. Keeps its saved names/hidden/groups in plugins.json
# and the source checkout; leaves audio routing exactly as it is.
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
link="${XDG_DATA_HOME:-$HOME/.local/share}/caelestia/plugins/audio-devices"

python3 "$root/scripts/plugin-enable.py" disable
"$root/scripts/shell-integration.sh" remove
if [ -L "$link" ] && [ "$(readlink -f "$link")" = "$root" ]; then
    rm "$link"
fi
echo "Audio Devices removed; the native selectors show raw PipeWire devices again."
