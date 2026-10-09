// node --test tests/test_model.mjs
// Loads lib/AudioModel.js (a QML ".pragma library" file) without QML.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const src = readFileSync(fileURLToPath(new URL("../lib/AudioModel.js", import.meta.url)), "utf8").replace(/^\.pragma library\s*$/m, "");
const sandbox = { module: { exports: {} } };
vm.runInNewContext(src, sandbox);
const M = sandbox.module.exports;
// Objects from the vm realm have foreign prototypes; compare as plain JSON.
const deq = (actual, expected) => assert.deepStrictEqual(JSON.parse(JSON.stringify(actual)), expected);

const CARD = "sof-hda-dsp";
const BUS = "alsa_output.pci-0000_00_1f.3-platform-skl_hda_dsp_generic";
const IN = "alsa_input.pci-0000_00_1f.3-platform-skl_hda_dsp_generic";

function alsa(kind, port, desc, extra = {}) {
    const name = `${kind === "sink" ? BUS : IN}.HiFi__${port}__${kind}`;
    return {
        name,
        description: `Meteor Lake-P HD Audio Controller ${desc}`,
        nick: desc,
        mediaClass: kind === "sink" ? "Audio/Sink" : "Audio/Source",
        props: {
            "device.api": "alsa", "device.bus": "pci", "device.id": 45,
            "api.alsa.card.name": CARD, "device.profile.name": `HiFi: ${port}: ${kind}`,
            "device.profile.description": desc,
            "device.icon_name": port.startsWith("HDMI") ? "video-display" : (kind === "sink" ? "audio-speakers" : "audio-input-microphone"),
            ...extra
        },
        ref: { id: name }
    };
}

const speaker = alsa("sink", "Speaker", "Speaker");
const hdmi = [1, 2, 3].map(n => alsa("sink", `HDMI${n}`, `HDMI / DisplayPort ${n} Output`));
const mic1 = alsa("source", "Mic1", "Digital Microphone");
const mic2 = alsa("source", "Mic2", "Stereo Microphone");
const spatial = {
    name: "caelestia_spatial_audio", description: "Caelestia Spatial Audio (Pan)", mediaClass: "Audio/Sink",
    props: { "node.virtual": true, "node.link-group": "filter-chain-1741-22" }, ref: { id: "sp" }
};
const easyeffects = {
    name: "easyeffects_sink", description: "Easy Effects Sink", mediaClass: "Audio/Sink",
    props: { "node.virtual": true }, ref: {}
};
const bt = {
    name: "bluez_output.AC_80_0A_11_22_33.1", description: "WH-1000XM4", mediaClass: "Audio/Sink",
    props: { "device.api": "bluez5", "device.bus": "bluetooth", "api.bluez5.address": "AC:80:0A:11:22:33", "device.form_factor": "headphone" },
    ref: {}
};
const btMic = {
    name: "bluez_input.AC:80:0A:11:22:33.0", description: "WH-1000XM4", mediaClass: "Audio/Source",
    props: { "device.api": "bluez5", "api.bluez5.address": "AC:80:0A:11:22:33" }, ref: {}
};

function liveSnapshot(over = {}) {
    const nodes = {};
    nodes[speaker.name] = { available: "unknown", port: "Speaker", portType: "Speaker", availabilityGroup: "" };
    hdmi.forEach((h, i) => nodes[h.name] = { available: "no", port: `HDMI${i + 1}`, portType: "HDMI", availabilityGroup: `HDMI/DP,pcm=${5 - i}` });
    nodes[mic1.name] = { available: "unknown", port: "Mic1", portType: "Mic", availabilityGroup: "" };
    nodes[mic2.name] = { available: "no", port: "Mic2", portType: "Mic", availabilityGroup: "Mic" };
    return {
        nodes,
        alternates: [],
        spatial: { installed: true, active: true, physical: speaker.name, mode: "Pan" },
        ...over
    };
}

const noPrefs = M.prefsFromSettings(null);
const sinks = [speaker, ...hdmi, spatial];

