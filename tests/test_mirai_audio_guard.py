"""Unit tests with no changes to real audio."""
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

MODULE = Path(__file__).resolve().parents[1] / "scripts/mirai-audio-guard.py"
spec = importlib.util.spec_from_file_location("mirai_guard", MODULE)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


class AudioGuardTests(unittest.TestCase):
    def test_recovery_scoped_to_selected_speaker_and_unintentional_mute(self):
        s = guard.SPEAKER
        self.assertTrue(guard.should_heal(s, True, False))
        self.assertFalse(guard.should_heal(s, True, True))
        self.assertFalse(guard.should_heal(s, False, False))
        self.assertFalse(guard.should_heal("ue_boombox_lowlatency", True, False))

    def test_intent_persists_and_is_atomic(self):
        with tempfile.TemporaryDirectory() as d:
            with patch.object(guard, "STATE_DIR", Path(d)), patch.object(guard, "STATE_FILE", Path(d)/"intent.json"):
                guard.save_intent(True)
                self.assertTrue(guard.explicit_mute())
                self.assertTrue(guard.mute_intent_pending())
                guard.save_intent(False)
                self.assertFalse(guard.explicit_mute())

    def test_unexpected_mute_restored_only_on_speaker(self):
        s = guard.SPEAKER
        with patch.object(guard, "selected_sink", return_value=s), patch.object(guard, "is_muted", return_value=True), patch.object(guard, "explicit_mute", return_value=False), patch.object(guard.time, "sleep"), patch.object(guard, "pactl") as pactl:
            self.assertEqual(guard.check_once()["status"], "recovered")
            pactl.assert_called_once_with("set-sink-mute", s, "0")

    def test_intentional_mute_never_restored(self):
        with patch.object(guard, "selected_sink", return_value=guard.SPEAKER), patch.object(guard, "is_muted", return_value=True), patch.object(guard, "explicit_mute", return_value=True), patch.object(guard, "pactl") as pactl:
            self.assertEqual(guard.check_once()["status"], "user_muted")
            pactl.assert_not_called()

    def test_other_sink_not_changed(self):
        with patch.object(guard, "selected_sink", return_value="ue_boombox_lowlatency"), patch.object(guard, "pactl") as pactl:
            self.assertEqual(guard.check_once()["status"], "other_output")
            pactl.assert_not_called()

    def test_manual_toggle_marks_intent_before_sink_change(self):
        events = []
        with patch.object(guard, "selected_sink", return_value=guard.SPEAKER), patch.object(guard, "is_muted", return_value=False), patch.object(guard, "save_intent", side_effect=lambda v: events.append(("intent",v))), patch.object(guard, "pactl", side_effect=lambda *args: events.append(("pactl",args))):
            self.assertTrue(guard.set_explicit("toggle")["muted"])
        self.assertEqual(events, [("intent", True), ("pactl", ("set-sink-mute", guard.SPEAKER, "1"))])

    def test_pending_manual_mute_does_not_get_cleared_by_watcher(self):
        with patch.object(guard, "selected_sink", return_value=guard.SPEAKER), patch.object(guard, "is_muted", return_value=False), patch.object(guard, "explicit_mute", return_value=True), patch.object(guard, "mute_intent_pending", return_value=True), patch.object(guard, "save_intent") as save:
            self.assertEqual(guard.check_once()["status"], "manual_mute_pending")
            save.assert_not_called()

    def test_status_never_mutates_saved_intent(self):
        with patch.object(guard, "selected_sink", return_value=guard.SPEAKER), patch.object(guard, "is_muted", return_value=False), patch.object(guard, "explicit_mute", return_value=True), patch.object(guard, "mute_intent_pending", return_value=False), patch.object(guard, "save_intent") as save:
            self.assertEqual(guard.check_once(heal=False)["status"], "ready")
            save.assert_not_called()

    def test_manual_unmute_resets_persisted_state(self):
        with patch.object(guard, "selected_sink", return_value=guard.SPEAKER), patch.object(guard, "is_muted", return_value=False), patch.object(guard, "explicit_mute", return_value=True), patch.object(guard, "mute_intent_pending", return_value=False), patch.object(guard, "save_intent") as save:
            self.assertEqual(guard.check_once()["status"], "ready")
            save.assert_called_once_with(False)


if __name__ == "__main__":
    unittest.main()
