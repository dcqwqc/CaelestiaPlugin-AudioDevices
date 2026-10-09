#!/usr/bin/env bash
# Apply / remove / inspect the small Caelestia core hook (services/AudioPresentation.qml
# plus AudioDeviceList, AudioPage, bar audio popout and the output-changed toast).
# Idempotent; refuses rather than half-patching a shell that has drifted.
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
patch="$root/integration/shell-integration.patch"
shell_dir="${CAELESTIA_SHELL_DIR:-$HOME/.config/quickshell/caelestia}"
state="${XDG_STATE_HOME:-$HOME/.local/state}/caelestia-audio-devices"
files=(services/AudioPresentation.qml services/Audio.qml modules/nexus/common/AudioDeviceList.qml modules/nexus/pages/AudioPage.qml modules/bar/popouts/Audio.qml)

status() {
    if git -C "$shell_dir" apply --reverse --check "$patch" 2>/dev/null; then echo applied
    elif git -C "$shell_dir" apply --check "$patch" 2>/dev/null; then echo absent
    else echo conflict; fi
}

backup() {
    local dir="$state/backups/$(date +%Y%m%d-%H%M%S)-$1"
    mkdir -p "$dir"
    for f in "${files[@]}"; do
        [ -f "$shell_dir/$f" ] && install -D -m 0644 "$shell_dir/$f" "$dir/$f"
    done
    echo "$dir"
}

case "${1:-status}" in
    status) status ;;
    apply)
        case "$(status)" in
            applied) echo "Shell integration already applied." ;;
            absent)
                b="$(backup pre-apply)"
                git -C "$shell_dir" apply "$patch"
                echo "Shell integration applied (backup: $b)."
                printf '%s\t%s\tapply\t%s\n' "$(date -Is)" "$shell_dir" "${files[*]}" >> "$state/integration.log" ;;
            *) echo "Shell files differ from what the patch expects; nothing changed. See $patch." >&2; exit 2 ;;
        esac ;;
    remove)
        case "$(status)" in
            absent) echo "Shell integration not present." ;;
            applied)
                b="$(backup pre-remove)"
                git -C "$shell_dir" apply --reverse "$patch"
                echo "Shell integration removed (backup: $b)."
                printf '%s\t%s\tremove\t%s\n' "$(date -Is)" "$shell_dir" "${files[*]}" >> "$state/integration.log" ;;
            *) echo "Patched files were edited since install; not reverting automatically. Backups: $state/backups" >&2; exit 2 ;;
        esac ;;
    *) echo "usage: $0 status|apply|remove" >&2; exit 64 ;;
esac
