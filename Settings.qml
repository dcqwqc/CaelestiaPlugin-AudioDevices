import Caelestia.Plugins

SettingsObject {
    property bool autoDefaults: true
    SettingMeta on autoDefaults {
        label: "Friendly defaults"
        description: "Name built-in speakers, headphones and microphones, and hide disconnected displays and system routes until you reveal them."
        icon: "auto_fix_high"
        inputType: SettingMeta.Switch
    }

    property bool routeThroughSpatial: true
    SettingMeta on routeThroughSpatial {
        label: "Keep Spatial Audio in the path"
        description: "While Spatial Audio is the active output, choosing a speaker or headphones moves Spatial Audio onto it instead of bypassing it."
        icon: "surround_sound"
        inputType: SettingMeta.Switch
    }

    // Persisted per stable device key (never numeric PipeWire ids).
    property string aliasesJson: "{}"
    property string hiddenJson: "{}"
    property string groupsJson: "{}"
    property string groupPreferredJson: "{}"
}
