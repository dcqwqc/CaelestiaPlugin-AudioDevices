#!/usr/bin/env python3
"""python3 -m unittest tests/test_helper.py  (no PipeWire access; fake System)."""
import copy
import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("helper", ROOT / "scripts/audio-devices-helper.py")
H = importlib.util.module_from_spec(spec)
spec.loader.exec_module(H)

CARD = "alsa_card.pci-0000_00_1f.3-platform-skl_hda_dsp_generic"
SPK_PROFILE = "HiFi (HDMI1, HDMI2, HDMI3, Mic1, Mic2, Speaker)"
HP_PROFILE = "HiFi (HDMI1, HDMI2, HDMI3, Headphones, Mic1, Mic2)"
BOTH = [SPK_PROFILE, HP_PROFILE]


def port(desc, typ, avail, profiles, group=""):
    return {"description": desc, "type": typ, "priority": 100, "availability_group": group,
            "availability": avail, "profiles": profiles}


def mirai_card(active=SPK_PROFILE, hp_avail="not available"):
    return {
        "name": CARD,
        "active_profile": active,
        "properties": {"api.alsa.card.name": "sof-hda-dsp", "device.description": "Meteor Lake-P HD Audio Controller"},
        "profiles": {
            "off": {"available": True, "priority": 0},
            HP_PROFILE: {"available": hp_avail != "not available", "priority": 10300},
            SPK_PROFILE: {"available": True, "priority": 10200},
            "pro-audio": {"available": True, "priority": 1},
        },
        "ports": {
            "[Out] HDMI1": port("HDMI / DisplayPort 1 Output", "HDMI", "not available", BOTH, "HDMI/DP,pcm=3"),
            "[Out] Speaker": port("Speaker", "Speaker", "availability unknown", [SPK_PROFILE]),
            "[In] Mic2": port("Stereo Microphone", "Mic", "not available", BOTH, "Mic"),
            "[In] Mic1": port("Digital Microphone", "Mic", "availability unknown", BOTH),
            "[Out] Headphones": port("Headphones", "Headphones", hp_avail, [HP_PROFILE], "Headphone"),
        },
    }


def sink_for(port_name, avail="availability unknown"):
    return {
        "name": f"alsa_output.pci-0000_00_1f.3-platform-skl_hda_dsp_generic.HiFi__{port_name}__sink",
        "properties": {"api.alsa.card.name": "sof-hda-dsp", "device.profile.name": f"HiFi: {port_name}: sink", "device.class": "sound"},
        "ports": [{"name": f"[Out] {port_name}", "type": port_name, "availability": avail, "availability_group": ""}],
        "active_port": f"[Out] {port_name}",
    }


SPATIAL = "caelestia_spatial_audio"


class FakeSystem(H.System):
    def __init__(self, card, spatial_active=False, spatial_follows=True, profile_works=True, spatial_installed=True):
        self.card = card
        self.default_sink = SPATIAL if spatial_active else sink_for("Speaker")["name"]
        self.default_source = "alsa_input.x.HiFi__Mic1__source"
        self.spatial_state = {"active": spatial_active, "physical": sink_for("Speaker")["name"] if spatial_active else None}
        self.spatial_follows = spatial_follows
        self.profile_works = profile_works
        self.spatial_installed = spatial_installed
        self.log = []

    def _sinks(self):
        out = [sink_for("HDMI1", "not available")]
        if "Speaker" in self.card["active_profile"]:
            out.append(sink_for("Speaker"))
        if "Headphones" in self.card["active_profile"] and self.profile_works:
            out.append(sink_for("Headphones", self.card["ports"]["[Out] Headphones"]["availability"]))
        return out

    def pactl_json(self, what):
        if what == "cards":
            return [copy.deepcopy(self.card)]
        if what == "sinks":
            return self._sinks()
        if what == "sources":
            return [{"name": "x.monitor", "properties": {"device.class": "monitor"}}]
        return []

    def default(self, kind):
        return self.default_sink if kind == "sink" else self.default_source

    def set_default(self, kind, name):
        self.log.append(("default", kind, name))
        if kind == "sink":
            self.default_sink = name
        else:
            self.default_source = name
        return True

    def set_profile(self, card, profile):
        self.log.append(("profile", profile))
        self.card["active_profile"] = profile
        return True

    def spatial_status(self):
        return dict(self.spatial_state)

    def has_spatial(self):
        return self.spatial_installed

    def spatial(self, *args):
        self.log.append(("spatial",) + args)
        if args[0] == "stop":
            self.spatial_state = {"active": False}
        elif args[0] == "configure" and json.loads(args[1]).get("enabled"):
            if self.spatial_follows:
                self.spatial_state = {"active": True, "physical": self.default_sink}
                self.default_sink = SPATIAL
            else:
                self.spatial_state = {"active": True, "physical": sink_for("HDMI1")["name"]}
                self.default_sink = SPATIAL
        return True

    def sleep(self, seconds):
        self.log.append(("sleep", seconds))


