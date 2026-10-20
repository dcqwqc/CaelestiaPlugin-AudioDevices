#!/usr/bin/env python3
"""Mirai speaker mute recovery. Never changes routing, volume, streams or microphones.

Explicit user mute intent is persisted per internal-speaker sink. Only an unexpected
mute on the currently selected INTERNAL speaker can be healed. Other devices and
manual mute are never overridden. The watcher reconnects after PipeWire restarts.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

SPEAKER = "alsa_output.pci-0000_00_1f.3-platform-skl_hda_dsp_generic.HiFi__Speaker__sink"
STATE_DIR = Path(os.getenv("XDG_STATE_HOME", Path.home() / ".local/state")) / "mirai-audio-guard"
STATE_FILE = STATE_DIR / "explicit-mute.json"
LOG = logging.getLogger("mirai-audio-guard")


def pactl(*args: str) -> str:
    return subprocess.run(["pactl", *args], capture_output=True,
                          text=True, check=True, timeout=4).stdout.strip()


def is_muted(sink: str) -> bool:
    response = pactl("get-sink-mute", sink)
    if response not in ("Mute: yes", "Mute: no"):
        raise ValueError(f"Unrecognized mute state: {response!r}")
    return response == "Mute: yes"


def selected_sink() -> str:
    return pactl("get-default-sink")


def read_intent() -> dict:
    try:
        d = json.loads(STATE_FILE.read_text())
        return d if isinstance(d, dict) and d.get("sink") == SPEAKER else {}
    except (OSError, ValueError, TypeError):
        return {}


def explicit_mute() -> bool:
    return read_intent().get("explicit_mute") is True


def mute_intent_pending() -> bool:
    d = read_intent()
    # A watchdog iteration must not clear newly recorded intent in the brief
    # period between the user action being saved and PipeWire applying mute.
    return d.get("explicit_mute") is True and (
        time.time() - float(d.get("updated_at", 0)) < 3.0
    )


def save_intent(muted: bool) -> None:
    STATE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    content = json.dumps({"sink": SPEAKER, "explicit_mute": bool(muted), "updated_at": time.time()}) + "\n"
    fd, temporary = tempfile.mkstemp(prefix=".intent-", dir=STATE_DIR)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as fp:
            fp.write(content)
            fp.flush()
            os.fsync(fp.fileno())
        os.replace(temporary, STATE_FILE)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def should_heal(current_sink: str, muted: bool, user_muted: bool) -> bool:
    return current_sink == SPEAKER and muted and not user_muted


def check_once(heal: bool = True) -> dict:
    default = selected_sink()
    result = {"selected": default, "speaker_selected": default == SPEAKER,
              "status": "other_output", "recovered": False}
    if default != SPEAKER:
        return result
    muted = is_muted(SPEAKER)
    intent = explicit_mute()
    result.update(muted=muted, explicit_mute=intent)
    if not muted:
        # A volume key, any audio app, or a manual unmute should clear the
        # saved explicit-mute intent, even after the audio service restarted.
        if intent and mute_intent_pending():
            result["status"] = "manual_mute_pending"
            return result
        if intent and heal:
            save_intent(False)
            result["explicit_mute"] = False
        result["status"] = "ready"
    elif intent:
        result["status"] = "user_muted"
    elif not heal:
        result["status"] = "unexpected_mute"
    else:
        # Query again after a grace period to avoid changing an ongoing
        # switch/brief intermediate sink state.
        time.sleep(0.35)
        if should_heal(selected_sink(), is_muted(SPEAKER), explicit_mute()):
            pactl("set-sink-mute", SPEAKER, "0")
            result["recovered"] = True
            result["status"] = "recovered"
            LOG.warning("Restored unexpected mute on Mirai internal speaker")
        else:
            result["status"] = "state_changed"
    return result


def set_explicit(value: str) -> dict:
    sink = selected_sink()
    previous = is_muted(sink)
    muted = not previous if value == "toggle" else value == "1"
    if sink == SPEAKER:
        # Save intent BEFORE applying mute; the background watcher cannot
        # race into an intentional user operation.
        save_intent(muted)
    pactl("set-sink-mute", sink, "1" if muted else "0")
    return {"selected": sink, "muted": muted, "explicit": sink == SPEAKER}


def watch() -> None:
    """Bounded health checks; PipeWire disconnects are retried harmlessly.

    Do not use an unfiltered pactl subscribe event loop: each pactl query
    creates client events, which can otherwise provoke recursive polling.
    """
    LOG.info("Starting bounded audio health checks (every 3 seconds)")
    last_error = None
    while True:
        try:
            result = check_once()
            last_error = None
            if result["recovered"]:
                LOG.info("Internal speaker mute restored; output unchanged")
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            # Retry quietly if audio is briefly unavailable during login/restart.
            msg = str(exc)
            if msg != last_error:
                LOG.warning("Audio graph temporarily unavailable: %s", msg)
                last_error = msg
        time.sleep(3.0)


def main() -> int:
    if os.uname().nodename.lower() != "mirai" and not os.getenv("MIRAI_AUDIO_GUARD_TEST"):
        print("Only for Mirai", file=sys.stderr)
        return 2
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("watch")
    sub.add_parser("status")
    sub.add_parser("check")
    setter = sub.add_parser("set")
    setter.add_argument("value", choices=("0", "1", "toggle"))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        if args.action == "watch":
            watch()
        elif args.action == "status":
            print(json.dumps(check_once(heal=False), sort_keys=True))
        elif args.action == "check":
            print(json.dumps(check_once(), sort_keys=True))
        else:
            print(json.dumps(set_explicit(args.value), sort_keys=True))
        return 0
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        LOG.error("Audio backend unavailable: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