function build(kind, nodes, opts = {}) {
    return M.buildEntries({
        kind, nodes, defaultName: opts.defaultName ?? (kind === "sink" ? spatial.name : mic1.name),
        prefs: opts.prefs ?? noPrefs, snapshot: opts.snapshot ?? liveSnapshot(), options: { reveal: !!opts.reveal, autoDefaults: opts.autoDefaults }
    });
}

test("live Mirai outputs: friendly names, disconnected HDMI hidden, spatial kept", () => {
    const v = build("sink", sinks);
    const labels = v.entries.map(e => e.label);
    deq(labels, ["Spatial Audio (Pan)", "Laptop speakers"]);
    assert.equal(v.hiddenCount, 3);
    const sp = v.entries[0];
    assert.equal(sp.isDefault, true);
    assert.equal(v.entries[1].routed, true);
    assert.match(v.entries[1].sublabel, /Spatial Audio/);
});

test("reveal shows hidden displays marked hidden, still never mixes inputs", () => {
    const v = build("sink", [...sinks, mic1], { reveal: true });
    assert.equal(v.entries.length, 5);
    const disp = v.entries.filter(e => e.category === "hdmi");
    assert.equal(disp.length, 3);
    assert.ok(disp.every(e => e.hidden && /not connected/.test(e.sublabel)));
    assert.ok(disp.map(e => e.label).includes("External display 2 (HDMI/DP)"));
    assert.ok(!v.entries.some(e => e.nodeName === mic1.name));
});

test("connected HDMI is shown", () => {
    const snap = liveSnapshot();
    snap.nodes[hdmi[0].name].available = "yes";
    const v = build("sink", sinks, { snapshot: snap });
    assert.ok(v.entries.some(e => e.label === "External display 1 (HDMI/DP)" && !e.hidden));
});

test("inputs: built-in mic named, unplugged headset mic hidden, then discovered when plugged", () => {
    let v = build("source", [mic1, mic2]);
    deq(v.entries.map(e => e.label), ["Built-in microphone"]);
    const snap = liveSnapshot();
    snap.nodes[mic2.name].available = "yes";
    v = build("source", [mic1, mic2], { snapshot: snap });
    deq(v.entries.map(e => e.label), ["Built-in microphone", "Headset microphone (3.5 mm)"]);
});

test("stable keys use port / bluetooth address, never numeric ids", () => {
    assert.equal(M.stableKey(speaker, "sink"), "alsa:sof-hda-dsp:sink:Speaker");
    assert.equal(M.stableKey(bt, "sink"), "bluez:AC:80:0A:11:22:33:sink");
    assert.equal(M.stableKey(btMic, "source"), "bluez:AC:80:0A:11:22:33:source");
    assert.equal(M.stableKey(easyeffects, "sink"), "easyeffects_sink");
});

test("rename and hide persist by stable key and round-trip through JSON", () => {
    let settings = { aliasesJson: "{}", hiddenJson: "{}", groupsJson: "{}", groupPreferredJson: "{}" };
    settings.aliasesJson = M.setInMap(settings.aliasesJson, "alsa:sof-hda-dsp:sink:Speaker", "Desk speakers");
    settings.hiddenJson = M.setInMap(settings.hiddenJson, "alsa:sof-hda-dsp:sink:HDMI2", false);
    const prefs = M.prefsFromSettings(JSON.parse(JSON.stringify(settings)));
    const v = build("sink", sinks, { prefs });
    assert.ok(v.entries.some(e => e.label === "Desk speakers"));
    assert.ok(v.entries.some(e => e.label === "External display 2 (HDMI/DP)" && !e.hidden), "user un-hide beats auto hide");
    assert.equal(v.hiddenCount, 2);
    settings.aliasesJson = M.setInMap(settings.aliasesJson, "alsa:sof-hda-dsp:sink:Speaker", "");
    assert.equal(settings.aliasesJson, "{}");
});

test("corrupt settings JSON degrades to defaults", () => {
    const prefs = M.prefsFromSettings({ aliasesJson: "{oops", hiddenJson: "[]", groupsJson: null });
    deq(prefs.aliases, {});
    deq(prefs.hidden, {});
    assert.equal(build("sink", sinks, { prefs }).entries.length, 2);
});

