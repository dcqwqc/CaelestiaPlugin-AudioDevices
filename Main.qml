pragma ComponentBehavior: Bound

import QtQuick
import Quickshell.Io
import Caelestia
import qs.services
import "lib/AudioModel.js" as Model

// Provider for the shell's AudioPresentation hook. All policy lives here; the
// core shell only asks for entries and forwards clicks.
Item {
    id: root

    property var settings: null
    property int revision: 0
    property var snapshot: ({})
    property string snapshotKey: ""
    property bool busy: false
    property var lastResult: null
    property bool registered: false

    readonly property string helper: Qt.resolvedUrl("scripts/audio-devices-helper.py").toString().replace("file://", "")

    visible: false
    implicitWidth: 0
    implicitHeight: 0

    function bump(): void {
        revision++;
    }

    function prefs(): var {
        return Model.prefsFromSettings(settings);
    }

    function autoDefaults(): bool {
        return settings?.autoDefaults ?? true;
    }

    function nodeRecord(node): var {
        if (!node)
            return null;
        const props = node.properties ?? {};
        return {
            name: node.name ?? "",
            description: node.description ?? "",
            nick: node.nickname ?? "",
            mediaClass: props["media.class"] ?? "",
            props: props,
            ref: node
        };
    }

    function nodeRecords(kind): var {
        const list = kind === "sink" ? Audio.sinks : Audio.sources;
        const out = [];
        for (const node of list) {
            const rec = nodeRecord(node);
            if (rec?.name)
                out.push(rec);
        }
        return out;
    }

    // Called by AudioPresentation.view(); reads Audio.* so bindings follow PipeWire.
    function entries(kind, reveal): var {
        void revision;
        const current = kind === "sink" ? Audio.sink : Audio.source;
        return Model.buildEntries({
            kind: kind,
            nodes: nodeRecords(kind),
            defaultName: current?.name ?? "",
            prefs: prefs(),
            snapshot: snapshot,
            options: {
                autoDefaults: autoDefaults(),
                reveal: !!reveal
            }
        });
    }

    function records(kind): var {
        void revision;
        const current = kind === "sink" ? Audio.sink : Audio.source;
        return Model.records({
            kind: kind,
            nodes: nodeRecords(kind),
            defaultName: current?.name ?? "",
            prefs: prefs(),
            snapshot: snapshot,
            options: {
                autoDefaults: autoDefaults()
            }
        });
    }

    function displayName(node, kind): string {
        const rec = nodeRecord(node);
        if (!rec)
            return "";
        return Model.displayName(rec, kind, prefs(), snapshot, autoDefaults());
    }

    function findNode(kind, name): var {
        for (const node of (kind === "sink" ? Audio.sinks : Audio.sources))
            if (node?.name === name)
                return node;
        return null;
    }

    function select(entry): void {
        const plan = Model.planSelection(entry, {
            spatial: snapshot?.spatial ?? {},
            defaultName: (entry?.kind === "source" ? Audio.source : Audio.sink)?.name ?? "",
            routeThroughSpatial: settings?.routeThroughSpatial ?? true
        });

        if (plan.type === "default") {
            const node = entry.ref ?? findNode(entry.kind, plan.nodeName);
            if (!node) {
                fail(qsTr("%1 is no longer available").arg(entry.label));
                return;
            }
            if (entry.kind === "source")
                Audio.setAudioSource(node);
            else
                Audio.setAudioSink(node);
            lastResult = {
                ok: true,
                route: "direct",
                node: plan.nodeName
            };
        } else if (plan.type === "helper") {
            if (selectProc.running) {
                fail(qsTr("Still switching the previous device"));
                return;
            }
            busy = true;
            selectProc.label = entry.label;
            selectProc.command = [helper, "select", JSON.stringify(plan.request)];
            selectProc.running = true;
        } else if (plan.type === "error") {
            fail(plan.reason);
        }
    }

    // Used by the settings page to pin which member a group row selects.
    function setPreferredMember(groupId, key): void {
        if (settings)
            settings.groupPreferredJson = Model.setInMap(settings.groupPreferredJson, groupId, key);
    }

    function fail(message): void {
        lastResult = {
            ok: false,
            error: message
        };
        Toaster.toast(qsTr("Audio device"), message, "error");
    }

    function refresh(): void {
        if (snapshotProc.running)
            refreshTimer.restart();
        else
            snapshotProc.running = true;
    }

    function register(): void {
        try {
            AudioPresentation.register(root);
            registered = true;
        } catch (e) {
            // Core integration not installed: the settings page still works.
            registered = false;
        }
    }

    Component.onCompleted: {
        register();
        refresh();
    }

    Component.onDestruction: {
        try {
            AudioPresentation.unregister(root);
        } catch (e) {}
    }

    Connections {
        target: root.settings

        function onAliasesJsonChanged(): void {
            root.bump();
        }
        function onHiddenJsonChanged(): void {
            root.bump();
        }
        function onGroupsJsonChanged(): void {
            root.bump();
        }
        function onGroupPreferredJsonChanged(): void {
            root.bump();
        }
        function onAutoDefaultsChanged(): void {
            root.bump();
        }
    }

    Connections {
        target: Audio

        function onSinksChanged(): void {
            root.bump();
            refreshTimer.restart();
        }
        function onSourcesChanged(): void {
            root.bump();
            refreshTimer.restart();
        }
        function onSinkChanged(): void {
            root.bump();
            refreshTimer.restart();
        }
        function onSourceChanged(): void {
            root.bump();
            refreshTimer.restart();
        }
    }

    Timer {
        id: refreshTimer

        interval: 300
        onTriggered: root.refresh()
    }

    // Safety net for changes pactl subscribe cannot report.
    Timer {
        interval: 30000
        running: true
        repeat: true
        onTriggered: root.refresh()
    }

    Process {
        id: snapshotProc

        command: [root.helper, "snapshot"]
        stdout: StdioCollector {
            onStreamFinished: {
                try {
                    const data = JSON.parse(text);
                    if (!data?.ok)
                        return;
                    const key = JSON.stringify([data.nodes, data.alternates, data.spatial, data.cards]);
                    if (key !== root.snapshotKey) {
                        root.snapshotKey = key;
                        root.snapshot = data;
                        root.bump();
                    }
                } catch (e) {
                    console.warn("AudioDevices: bad snapshot", e);
                }
            }
        }
    }

    // Jack plug/unplug and profile changes arrive as card events.
    Process {
        id: subscribeProc

        running: true
        command: ["pactl", "subscribe"]
        stdout: SplitParser {
            onRead: line => {
                if (/on card|'(new|remove)' on (sink|source)|'change' on server/.test(line))
                    refreshTimer.restart();
            }
        }
        onExited: resubscribe.restart()
    }

    Timer {
        id: resubscribe

        interval: 3000
        onTriggered: subscribeProc.running = true
    }

    Process {
        id: selectProc

        property string label

        stdout: StdioCollector {
            onStreamFinished: {
                let result = null;
                try {
                    result = JSON.parse(text);
                } catch (e) {
                    result = {
                        ok: false,
                        error: qsTr("Helper returned no result")
                    };
                }
                root.busy = false;
                root.lastResult = result;
                if (!result.ok)
                    root.fail(result.error || qsTr("Could not switch to %1").arg(selectProc.label));
                else if (result.warning)
                    Toaster.toast(qsTr("Audio device"), result.warning, "warning");
                root.refresh();
            }
        }
    }
}
