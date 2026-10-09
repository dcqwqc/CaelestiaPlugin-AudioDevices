#!/usr/bin/env python3
"""Read-only audio snapshot plus explicit, verified device selection for the
Caelestia Audio Devices plugin.

snapshot        -> compact JSON (port availability, profile alternates, Spatial Audio state)
select '<json>' -> switch the card profile if needed (with rollback), then make the
                   endpoint the default, optionally keeping Spatial Audio in the path.

Never restarts PipeWire/WirePlumber, never toggles profiles on its own, never
stores numeric PipeWire ids.
"""
from __future__ import annotations

import fcntl
import json
import os
import subprocess
import sys
import time
from pathlib import Path

SPATIAL_PREFIX = "caelestia_spatial_audio"
EXCLUDED_PROFILES = {"off", "pro-audio"}
RUNTIME_DIR = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp"))
SPATIAL_STATUS = RUNTIME_DIR / "caelestia-spatial-audio" / "status.json"
LOCK = RUNTIME_DIR / "caelestia-audio-devices.lock"


def spatial_controller() -> Path | None:
    override = os.environ.get("CAELESTIA_SPATIAL_CTL")
    candidates = [Path(override)] if override else []
    data = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    candidates.append(data / "caelestia/plugins/spatialaudio/scripts/spatial-audio-controller.py")
    for path in candidates:
        if path.is_file() and os.access(path, os.X_OK):
            return path
    return None


class System:
    """Everything that touches the outside world. Tests replace this."""

    def run(self, args: list[str], timeout: float = 5.0) -> tuple[int, str]:
        try:
            proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return 127, str(exc)
        return proc.returncode, proc.stdout

    def pactl_json(self, what: str) -> list:
        code, out = self.run(["pactl", "-f", "json", "list", what])
        if code != 0:
            return []
        try:
            data = json.loads(out)
        except json.JSONDecodeError:
            return []
        return data if isinstance(data, list) else []

    def default(self, kind: str) -> str:
        code, out = self.run(["pactl", "get-default-sink" if kind == "sink" else "get-default-source"])
        return out.strip() if code == 0 else ""

    def set_default(self, kind: str, name: str) -> bool:
        cmd = "set-default-sink" if kind == "sink" else "set-default-source"
        return self.run(["pactl", cmd, name])[0] == 0

    def set_profile(self, card: str, profile: str) -> bool:
        return self.run(["pactl", "set-card-profile", card, profile])[0] == 0

    def spatial_status(self) -> dict:
        try:
            data = json.loads(SPATIAL_STATUS.read_text())
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def spatial(self, *args: str) -> bool:
        ctl = spatial_controller()
        if not ctl:
            return False
        return self.run([str(ctl), *args], timeout=15.0)[0] == 0

    def has_spatial(self) -> bool:
        return spatial_controller() is not None

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)


def port_direction(port_name: str) -> str:
    if port_name.startswith("[Out]"):
        return "sink"
    if port_name.startswith("[In]"):
        return "source"
    return ""


def bare_port(port_name: str) -> str:
    for prefix in ("[Out] ", "[In] "):
        if port_name.startswith(prefix):
            return port_name[len(prefix):]
    return port_name


def availability(text: str | None) -> str:
    t = (text or "").lower()
    if t == "available":
        return "yes"
    if t == "not available":
        return "no"
    return "unknown"


def card_ports(card: dict) -> dict:
    ports = card.get("ports") or {}
    if isinstance(ports, list):  # older pactl
        return {p.get("name", ""): p for p in ports if isinstance(p, dict)}
    return ports if isinstance(ports, dict) else {}


def alsa_card_name(card: dict) -> str:
    props = card.get("properties") or {}
    return str(props.get("api.alsa.card.name") or props.get("alsa.card_name") or props.get("alsa.id") or "")


def profile_ports(card: dict) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for pname, port in card_ports(card).items():
        for prof in port.get("profiles") or []:
            result.setdefault(prof, set()).add(pname)
    return result


