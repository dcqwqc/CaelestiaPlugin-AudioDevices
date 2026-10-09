#!/usr/bin/env python3
"""Enable/disable dcqwqc/audiodevices in ~/.config/caelestia/plugins.json (settings are kept)."""
import json
import os
import sys
from pathlib import Path

PLUGIN = "dcqwqc/audiodevices"
path = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "caelestia/plugins.json"
enable = (sys.argv[1] if len(sys.argv) > 1 else "enable") == "enable"

data = json.loads(path.read_text()) if path.exists() else {}
enabled = data.setdefault("enabled", [])
changed = False
if enable and PLUGIN not in enabled:
    enabled.append(PLUGIN)
    changed = True
if not enable and PLUGIN in enabled:
    enabled.remove(PLUGIN)
    changed = True
if changed:
    tmp = path.with_suffix(".json.audiodevices-new")
    tmp.write_text(json.dumps(data, indent=4) + "\n")
    tmp.replace(path)
print(("enabled " if enable else "disabled ") + PLUGIN + ("" if changed else " (unchanged)"))