class ProfileChoice(unittest.TestCase):
    def test_active_profile_kept_when_port_already_in_it(self):
        self.assertEqual(H.choose_profile(mirai_card(), "[Out] Speaker"), SPK_PROFILE)

    def test_alternate_profile_for_headphones(self):
        card = mirai_card(hp_avail="available")
        self.assertEqual(H.choose_profile(card, "[Out] Headphones"), HP_PROFILE)

    def test_never_pro_audio_or_off_or_unavailable(self):
        card = mirai_card()  # headphone profile unavailable (jack empty)
        self.assertIsNone(H.choose_profile(card, "[Out] Headphones"))
        card["ports"]["[Out] Headphones"]["profiles"] = ["pro-audio", "off"]
        self.assertIsNone(H.choose_profile(card, "[Out] Headphones"))


class Snapshot(unittest.TestCase):
    def test_live_like_snapshot_has_no_dead_alternates(self):
        snap = H.snapshot(FakeSystem(mirai_card(), spatial_active=True))
        self.assertEqual(snap["alternates"], [])
        self.assertEqual(snap["nodes"][sink_for("HDMI1")["name"]]["available"], "no")
        self.assertEqual(snap["nodes"][sink_for("Speaker")["name"]]["port"], "Speaker")
        self.assertTrue(snap["spatial"]["active"])
        self.assertNotIn("x.monitor", snap["nodes"])

    def test_plugged_headphones_become_alternate(self):
        snap = H.snapshot(FakeSystem(mirai_card(hp_avail="available")))
        self.assertEqual(len(snap["alternates"]), 1)
        alt = snap["alternates"][0]
        self.assertEqual((alt["kind"], alt["port"], alt["profile"], alt["cardName"]), ("sink", "Headphones", HP_PROFILE, "sof-hda-dsp"))

    def test_speaker_is_alternate_while_in_headphone_profile(self):
        snap = H.snapshot(FakeSystem(mirai_card(active=HP_PROFILE, hp_avail="available")))
        self.assertEqual([a["port"] for a in snap["alternates"]], ["Speaker"])
        self.assertEqual(snap["alternates"][0]["profile"], SPK_PROFILE)