test("hidden but active output stays reachable", () => {
    const prefs = M.prefsFromSettings({ hiddenJson: JSON.stringify({ "alsa:sof-hda-dsp:sink:Speaker": true, "caelestia_spatial_audio": true }) });
    const v = build("sink", sinks, { prefs, defaultName: speaker.name, snapshot: liveSnapshot({ spatial: { active: false } }) });
    assert.ok(v.entries.some(e => e.nodeName === speaker.name && e.isDefault));
    // Spatial is hidden by the user and not active -> gone
    assert.ok(!v.entries.some(e => e.category === "spatial"));
});

test("active spatial sink cannot be hidden, inactive virtual routes are hidden", () => {
    const prefs = M.prefsFromSettings({ hiddenJson: JSON.stringify({ "caelestia_spatial_audio": true }) });
    const v = build("sink", [...sinks, easyeffects], { prefs });
    assert.ok(v.entries.some(e => e.category === "spatial"));
    assert.ok(!v.entries.some(e => e.nodeName === "easyeffects_sink"));
});

test("bluetooth appears with its alias when connected", () => {
    const v = build("sink", [...sinks, bt]);
    const e = v.entries.find(x => x.category === "bluetooth");
    assert.equal(e.label, "WH-1000XM4");
    assert.equal(e.icon, "headphones");
    assert.equal(e.sublabel, "Bluetooth");
    const vi = build("source", [mic1, btMic]);
    assert.ok(vi.entries.some(x => x.label === "WH-1000XM4 microphone"));
});

test("duplicate nodes and missing names are tolerated", () => {
    const v = build("sink", [speaker, speaker, { name: "", mediaClass: "Audio/Sink" }, null, spatial]);
    assert.equal(v.entries.length, 2);
});

test("groups: same-kind only, resolve to a real member, prefer active/preferred", () => {
    const usbA = { name: "alsa_output.usb-Foo.analog-stereo", description: "Foo USB Analog Stereo", mediaClass: "Audio/Sink", props: { "device.api": "alsa", "device.bus": "usb", "device.id": 70 }, ref: {} };
    const usbB = { name: "alsa_output.usb-Foo.iec958-stereo", description: "Foo USB Digital Stereo", mediaClass: "Audio/Sink", props: { "device.api": "alsa", "device.bus": "usb", "device.id": 70 }, ref: {} };
    const usbMic = { name: "alsa_input.usb-Foo.mono", description: "Foo USB Mic", mediaClass: "Audio/Source", props: { "device.api": "alsa", "device.bus": "usb" }, ref: {} };
    const groups = { [usbA.name]: "Foo DAC", [usbB.name]: "Foo DAC", [usbMic.name]: "Foo DAC" };
    let prefs = M.prefsFromSettings({ groupsJson: JSON.stringify(groups) });
    let v = build("sink", [...sinks, usbA, usbB], { prefs });
    const g = v.entries.filter(e => e.isGroup);
    assert.equal(g.length, 1);
    assert.equal(g[0].label, "Foo DAC");
    assert.equal(g[0].members.length, 2);
    assert.ok([usbA.name, usbB.name].includes(g[0].nodeName), "group selects a real member");

    prefs = M.prefsFromSettings({ groupsJson: JSON.stringify(groups), groupPreferredJson: JSON.stringify({ "sink:Foo DAC": usbB.name }) });
    v = build("sink", [...sinks, usbA, usbB], { prefs });
    assert.equal(v.entries.find(e => e.isGroup).nodeName, usbB.name);

    v = build("sink", [...sinks, usbA, usbB], { prefs, defaultName: usbA.name, snapshot: liveSnapshot({ spatial: { active: false } }) });
    const active = v.entries.find(e => e.isGroup);
    assert.equal(active.nodeName, usbA.name);
    assert.equal(active.isDefault, true);

    // the mic with the same group name stays an input-only single row
    const vi = build("source", [mic1, usbMic], { prefs });
    assert.ok(vi.entries.some(e => e.nodeName === usbMic.name && !e.isGroup));

    // reveal ungroups so each real member is directly selectable
    v = build("sink", [...sinks, usbA, usbB], { prefs, reveal: true });
    assert.ok(v.entries.some(e => e.nodeName === usbA.name) && v.entries.some(e => e.nodeName === usbB.name));
});