def choose_profile(card: dict, port_name: str) -> str | None:
    """Best profile exposing port_name while keeping as many of the currently
    active ports as possible. Never 'off' or 'pro-audio', never an unavailable one."""
    active = card.get("active_profile") or ""
    profiles = card.get("profiles") or {}
    port = card_ports(card).get(port_name)
    if not port:
        return None
    if active in (port.get("profiles") or []):
        return active
    keep = profile_ports(card).get(active, set())
    by_profile = profile_ports(card)
    best = None
    best_score = None
    for prof in port.get("profiles") or []:
        if prof in EXCLUDED_PROFILES:
            continue
        info = profiles.get(prof)
        if not isinstance(info, dict) or info.get("available") is False:
            continue
        score = (len(keep & by_profile.get(prof, set())), int(info.get("priority") or 0))
        if best_score is None or score > best_score:
            best, best_score = prof, score
    return best


def node_port(node: dict) -> str:
    profile = str((node.get("properties") or {}).get("device.profile.name") or "")
    parts = profile.split(":")
    if len(parts) == 3:
        return parts[1].strip()
    return bare_port(str(node.get("active_port") or ""))


def node_info(node: dict, card_by_name: dict) -> dict:
    props = node.get("properties") or {}
    active = str(node.get("active_port") or "")
    port = next((p for p in node.get("ports") or [] if p.get("name") == active), None)
    card = card_by_name.get(str(props.get("api.alsa.card.name") or props.get("alsa.card_name") or ""))
    return {
        "available": availability(port.get("availability")) if port else "unknown",
        "port": node_port(node),
        "portType": str(port.get("type") or "") if port else "",
        "availabilityGroup": str(port.get("availability_group") or "") if port else "",
        "card": card.get("name") if card else "",
    }


def snapshot(sys_: System) -> dict:
    cards = sys_.pactl_json("cards")
    sinks = sys_.pactl_json("sinks")
    sources = [s for s in sys_.pactl_json("sources") if (s.get("properties") or {}).get("device.class") != "monitor"]
    card_by_alsa = {alsa_card_name(c): c for c in cards if alsa_card_name(c)}

    nodes: dict[str, dict] = {}
    for node in sinks + sources:
        name = node.get("name")
        if name:
            nodes[name] = node_info(node, card_by_alsa)

    alternates = []
    for card in cards:
        active = card.get("active_profile") or ""
        cname = alsa_card_name(card)
        if not cname:
            continue
        for pname, port in card_ports(card).items():
            kind = port_direction(pname)
            if not kind or active in (port.get("profiles") or []):
                continue
            avail = availability(port.get("availability"))
            if avail == "no":
                continue  # e.g. headphone jack empty: never advertise a dead endpoint
            profile = choose_profile(card, pname)
            if not profile:
                continue
            alternates.append({
                "kind": kind,
                "card": card.get("name"),
                "cardName": cname,
                "port": bare_port(pname),
                "description": port.get("description") or bare_port(pname),
                "type": port.get("type") or "",
                "available": avail,
                "availabilityGroup": port.get("availability_group") or "",
                "profile": profile,
                "activeProfile": active,
            })

    st = sys_.spatial_status()
    return {
        "ok": True,
        "time": time.time(),
        "defaultSink": sys_.default("sink"),
        "defaultSource": sys_.default("source"),
        "nodes": nodes,
        "alternates": alternates,
        "cards": [
            {"name": c.get("name"), "cardName": alsa_card_name(c), "activeProfile": c.get("active_profile")}
            for c in cards
        ],
        "spatial": {
            "installed": sys_.has_spatial(),
            "active": bool(st.get("active")),
            "physical": st.get("physical"),
            "mode": st.get("mode"),
            "virtual": st.get("virtual"),
        },
    }


def find_port_node(sys_: System, card: dict, port: str, kind: str) -> str | None:
    cname = alsa_card_name(card)
    for node in sys_.pactl_json("sinks" if kind == "sink" else "sources"):
        props = node.get("properties") or {}
        if props.get("device.class") == "monitor":
            continue
        if str(props.get("api.alsa.card.name") or props.get("alsa.card_name") or "") != cname:
            continue
        if node_port(node) == port:
            return node.get("name")
    return None


def wait_for(fn, sys_: System, timeout: float, step: float = 0.2):
    deadline = timeout
    while True:
        value = fn()
        if value:
            return value
        if deadline <= 0:
            return None
        sys_.sleep(step)
        deadline -= step


