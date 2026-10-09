.pragma library

// Pure presentation model for Caelestia's audio device selectors.
//
// Nothing in here touches PipeWire. Callers hand in plain node records
// ({ name, description, nick, mediaClass, props, ref }) plus an optional
// helper snapshot (port availability, card profiles, Spatial Audio state) and
// the user's persisted preferences. The result is the list each selector shows.
// Keeping it pure lets tests/test_model.mjs exercise it under node.

var SPATIAL_PREFIX = "caelestia_spatial_audio";

function str(value) {
    return value === undefined || value === null ? "" : String(value);
}

function parseJsonObject(text) {
    try {
        var parsed = JSON.parse(str(text) || "{}");
        return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
    } catch (e) {
        return {};
    }
}

function prefsFromSettings(settings) {
    return {
        aliases: parseJsonObject(settings && settings.aliasesJson),
        hidden: parseJsonObject(settings && settings.hiddenJson),
        groups: parseJsonObject(settings && settings.groupsJson),
        preferred: parseJsonObject(settings && settings.groupPreferredJson)
    };
}

function kindOf(mediaClass) {
    var mc = str(mediaClass);
    if (mc.indexOf("Audio/Sink") === 0 || mc === "Audio/Duplex")
        return "sink";
    if (mc.indexOf("Audio/Source") === 0)
        return "source";
    return "";
}

// "HiFi: Speaker: sink" -> "Speaker" (ALSA UCM). Empty for ACP profiles.
function ucmPort(props) {
    var parts = str(props["device.profile.name"]).split(":");
    if (parts.length === 3)
        return parts[1].trim();
    return "";
}

function alsaCard(props) {
    return str(props["api.alsa.card.name"] || props["alsa.card_name"] || props["alsa.id"]);
}

function bluezAddress(props, name) {
    var addr = str(props["api.bluez5.address"] || props["device.string"]);
    if (/^([0-9A-Fa-f]{2}[:_]){5}[0-9A-Fa-f]{2}$/.test(addr))
        return addr.replace(/_/g, ":").toUpperCase();
    var m = /^bluez_(?:output|input|sink|source)\.([0-9A-Fa-f_:]{17})/.exec(str(name));
    return m ? m[1].replace(/_/g, ":").toUpperCase() : "";
}

function isBluetooth(props, name) {
    return str(props["device.api"]) === "bluez5" || str(props["device.bus"]) === "bluetooth" || /^bluez_/.test(str(name));
}

// Stable identity used for every persisted preference. Never a numeric id.
function stableKey(node, kind) {
    var props = node.props || {};
    if (isBluetooth(props, node.name)) {
        var addr = bluezAddress(props, node.name);
        if (addr)
            return "bluez:" + addr + ":" + kind;
    }
    var port = ucmPort(props);
    var card = alsaCard(props);
    if (str(props["device.api"]) === "alsa" && port && card)
        return "alsa:" + card + ":" + kind + ":" + port;
    return str(node.name);
}

function portKey(card, kind, port) {
    return "alsa:" + card + ":" + kind + ":" + port;
}

function isSpatial(name) {
    return str(name).indexOf(SPATIAL_PREFIX) === 0;
}

function stripVendor(description, props) {
    var desc = str(description);
    var card = str(props["device.product.name"] || props["device.description"]);
    if (card && desc.indexOf(card + " ") === 0 && desc.length > card.length + 1)
        return desc.slice(card.length + 1);
    // ALSA nodes sometimes only carry the card name on the device, not the node.
    var known = /^(?:[A-Za-z0-9 -]+ (?:HD Audio Controller|High Definition Audio Controller|Audio Controller))\s+(.+)$/.exec(desc);
    return known ? known[1] : desc;
}

function availabilityOf(info) {
    var a = str(info && info.available).toLowerCase();
    if (a === "yes" || a === "no")
        return a;
    return "unknown";
}