test("resolveGroupMember skips unplugged members and never invents one", () => {
    const m = [
        { key: "a", action: "node", nodeName: "a", available: "no" },
        { key: "b", action: "node", nodeName: "b", available: "unknown" }
    ];
    assert.equal(M.resolveGroupMember(m, "a").key, "b");
    assert.equal(M.resolveGroupMember([], ""), null);
});

test("profile alternate: headphones offered when plugged but inactive, keyed like the real port", () => {
    const snap = liveSnapshot({
        alternates: [{ kind: "sink", card: "alsa_card.pci-x", cardName: CARD, port: "Headphones", description: "Headphones", type: "Headphones", available: "yes", availabilityGroup: "Headphone", profile: "HiFi (HDMI1, HDMI2, HDMI3, Headphones, Mic1, Mic2)" }]
    });
    const prefs = M.prefsFromSettings({ aliasesJson: JSON.stringify({ "alsa:sof-hda-dsp:sink:Headphones": "Studio cans" }) });
    const v = build("sink", sinks, { snapshot: snap, prefs });
    const hp = v.entries.find(e => e.action === "port");
    assert.equal(hp.label, "Studio cans");
    assert.equal(hp.key, "alsa:sof-hda-dsp:sink:Headphones");
    assert.match(hp.sublabel, /profile/);
    // once the headphones node is real, the same alias applies to it
    const hpNode = alsa("sink", "Headphones", "Headphones");
    const v2 = build("sink", [hpNode, ...hdmi, spatial], { prefs, snapshot: liveSnapshot({ spatial: { active: false } }), defaultName: hpNode.name });
    assert.ok(v2.entries.some(e => e.label === "Studio cans" && e.action === "node"));
});

test("planSelection: direct, noop, spatial reroute, profile switch, missing node", () => {
    const view = build("sink", sinks);
    const lap = view.entries.find(e => e.category === "speakers");
    const spatialState = { spatial: { active: true, physical: speaker.name }, defaultName: spatial.name, routeThroughSpatial: true };
    assert.equal(M.planSelection(lap, spatialState).type, "noop");
    assert.equal(M.planSelection(view.entries[0], spatialState).type, "noop");

    const hp = { kind: "sink", category: "headphones", action: "node", nodeName: "hp", isDefault: false };
    deq(M.planSelection(hp, spatialState), { type: "helper", request: { kind: "sink", node: "hp", spatial: true } });
    deq(M.planSelection(hp, { ...spatialState, routeThroughSpatial: false }), { type: "default", nodeName: "hp" });
    assert.equal(M.planSelection(hp, { spatial: { active: false }, defaultName: speaker.name, routeThroughSpatial: true }).type, "default");

    const port = { kind: "sink", category: "headphones", action: "port", port: { card: "alsa_card.x", port: "Headphones" } };
    const p = M.planSelection(port, spatialState);
    assert.equal(p.type, "helper");
    assert.equal(p.request.port, "Headphones");
    assert.equal(p.request.spatial, true);

    assert.equal(M.planSelection({ kind: "sink", action: "node", nodeName: "" }, spatialState).type, "error");
    assert.equal(M.planSelection(null, spatialState).type, "error");
    // sources never go through spatial
    const src = { kind: "source", action: "node", nodeName: mic2.name, isDefault: false };
    assert.equal(M.planSelection(src, spatialState).type, "default");
});

test("autoDefaults off shows raw descriptions and does not auto-hide", () => {
    const v = build("sink", sinks, { autoDefaults: false });
    assert.equal(v.entries.length, 5);
    assert.ok(v.entries.some(e => e.label === "Meteor Lake-P HD Audio Controller Speaker"));
});

test("displayName for toasts", () => {
    assert.equal(M.displayName(speaker, "sink", noPrefs, liveSnapshot(), true), "Laptop speakers");
    assert.equal(M.displayName(null, "sink", noPrefs, {}, true), "");
});