def ensure_port(sys_: System, card_name: str, port: str, kind: str) -> dict:
    """Make card_name expose port. Rolls back on failure."""
    card = next((c for c in sys_.pactl_json("cards") if c.get("name") == card_name), None)
    if not card:
        return {"ok": False, "error": "Sound card not found"}
    full = ("[Out] " if kind == "sink" else "[In] ") + port
    meta = card_ports(card).get(full)
    if not meta:
        return {"ok": False, "error": f"{port} is not a port of this card"}
    if availability(meta.get("availability")) == "no":
        return {"ok": False, "error": f"{port} is not plugged in"}

    previous = card.get("active_profile") or ""
    target = choose_profile(card, full)
    if not target:
        return {"ok": False, "error": f"No usable profile exposes {port}"}

    changed = False
    if target != previous:
        if not sys_.set_profile(card_name, target):
            return {"ok": False, "error": "Profile change was refused"}
        changed = True

    node = wait_for(lambda: find_port_node(sys_, card, port, kind), sys_, 5.0 if changed else 0.0)
    if not node:
        if changed and previous:
            sys_.set_profile(card_name, previous)
        return {"ok": False, "error": f"{port} did not appear; profile restored", "rolledBack": changed}
    return {"ok": True, "node": node, "profile": target, "previousProfile": previous, "profileChanged": changed}


def spatial_ready(sys_: System, target: str):
    st = sys_.spatial_status()
    if st.get("active") and st.get("physical") == target and sys_.default("sink").startswith(SPATIAL_PREFIX):
        return st
    return None


def select(sys_: System, request: dict) -> dict:
    kind = request.get("kind")
    if kind not in ("sink", "source"):
        return {"ok": False, "error": "kind must be sink or source"}
    through_spatial = bool(request.get("spatial")) and kind == "sink" and sys_.has_spatial()
    spatial_was_active = through_spatial and bool(sys_.spatial_status().get("active")) \
        and sys_.default("sink").startswith(SPATIAL_PREFIX)
    through_spatial = through_spatial and spatial_was_active

    result: dict = {"ok": False, "kind": kind, "route": "direct"}
    stopped = False
    try:
        if through_spatial and (request.get("port") or request.get("node")):
            target_now = request.get("node")
            if target_now and sys_.spatial_status().get("physical") == target_now:
                return {"ok": True, "kind": kind, "route": "spatial", "node": target_now, "noop": True}
            # The controller only picks its physical sink on activation, and its
            # output stream is dont-reconnect, so restart it through its own CLI.
            sys_.spatial("stop")
            stopped = True

        if request.get("port"):
            got = ensure_port(sys_, str(request.get("card") or ""), str(request["port"]), kind)
            result.update({k: v for k, v in got.items() if k != "ok"})
            if not got["ok"]:
                return result
            target = got["node"]
        else:
            target = str(request.get("node") or "")
            if not target.strip() or target.startswith(SPATIAL_PREFIX) and through_spatial:
                result["error"] = "Invalid target"
                return result

        if not sys_.set_default(kind, target):
            result["error"] = "Could not set the default device"
            return result
        result.update({"ok": True, "node": target})

        if stopped:
            sys_.spatial("configure", json.dumps({"enabled": True}))
            stopped = False
            st = wait_for(lambda: spatial_ready(sys_, target), sys_, 6.0, 0.25)
            if st:
                result["route"] = "spatial"
            else:
                # Spatial came back on another sink or not at all: never leave the
                # user without the device they asked for.
                sys_.set_default(kind, target)
                result["route"] = "direct"
                result["warning"] = "Spatial Audio could not follow; playing directly"
        return result
    finally:
        if stopped:
            # Failure before activation: bring Spatial Audio back as it was.
            sys_.spatial("configure", json.dumps({"enabled": True}))


def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else "snapshot"
    sys_ = System()
    if cmd == "snapshot":
        print(json.dumps(snapshot(sys_), separators=(",", ":")))
        return 0
    if cmd == "select":
        try:
            request = json.loads(argv[2])
        except (IndexError, json.JSONDecodeError):
            print(json.dumps({"ok": False, "error": "bad request"}))
            return 64
        LOCK.parent.mkdir(parents=True, exist_ok=True)
        with open(LOCK, "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            out = select(sys_, request)
        print(json.dumps(out, separators=(",", ":")))
        return 0 if out.get("ok") else 1
    print(json.dumps({"ok": False, "error": f"unknown command {cmd}"}))
    return 64


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