// Category, friendly default label, icon and whether it is hidden by default.
function classify(node, kind, info) {
    var props = node.props || {};
    var name = str(node.name);
    var desc = str(node.description || props["node.description"]);
    var nick = str(node.nick || props["node.nick"]);
    var port = ucmPort(props) || str(info && info.port);
    var portType = str(info && info.portType).toLowerCase();
    var hay = (port + " " + portType + " " + nick + " " + desc + " " + str(props["device.profile.description"]) + " " + str(props["device.icon_name"])).toLowerCase();
    var available = availabilityOf(info);
    var jackDetected = !!(info && info.availabilityGroup);
    var out = {
        category: "other",
        label: stripVendor(desc || nick || name, props) || name,
        icon: kind === "sink" ? "speaker" : "mic",
        autoHidden: false,
        hiddenReason: "",
        available: available
    };

    if (isSpatial(name)) {
        var mode = /\((Pan|HRTF)\)/.exec(desc);
        out.category = "spatial";
        out.label = "Spatial Audio" + (mode ? " (" + mode[1] + ")" : "");
        out.icon = "surround_sound";
        return out;
    }

    if (isBluetooth(props, name)) {
        var alias = str(props["device.alias"] || props["api.bluez5.alias"] || desc || nick);
        out.category = "bluetooth";
        out.label = kind === "source" ? alias + " microphone" : alias;
        out.icon = kind === "source" ? "mic" : (/head|ear|bud/.test((alias + " " + str(props["device.form_factor"])).toLowerCase()) ? "headphones" : "bluetooth");
        if (kind === "source" && /microphone$/i.test(alias))
            out.label = alias;
        return out;
    }

    var virtualNode = props["node.virtual"] === true || str(props["node.virtual"]) === "true" || !!props["node.link-group"] || !props["device.api"] && !props["device.id"];
    if (virtualNode) {
        out.category = "virtual";
        out.icon = kind === "sink" ? "graphic_eq" : "settings_voice";
        out.autoHidden = true;
        out.hiddenReason = "System or virtual route";
        return out;
    }

    if (/hdmi|displayport/.test(hay) || portType === "hdmi" || str(props["device.icon_name"]) === "video-display") {
        var n = /(?:hdmi|displayport)\s*(\d+)/i.exec(port + " " + desc) || /(\d+)\s*$/.exec(port);
        out.category = "hdmi";
        out.label = "External display" + (n ? " " + n[1] : "") + " (HDMI/DP)";
        out.icon = "tv";
        if (available !== "yes") {
            out.autoHidden = true;
            out.hiddenReason = available === "no" ? "Display not connected" : "Display connection unknown";
        }
        return out;
    }

    if (kind === "sink" && /headphone|headset/.test(hay)) {
        out.category = "headphones";
        out.label = str(props["device.bus"]) === "usb" ? stripVendor(desc, props) : "Headphones (3.5 mm)";
        out.icon = "headphones";
    } else if (kind === "sink" && /speaker/.test(hay)) {
        out.category = "speakers";
        out.label = str(props["device.bus"]) === "usb" ? stripVendor(desc, props) : "Laptop speakers";
        out.icon = "laptop_chromebook";
    } else if (kind === "sink" && /line ?out|spdif|iec958|digital/.test(hay)) {
        out.category = "line";
        out.icon = "settings_input_component";
    } else if (kind === "source" && (/headset|headphone/.test(hay) || (/mic/.test(hay) && jackDetected && !/digital|internal|dmic/.test(hay)))) {
        out.category = "headset-mic";
        out.label = "Headset microphone (3.5 mm)";
        out.icon = "headset_mic";
    } else if (kind === "source" && /digital mic|dmic|internal|built-in/.test(hay)) {
        out.category = "builtin-mic";
        out.label = "Built-in microphone";
        out.icon = "mic";
    } else if (kind === "source" && /line ?in/.test(hay)) {
        out.category = "line";
        out.icon = "settings_input_component";
    } else if (str(props["device.bus"]) === "usb") {
        out.category = "usb";
        out.icon = kind === "sink" ? "speaker" : "mic";
    }

    // Jack-detected endpoints that report "not available" are unplugged.
    if (available === "no") {
        out.autoHidden = true;
        out.hiddenReason = "Not plugged in";
    }
    return out;
}