class Select(unittest.TestCase):
    def test_explicit_speakers_switches_profile_and_sets_default(self):
        fake = FakeSystem(mirai_card(active=HP_PROFILE, hp_avail="available"))
        out = H.select(fake, {"kind": "sink", "card": CARD, "port": "Speaker"})
        self.assertTrue(out["ok"], out)
        self.assertTrue(out["profileChanged"])
        self.assertEqual(fake.card["active_profile"], SPK_PROFILE)
        self.assertEqual(fake.default_sink, sink_for("Speaker")["name"])

    def test_profile_rollback_when_port_never_appears(self):
        fake = FakeSystem(mirai_card(hp_avail="available"), profile_works=False)
        out = H.select(fake, {"kind": "sink", "card": CARD, "port": "Headphones"})
        self.assertFalse(out["ok"])
        self.assertTrue(out.get("rolledBack"))
        self.assertEqual(fake.card["active_profile"], SPK_PROFILE)
        self.assertEqual([e for e in fake.log if e[0] == "profile"], [("profile", HP_PROFILE), ("profile", SPK_PROFILE)])

    def test_unplugged_port_refused_without_touching_profile(self):
        fake = FakeSystem(mirai_card())
        out = H.select(fake, {"kind": "sink", "card": CARD, "port": "Headphones"})
        self.assertFalse(out["ok"])
        self.assertFalse([e for e in fake.log if e[0] == "profile"])

    def test_spatial_follows_new_output(self):
        fake = FakeSystem(mirai_card(active=HP_PROFILE, hp_avail="available"), spatial_active=True)
        fake.spatial_state["physical"] = sink_for("Headphones")["name"]
        out = H.select(fake, {"kind": "sink", "card": CARD, "port": "Speaker", "spatial": True})
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["route"], "spatial")
        self.assertEqual(fake.default_sink, SPATIAL)
        self.assertEqual(fake.spatial_state["physical"], sink_for("Speaker")["name"])
        kinds = [e[0] for e in fake.log if e[0] in ("spatial", "profile")]
        self.assertEqual(kinds[0], "spatial", "spatial stopped before its sink disappears")

    def test_spatial_noop_when_already_on_target(self):
        fake = FakeSystem(mirai_card(), spatial_active=True)
        out = H.select(fake, {"kind": "sink", "node": sink_for("Speaker")["name"], "spatial": True})
        self.assertTrue(out.get("noop"))
        self.assertEqual(fake.log, [])

    def test_spatial_failure_falls_back_to_direct(self):
        fake = FakeSystem(mirai_card(active=HP_PROFILE, hp_avail="available"), spatial_active=True, spatial_follows=False)
        out = H.select(fake, {"kind": "sink", "card": CARD, "port": "Speaker", "spatial": True})
        self.assertTrue(out["ok"])
        self.assertEqual(out["route"], "direct")
        self.assertIn("warning", out)
        self.assertEqual(fake.default_sink, sink_for("Speaker")["name"])

    def test_spatial_restarted_even_when_profile_switch_fails(self):
        fake = FakeSystem(mirai_card(hp_avail="available"), spatial_active=True, profile_works=False)
        out = H.select(fake, {"kind": "sink", "card": CARD, "port": "Headphones", "spatial": True})
        self.assertFalse(out["ok"])
        self.assertEqual(fake.log[-1][:2], ("spatial", "configure"))
        self.assertTrue(fake.spatial_state["active"])

    def test_spatial_request_ignored_when_spatial_not_default(self):
        fake = FakeSystem(mirai_card(), spatial_active=False)
        out = H.select(fake, {"kind": "sink", "node": "alsa_output.usb-dac", "spatial": True})
        self.assertTrue(out["ok"])
        self.assertEqual(out["route"], "direct")
        self.assertFalse([e for e in fake.log if e[0] == "spatial"])

    def test_sources_never_touch_spatial(self):
        fake = FakeSystem(mirai_card(), spatial_active=True)
        out = H.select(fake, {"kind": "source", "node": "alsa_input.x.HiFi__Mic2__source", "spatial": True})
        self.assertTrue(out["ok"])
        self.assertFalse([e for e in fake.log if e[0] == "spatial"])

    def test_bad_requests(self):
        fake = FakeSystem(mirai_card())
        self.assertFalse(H.select(fake, {"kind": "video"})["ok"])
        self.assertFalse(H.select(fake, {"kind": "sink", "node": ""})["ok"])
        self.assertFalse(H.select(fake, {"kind": "sink", "card": "nope", "port": "Speaker"})["ok"])


if __name__ == "__main__":
    unittest.main()
