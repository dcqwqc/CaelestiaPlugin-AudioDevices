pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import Quickshell.Io
import Caelestia.Config
import qs.components
import qs.components.controls
import qs.services
import qs.modules.nexus.common
import "lib/AudioModel.js" as Model

ColumnLayout {
    id: root

    property var settings: null
    property var snapshot: ({})
    property int revision: 0

    readonly property string helper: Qt.resolvedUrl("scripts/audio-devices-helper.py").toString().replace("file://", "")
    readonly property var provider: {
        try {
            return AudioPresentation.provider?.records ? AudioPresentation.provider : null;
        } catch (e) {
            return null;
        }
    }
    readonly property var outputs: recordsFor("sink")
    readonly property var inputs: recordsFor("source")

    Layout.fillWidth: true
    spacing: Tokens.spacing.extraSmall / 2

    function recordsFor(kind): var {
        void revision;
        const current = kind === "sink" ? Audio.sink : Audio.source;
        const nodes = [];
        for (const n of (kind === "sink" ? Audio.sinks : Audio.sources)) {
            if (n?.name)
                nodes.push({
                    name: n.name,
                    description: n.description ?? "",
                    nick: n.nickname ?? "",
                    mediaClass: n.properties?.["media.class"] ?? "",
                    props: n.properties ?? {},
                    ref: n
                });
        }
        const recs = Model.records({
            kind: kind,
            nodes: nodes,
            defaultName: current?.name ?? "",
            prefs: Model.prefsFromSettings(settings),
            snapshot: root.provider?.snapshot ?? snapshot,
            options: {
                autoDefaults: settings?.autoDefaults ?? true
            }
        });
        return recs.sort((a, b) => (a.hidden - b.hidden) || a.label.localeCompare(b.label));
    }

    function setMap(prop, key, value): void {
        if (settings)
            settings[prop] = Model.setInMap(settings[prop], key, value);
    }

    function use(rec): void {
        const entry = {
            key: rec.key,
            kind: rec.kind,
            label: rec.label,
            category: rec.category,
            nodeName: rec.nodeName,
            ref: rec.ref,
            isDefault: rec.isDefault,
            routed: rec.routed,
            action: rec.action,
            port: rec.port
        };
        if (rec.group)
            root.provider?.setPreferredMember(rec.kind + ":" + rec.group, rec.key);
        try {
            AudioPresentation.select(entry);
        } catch (e) {
            if (rec.ref)
                rec.kind === "source" ? Audio.setAudioSource(rec.ref) : Audio.setAudioSink(rec.ref);
        }
    }

    function statusText(rec): string {
        const parts = [rec.rawLabel];
        if (rec.isDefault)
            parts.push(qsTr("In use"));
        else if (rec.routed)
            parts.push(qsTr("In use through Spatial Audio"));
        if (rec.action === "port")
            parts.push(qsTr("needs profile switch"));
        if (rec.hidden)
            parts.push(rec.hiddenReason || qsTr("Hidden"));
        return parts.join(" · ");
    }

    Component.onCompleted: if (!provider)
        snapshotProc.running = true

    Connections {
        target: root.settings
        ignoreUnknownSignals: true

        function onAliasesJsonChanged(): void {
            root.revision++;
        }
        function onHiddenJsonChanged(): void {
            root.revision++;
        }
        function onGroupsJsonChanged(): void {
            root.revision++;
        }
        function onAutoDefaultsChanged(): void {
            root.revision++;
        }
    }

    Process {
        id: snapshotProc

        command: [root.helper, "snapshot"]
        stdout: StdioCollector {
            onStreamFinished: {
                try {
                    root.snapshot = JSON.parse(text);
                    root.revision++;
                } catch (e) {}
            }
        }
    }

    SectionHeader {
        first: true
        text: qsTr("Behaviour")
    }

    ToggleRow {
        Layout.fillWidth: true
        first: true
        text: qsTr("Friendly defaults")
        subtext: qsTr("Auto-name speakers, headphones and microphones; hide disconnected displays and system routes")
        checked: root.settings?.autoDefaults ?? true
        onToggled: if (root.settings)
            root.settings.autoDefaults = checked
    }

    ToggleRow {
        Layout.fillWidth: true
        last: true
        text: qsTr("Keep Spatial Audio in the path")
        subtext: qsTr("Choosing speakers or headphones moves Spatial Audio there instead of bypassing it")
        checked: root.settings?.routeThroughSpatial ?? true
        onToggled: if (root.settings)
            root.settings.routeThroughSpatial = checked
    }

    InfoRow {
        Layout.fillWidth: true
        Layout.topMargin: Tokens.spacing.small
        first: true
        label: qsTr("Native selectors")
        value: root.provider ? qsTr("Using these names") : qsTr("Core integration missing")
    }

    InfoRow {
        Layout.fillWidth: true
        label: qsTr("Sound card profile")
        value: {
            const cards = (root.provider?.snapshot ?? root.snapshot)?.cards ?? [];
            return cards.length ? String(cards[0].activeProfile ?? "") : qsTr("Unknown");
        }
    }

    InfoRow {
        Layout.fillWidth: true
        last: true
        label: qsTr("Spatial Audio")
        value: {
            const s = (root.provider?.snapshot ?? root.snapshot)?.spatial;
            if (!s?.installed)
                return qsTr("Not installed");
            if (!s.active)
                return qsTr("Off");
            const target = root.outputs.find(r => r.nodeName === s.physical);
            return qsTr("%1 → %2").arg(s.mode || "On").arg(target ? target.label : (s.physical || "?"));
        }
    }

    SectionHeader {
        text: qsTr("Outputs")
    }

    Repeater {
        model: root.outputs

        DeviceEditor {}
    }

    SectionHeader {
        text: qsTr("Inputs")
    }

    Repeater {
        model: root.inputs

        DeviceEditor {}
    }

    StyledText {
        Layout.fillWidth: true
        Layout.leftMargin: Tokens.padding.small
        Layout.rightMargin: Tokens.padding.small
        Layout.topMargin: Tokens.spacing.small
        text: qsTr("Names, visibility and groups follow the hardware port or Bluetooth address, so they survive reboots and profile switches. Devices with the same group name and direction share one row in the selectors; the row picks the device in use, otherwise the one you last chose here. The device in use is always listed, even when hidden.")
        color: Colours.palette.m3outline
        font: Tokens.font.body.small
        wrapMode: Text.WordWrap
    }

    IconTextButton {
        Layout.topMargin: Tokens.spacing.medium
        text: qsTr("Reset names, hidden devices and groups")
        icon: "restart_alt"
        verticalPadding: Tokens.padding.extraSmall
        onClicked: if (root.settings) {
            root.settings.aliasesJson = "{}";
            root.settings.hiddenJson = "{}";
            root.settings.groupsJson = "{}";
            root.settings.groupPreferredJson = "{}";
        }
    }

    component DeviceEditor: ColumnLayout {
        id: editor

        required property var modelData

        Layout.fillWidth: true
        Layout.bottomMargin: Tokens.spacing.small
        spacing: Tokens.spacing.extraSmall / 2

        ConnectedRect {
            Layout.fillWidth: true
            first: true
            implicitHeight: head.implicitHeight + head.anchors.margins * 2
            opacity: editor.modelData.hidden ? 0.7 : 1

            RowLayout {
                id: head

                anchors.fill: parent
                anchors.margins: Tokens.padding.medium
                anchors.leftMargin: Tokens.padding.largeIncreased
                anchors.rightMargin: Tokens.padding.medium
                spacing: Tokens.spacing.medium

                MaterialIcon {
                    text: editor.modelData.icon
                    color: editor.modelData.isDefault || editor.modelData.routed ? Colours.palette.m3primary : Colours.palette.m3onSurfaceVariant
                    font: Tokens.font.icon.medium
                    fill: editor.modelData.isDefault ? 1 : 0
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 0

                    StyledText {
                        Layout.fillWidth: true
                        text: editor.modelData.label
                        font: Tokens.font.body.small
                        elide: Text.ElideRight
                    }

                    StyledText {
                        Layout.fillWidth: true
                        text: root.statusText(editor.modelData)
                        color: Colours.palette.m3outline
                        font: Tokens.font.label.small
                        elide: Text.ElideRight
                    }
                }

                IconButton {
                    visible: !editor.modelData.isDefault && !editor.modelData.routed && editor.modelData.available !== "no"
                    icon: "check_circle"
                    type: IconButton.Text
                    onClicked: root.use(editor.modelData)
                }

                IconButton {
                    icon: editor.modelData.hidden ? "visibility_off" : "visibility"
                    type: IconButton.Text
                    onClicked: root.setMap("hiddenJson", editor.modelData.key, !editor.modelData.hidden)
                }

                IconButton {
                    visible: editor.modelData.userHidden !== null
                    icon: "undo"
                    type: IconButton.Text
                    onClicked: root.setMap("hiddenJson", editor.modelData.key, null)
                }
            }
        }

        TextFieldRow {
            label: qsTr("Name")
            value: editor.modelData.aliased ? editor.modelData.label : ""
            placeholderText: editor.modelData.autoLabel
            onEdited: v => root.setMap("aliasesJson", editor.modelData.key, v.trim())
        }

        TextFieldRow {
            last: true
            label: qsTr("Group")
            subtext: qsTr("Same name = one row in the selector")
            value: editor.modelData.group
            placeholderText: qsTr("None")
            onEdited: v => root.setMap("groupsJson", editor.modelData.key, v.trim())
        }
    }
}