// All classified records for one direction, ungrouped and including hidden.
function records(input) {
    var kind = input.kind;
    var prefs = input.prefs || prefsFromSettings(null);
    var snap = input.snapshot || {};
    var snapNodes = snap.nodes || {};
    var autoDefaults = !input.options || input.options.autoDefaults !== false;
    var defaultName = str(input.defaultName);
    var spatial = snap.spatial || {};
    var result = [];
    var seen = {};

    var nodes = input.nodes || [];
    for (var i = 0; i < nodes.length; i++) {
        var node = nodes[i];
        if (!node || !node.name)
            continue;
        var nk = kindOf(node.mediaClass || (node.props && node.props["media.class"])) || kind;
        if (nk !== kind)
            continue; // never conflate input with output
        if (seen[node.name])
            continue; // PipeWire briefly reports duplicates during profile changes
        seen[node.name] = true;

        var info = snapNodes[node.name] || null;
        var c = classify(node, kind, info);
        var key = stableKey(node, kind);
        var userHidden = Object.prototype.hasOwnProperty.call(prefs.hidden, key) ? !!prefs.hidden[key] : null;
        var autoHidden = autoDefaults && c.autoHidden;
        var alias = str(prefs.aliases[key]).trim();
        var isDefault = node.name === defaultName;
        var routed = kind === "sink" && !!spatial.active && isSpatial(defaultName) && str(spatial.physical) === node.name;

        result.push({
            key: key,
            kind: kind,
            nodeName: str(node.name),
            ref: node.ref === undefined ? null : node.ref,
            rawLabel: str(node.description || node.nick || node.name),
            autoLabel: c.label,
            label: alias || (autoDefaults ? c.label : str(node.description || node.nick || node.name)),
            aliased: !!alias,
            icon: c.icon,
            category: c.category,
            available: c.available,
            isDefault: isDefault,
            routed: routed,
            userHidden: userHidden,
            autoHidden: autoHidden,
            hidden: userHidden === null ? autoHidden : userHidden,
            hiddenReason: userHidden === true ? "Hidden by you" : (userHidden === null && autoHidden ? c.hiddenReason : ""),
            group: str(prefs.groups[key]).trim(),
            action: "node",
            port: null
        });
    }

    // Ports reachable only by switching the card profile (Speakers <-> Headphones).
    var alts = snap.alternates || [];
    for (var j = 0; j < alts.length; j++) {
        var alt = alts[j];
        if (!alt || alt.kind !== kind)
            continue;
        var akey = portKey(alt.cardName, kind, alt.port);
        var exists = false;
        for (var r = 0; r < result.length; r++) {
            if (result[r].key === akey) {
                exists = true;
                break;
            }
        }
        if (exists)
            continue;
        var fake = {
            name: "",
            description: str(alt.description),
            nick: str(alt.description),
            props: {
                "device.api": "alsa",
                "device.profile.name": "HiFi: " + alt.port + ": " + kind,
                "device.icon_name": ""
            }
        };
        var ac = classify(fake, kind, { available: alt.available, portType: alt.type, availabilityGroup: alt.availabilityGroup, port: alt.port });
        var aUserHidden = Object.prototype.hasOwnProperty.call(prefs.hidden, akey) ? !!prefs.hidden[akey] : null;
        var aAuto = autoDefaults && ac.autoHidden;
        var aAlias = str(prefs.aliases[akey]).trim();
        result.push({
            key: akey,
            kind: kind,
            nodeName: "",
            ref: null,
            rawLabel: str(alt.description),
            autoLabel: ac.label,
            label: aAlias || (autoDefaults ? ac.label : str(alt.description)),
            aliased: !!aAlias,
            icon: ac.icon,
            category: ac.category,
            available: ac.available,
            isDefault: false,
            routed: false,
            userHidden: aUserHidden,
            autoHidden: aAuto,
            hidden: aUserHidden === null ? aAuto : aUserHidden,
            hiddenReason: aUserHidden === true ? "Hidden by you" : (aUserHidden === null && aAuto ? ac.hiddenReason : ""),
            group: str(prefs.groups[akey]).trim(),
            action: "port",
            port: { card: str(alt.card), cardName: str(alt.cardName), port: str(alt.port), profile: str(alt.profile) }
        });
    }
    return result;
}

function rank(rec) {
    if (rec.category === "spatial")
        return 0;
    var order = ["speakers", "headphones", "builtin-mic", "headset-mic", "bluetooth", "usb", "line", "hdmi", "other", "virtual"];
    var i = order.indexOf(rec.category);
    return 1 + (i < 0 ? order.length : i);
}

function compare(a, b) {
    var d = rank(a) - rank(b);
    if (d !== 0)
        return d;
    return a.label.localeCompare(b.label);
}

// Picks the real member a group row stands for.
function resolveGroupMember(members, preferredKey) {
    var live = members.filter(function (m) { return m.action === "node" && m.nodeName; });
    var pick = live.filter(function (m) { return m.isDefault; })[0] || live.filter(function (m) { return m.routed; })[0];
    if (pick)
        return pick;
    if (preferredKey) {
        pick = members.filter(function (m) { return m.key === preferredKey && m.available !== "no"; })[0];
        if (pick)
            return pick;
    }
    pick = live.filter(function (m) { return m.available === "yes"; })[0] || live.filter(function (m) { return m.available !== "no"; })[0] || live[0];
    return pick || members.filter(function (m) { return m.available !== "no"; })[0] || members[0] || null;
}

// The list a selector shows. Hidden entries only appear when revealed, but the
// active default (or the physical device behind Spatial Audio) always does.
function buildEntries(input) {
    var kind = input.kind;
    var reveal = !!(input.options && input.options.reveal);
    var prefs = input.prefs || prefsFromSettings(null);
    var all = records(input);
    var entries = [];
    var hiddenCount = 0;
    var groups = {};
    var groupOrder = [];

    for (var i = 0; i < all.length; i++) {
        var rec = all[i];
        var mustShow = rec.isDefault || rec.routed || (rec.category === "spatial" && !!(input.snapshot && input.snapshot.spatial && input.snapshot.spatial.active));
        if (rec.hidden && !mustShow) {
            hiddenCount++;
            if (!reveal)
                continue;
        }
        if (rec.group && !reveal) {
            var gid = kind + ":" + rec.group;
            if (!groups[gid]) {
                groups[gid] = [];
                groupOrder.push(gid);
            }
            groups[gid].push(rec);
            continue;
        }
        entries.push(entryFrom(rec, reveal && rec.hidden && !mustShow));
    }

    for (var g = 0; g < groupOrder.length; g++) {
        var id = groupOrder[g];
        var members = groups[id];
        if (members.length === 1) {
            entries.push(entryFrom(members[0], false));
            continue;
        }
        var target = resolveGroupMember(members, str(prefs.preferred[id]));
        if (!target)
            continue;
        var e = entryFrom(target, false);
        e.key = "group:" + id;
        e.label = members[0].group;
        e.isGroup = true;
        e.groupId = id;
        e.members = members.map(function (m) { return { key: m.key, label: m.label, nodeName: m.nodeName, available: m.available, isDefault: m.isDefault }; });
        e.isDefault = members.some(function (m) { return m.isDefault; });
        e.routed = members.some(function (m) { return m.routed; });
        e.memberKey = target.key;
        e.sublabel = target.label + " · " + members.length + " devices";
        entries.push(e);
    }

    entries.sort(compare);
    return { entries: entries, hiddenCount: hiddenCount, records: all };
}

function entryFrom(rec, revealedHidden) {
    var sub = "";
    if (rec.routed)
        sub = "Playing through Spatial Audio";
    else if (rec.action === "port")
        sub = "Switches the sound card profile";
    else if (revealedHidden)
        sub = rec.hiddenReason || "Hidden";
    else if (rec.category === "bluetooth")
        sub = "Bluetooth";
    return {
        key: rec.key,
        kind: rec.kind,
        label: rec.label,
        sublabel: sub,
        icon: rec.icon,
        category: rec.category,
        nodeName: rec.nodeName,
        ref: rec.ref,
        isDefault: rec.isDefault,
        routed: rec.routed,
        hidden: !!revealedHidden,
        available: rec.available,
        action: rec.action,
        port: rec.port,
        isGroup: false,
        groupId: "",
        memberKey: rec.key,
        members: []
    };
}

// Turns a click into a concrete plan. The caller executes it.
//   { type: "default", nodeName }            set default directly
//   { type: "noop", reason }                  already where the user wants it
//   { type: "helper", request }               profile switch and/or Spatial reroute
//   { type: "error", reason }
function planSelection(entry, state) {
    if (!entry)
        return { type: "error", reason: "Nothing selected" };
    var spatial = (state && state.spatial) || {};
    var defaultName = str(state && state.defaultName);
    var throughSpatial = !!(state && state.routeThroughSpatial) && entry.kind === "sink" && !!spatial.active && isSpatial(defaultName) && entry.category !== "spatial";

    if (entry.action === "port") {
        if (!entry.port || !entry.port.card || !entry.port.port)
            return { type: "error", reason: "Profile information unavailable" };
        return {
            type: "helper",
            request: { kind: entry.kind, card: entry.port.card, port: entry.port.port, spatial: throughSpatial }
        };
    }
    if (!entry.nodeName)
        return { type: "error", reason: "Device is no longer present" };
    if (entry.isDefault)
        return { type: "noop", reason: "Already the default" };
    if (throughSpatial) {
        if (str(spatial.physical) === entry.nodeName)
            return { type: "noop", reason: "Already playing through Spatial Audio" };
        return { type: "helper", request: { kind: "sink", node: entry.nodeName, spatial: true } };
    }
    return { type: "default", nodeName: entry.nodeName };
}

// One display name for a node (toasts etc.). Falls back to the raw description.
function displayName(node, kind, prefs, snapshot, autoDefaults) {
    if (!node || !node.name)
        return "";
    var out = records({ kind: kind, nodes: [node], prefs: prefs, snapshot: snapshot, options: { autoDefaults: autoDefaults } });
    return out.length ? out[0].label : str(node.description || node.name);
}

function setInMap(text, key, value) {
    var map = parseJsonObject(text);
    if (value === undefined || value === null || value === "")
        delete map[key];
    else
        map[key] = value;
    return JSON.stringify(map);
}

if (typeof module !== "undefined" && module.exports) {
    module.exports = {
        prefsFromSettings: prefsFromSettings,
        parseJsonObject: parseJsonObject,
        stableKey: stableKey,
        classify: classify,
        records: records,
        buildEntries: buildEntries,
        resolveGroupMember: resolveGroupMember,
        planSelection: planSelection,
        displayName: displayName,
        setInMap: setInMap,
        kindOf: kindOf
    };
}
