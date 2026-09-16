import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config
import gameswap
import mover
import state
import steam
import tui
import verify


class GameSwapTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.main = self.root / "Main library"
        self.secondary = self.root / "Secondary library"
        for library in (self.main, self.secondary):
            (library / "steamapps/common").mkdir(parents=True)
        for target, value in (("state.STATE_FILE", self.root / "state/transfer.json"),
                              ("state.STATE_DIR", self.root / "state"),
                              ("config.CONFIG_PATH", self.root / "config/config.json"),
                              ("config.LEGACY_CONFIG", self.root / "legacy/config.json")):
            context = patch(target, value)
            context.start()
            self.addCleanup(context.stop)
        context = patch("verify.is_steam_running", return_value=False)
        context.start()
        self.addCleanup(context.stop)
        self.first = self.game(self.main, "10", "Alpha Game", "Alpha")
        self.second = self.game(self.secondary, "20", "Béta Game", "Beta")

    def game(self, library, appid, name, folder):
        common = library / "steamapps/common" / folder
        (common / "empty").mkdir(parents=True)
        (common / "binary").write_bytes(b"abcd" * 1024)
        (common / "binary").chmod(0o755)
        (common / "link").symlink_to("binary")
        (common / "dangling").symlink_to("missing")
        manifest = library / "steamapps" / f"appmanifest_{appid}.acf"
        manifest.write_text(f'"AppState" {{ "appid" "{appid}" "name" "{name}" '
                            f'"installdir" "{folder}" "StateFlags" "4" }}', encoding="utf-8")
        return steam.detect_game(library, appid)

    def journal(self):
        return {"version": 1, "index": 0, "jobs": [mover.pack_game(self.first, self.secondary),
                mover.pack_game(self.second, self.main)], "transfer": None}

    def move_first(self, journal):
        return mover.move_steam_game(self.first, self.secondary, journal=journal)

    def run_queue(self, journal):
        with patch.multiple(gameswap, reset=lambda: None, set_game=lambda *a: None,
                            set_progress=lambda *a: None, set_stage=lambda *a: None):
            return gameswap.run_queue(journal)

    def test_catalog_names_ids_and_unicode_filter(self):
        self.game(self.main, "30", "Alpha Game", "Other Alpha")
        games, warnings = steam.scan_library(self.main)
        self.assertEqual([game["appid"] for game in games], ["10", "30"])
        self.assertFalse(warnings)
        self.assertEqual(steam.filter_games(games, "30")[0]["appid"], "30")
        self.assertEqual(steam.filter_games([self.second], "BÉTA"), [self.second])

    def test_invalid_and_partial_manifests_are_skipped(self):
        manifest = self.main / "steamapps/appmanifest_30.acf"
        manifest.write_text('"AppState" {')
        games, warnings = steam.scan_library(self.main)
        self.assertEqual(len(games), 1)
        self.assertEqual(len(warnings), 1)
        self.first["manifest"].write_text(self.first["manifest"].read_text().replace('"4"', '"1026"'))
        self.assertIsNotNone(steam.detect_game(self.main, "10"))

    def test_manifest_parser_handles_escaped_quotes_and_nested_keys(self):
        data = steam.parse_manifest('"AppState" { "name" "A \\"Game\\"" '
                                    '"nested" { "name" "Wrong" } // hi\n "appid" "10" }')
        self.assertEqual(data["name"], 'A "Game"')
        self.assertEqual(data["appid"], "10")

    def test_path_traversal_and_root_symlink_are_rejected(self):
        manifest = self.first["manifest"]
        original = manifest.read_text()
        manifest.write_text(original.replace('"Alpha"', '"../Alpha"'))
        self.assertIsNone(steam.detect_game(self.main, "10"))
        manifest.write_text(original)
        shutil.rmtree(self.first["game_path"])
        self.first["game_path"].symlink_to(self.second["game_path"], target_is_directory=True)
        self.assertIsNone(steam.detect_game(self.main, "10"))

    def test_hash_verification_without_callback(self):
        target = self.root / "copy"
        shutil.copytree(self.first["game_path"], target, symlinks=True)
        self.assertTrue(verify.compare_directories(self.first["game_path"], target))
        (target / "binary").write_bytes(b"xxxx" * 1024)
        self.assertFalse(verify.compare_directories(self.first["game_path"], target))

    def test_empty_directories_and_link_targets_are_verified(self):
        target = self.root / "copy"
        shutil.copytree(self.first["game_path"], target, symlinks=True)
        (target / "empty").rmdir()
        self.assertFalse(verify.compare_directories(self.first["game_path"], target))
        (target / "empty").mkdir()
        (target / "dangling").unlink()
        (target / "dangling").symlink_to("other")
        self.assertFalse(verify.compare_directories(self.first["game_path"], target))

    def test_real_rsync_swap(self):
        journal = self.journal()
        state.save_state(journal)
        success, message = self.run_queue(journal)
        self.assertTrue(success, message)
        self.assertIsNone(state.load_state())
        self.assertIsNone(steam.detect_game(self.main, "10"))
        self.assertIsNone(steam.detect_game(self.secondary, "20"))
        self.assertIsNotNone(steam.detect_game(self.secondary, "10"))
        self.assertIsNotNone(steam.detect_game(self.main, "20"))
        self.assertEqual((self.secondary / "steamapps/common/Alpha/binary").stat().st_mode & 0o777, 0o755)

    def test_failed_copy_keeps_source_and_can_resume(self):
        journal = self.journal()
        with patch("mover.copy_directory", side_effect=RuntimeError("disk full")):
            result = self.move_first(journal)
        self.assertFalse(result["success"])
        self.assertTrue(self.first["game_path"].exists())
        saved = state.load_state()
        self.assertEqual(saved["jobs"], journal["jobs"])
        self.assertTrue(self.move_first(saved)["success"])

    def test_failed_verification_keeps_original(self):
        journal = self.journal()
        real_receipt = verify.directory_receipt

        def corrupt(path, callback=None):
            value = real_receipt(path, callback)
            if Path(path).name == "game":
                value["binary"][-1] = "wrong"
            return value

        with patch("mover.directory_receipt", side_effect=corrupt):
            result = self.move_first(journal)
        self.assertFalse(result["success"])
        self.assertTrue(self.first["game_path"].exists())
        self.assertTrue(self.first["manifest"].exists())
        self.assertTrue(self.move_first(state.load_state())["success"])

    def test_partial_source_deletion_keeps_destination_and_resumes(self):
        journal = self.journal()
        real_remove = shutil.rmtree

        def partial_remove(path, *args, **kwargs):
            if Path(path) == self.first["game_path"]:
                (Path(path) / "binary").unlink()
                raise PermissionError("cleanup denied")
            return real_remove(path, *args, **kwargs)

        with patch("mover.shutil.rmtree", side_effect=partial_remove):
            result = self.move_first(journal)
        self.assertFalse(result["success"])
        self.assertIn("cleanup is pending", result["message"])
        self.assertTrue((self.secondary / "steamapps/common/Alpha/binary").exists())
        self.assertTrue(self.move_first(state.load_state())["success"])

    def test_manifest_cleanup_failure_never_removes_destination(self):
        original_unlink = Path.unlink

        def fail_manifest(path, *args, **kwargs):
            if path == self.first["manifest"]:
                raise PermissionError("manifest locked")
            return original_unlink(path, *args, **kwargs)

        with patch.object(Path, "unlink", fail_manifest):
            result = self.move_first(self.journal())
        self.assertFalse(result["success"])
        self.assertTrue((self.secondary / "steamapps/common/Alpha/binary").exists())
        self.assertTrue(self.first["game_path"].exists())
        self.assertTrue(self.move_first(state.load_state())["success"])

    def test_resume_after_game_publish_before_manifest_publish(self):
        original_rename = Path.rename

        def interrupt_manifest(path, target):
            if path.name == "manifest.acf":
                raise OSError("interrupted publish")
            return original_rename(path, target)

        with patch.object(Path, "rename", interrupt_manifest):
            result = self.move_first(self.journal())
        self.assertFalse(result["success"])
        self.assertEqual(state.load_state()["transfer"]["stage"], "publishing")
        self.assertTrue(self.move_first(state.load_state())["success"])

    def test_resume_checks_destination_before_more_source_cleanup(self):
        with patch("mover.shutil.rmtree", side_effect=PermissionError("cleanup denied")):
            self.move_first(self.journal())
        target = self.secondary / "steamapps/common/Alpha/binary"
        target.write_bytes(b"xxxx" * 1024)
        result = self.move_first(state.load_state())
        self.assertFalse(result["success"])
        self.assertTrue((self.first["game_path"] / "binary").exists())

    def test_existing_destination_is_never_overwritten(self):
        target = self.secondary / "steamapps/common/Alpha"
        target.mkdir()
        (target / "mine").write_text("keep")
        result = self.move_first(self.journal())
        self.assertFalse(result["success"])
        self.assertEqual((target / "mine").read_text(), "keep")

    def test_second_move_failure_reports_partial_swap_and_resumes(self):
        actual_copy = mover.copy_directory

        def copy_first_only(source, destination, callback=None):
            if source == self.second["game_path"]:
                raise RuntimeError("second copy failed")
            return actual_copy(source, destination, callback)

        with patch("mover.copy_directory", side_effect=copy_first_only):
            success, message = self.run_queue(self.journal())
        self.assertFalse(success)
        self.assertIn("1/2", message)
        self.assertEqual(state.load_state()["index"], 1)
        success, message = self.run_queue(state.load_state())
        self.assertTrue(success, message)

    def test_final_state_cleanup_error_does_not_report_transfer_failure(self):
        with patch("gameswap.clear_state", side_effect=PermissionError("read-only state")):
            success, message = self.run_queue(self.journal())
        self.assertTrue(success)
        self.assertIn("cleanup is pending", message)
        self.assertEqual(state.load_state()["index"], 2)

    def test_proton_workshop_and_shader_data_move_with_the_game(self):
        folders = ("compatdata/10/pfx/drive_c/users", "shadercache/10", "workshop/content/10/123")
        for folder in folders:
            source = self.main / "steamapps" / folder
            source.mkdir(parents=True)
            (source / "save.dat").write_bytes(b"saved progress")
        prefix = self.main / "steamapps/compatdata/10/pfx"
        (prefix / "dosdevices").mkdir()
        (prefix / "dosdevices/z:").symlink_to("/")
        (self.main / "steamapps/workshop/appworkshop_10.acf").write_text('"Workshop" { "appid" "10" }')
        result = self.move_first(self.journal())
        self.assertTrue(result["success"], result["message"])
        for folder in folders:
            self.assertFalse((self.main / "steamapps" / folder).exists())
            self.assertEqual((self.secondary / "steamapps" / folder / "save.dat").read_bytes(), b"saved progress")
        self.assertTrue((self.secondary / "steamapps/compatdata/10/pfx/dosdevices/z:").is_symlink())
        self.assertTrue((self.secondary / "steamapps/workshop/appworkshop_10.acf").exists())

    def test_existing_proton_prefix_blocks_swap_without_overwriting(self):
        for library in (self.main, self.secondary):
            (library / "steamapps/compatdata/10").mkdir(parents=True)
        result = self.move_first(self.journal())
        self.assertFalse(result["success"])
        self.assertIn("Destination already exists", result["message"])
        self.assertTrue(self.first["game_path"].exists())

    def test_auxiliary_cleanup_failure_resumes_after_game_is_removed(self):
        prefix = self.main / "steamapps/compatdata/10"
        prefix.mkdir(parents=True)
        (prefix / "save.dat").write_bytes(b"saved progress")
        real_remove = shutil.rmtree

        def fail_prefix(path, *args, **kwargs):
            if Path(path) == prefix:
                raise PermissionError("prefix cleanup denied")
            return real_remove(path, *args, **kwargs)

        with patch("mover.shutil.rmtree", side_effect=fail_prefix):
            result = self.move_first(self.journal())
        self.assertFalse(result["success"])
        self.assertFalse(self.first["game_path"].exists())
        self.assertTrue((self.secondary / "steamapps/compatdata/10/save.dat").exists())
        result = self.move_first(state.load_state())
        self.assertTrue(result["success"], result["message"])
        self.assertFalse(prefix.exists())

    def test_source_changes_do_not_remove_its_manifest(self):
        def change_source(message):
            if message == "Checking installed copy before cleanup...":
                (self.first["game_path"] / "binary").write_bytes(b"new save")

        result = mover.move_steam_game(self.first, self.secondary, stage_callback=change_source,
                                      journal=self.journal())
        self.assertFalse(result["success"])
        self.assertTrue(self.first["manifest"].exists())
        self.assertEqual((self.first["game_path"] / "binary").read_bytes(), b"new save")


    def test_plan_single_move(self):
        with patch("gameswap.verify_game", return_value=[]):
            jobs = gameswap.plan_move(self.first, self.secondary)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["appid"], "10")
        self.assertEqual(Path(jobs[0]["destination"]), self.secondary)

    def test_single_move_queue_completes(self):
        journal = {"version": 1, "mode": "single", "index": 0,
                   "jobs": [mover.pack_game(self.first, self.secondary)], "transfer": None}
        success, message = self.run_queue(journal)
        self.assertTrue(success, message)
        self.assertIn("Game was moved", message)
        self.assertFalse(self.first["game_path"].exists())
        self.assertTrue((self.secondary / "steamapps/common/Alpha/binary").exists())

    def test_transfer_order_can_start_with_secondary(self):
        from types import SimpleNamespace
        real_stat = Path.stat
        amount = verify.get_transfer_size(self.second, self.main)

        def fake_stat(path, *args, **kwargs):
            if path == self.main:
                return SimpleNamespace(st_dev=1)
            if path == self.secondary:
                return SimpleNamespace(st_dev=2)
            return real_stat(path, *args, **kwargs)

        def disk_usage(path):
            free = verify.SPACE_MARGIN + (amount if Path(path) == self.main else 1024)
            return shutil._ntuple_diskusage(free * 2, free, free)

        with patch("gameswap.verify_game", return_value=[]), \
                patch.object(Path, "stat", fake_stat), patch("gameswap.shutil.disk_usage", side_effect=disk_usage):
            jobs = gameswap.plan_swap(self.first, self.second)
        self.assertEqual(jobs[0]["appid"], "20")

    def test_configuration_migrates_and_normalizes(self):
        config.LEGACY_CONFIG.parent.mkdir()
        config.LEGACY_CONFIG.write_text(json.dumps({"main_library": str(self.main),
                                                   "backup_library": str(self.secondary)}))
        self.assertEqual(config.load_config()["main_library"], str(self.main))
        config.set_library("main_library", self.main / "steamapps")
        self.assertTrue(config.CONFIG_PATH.exists())
        with self.assertRaises(ValueError):
            config.set_library("backup_library", self.main)

    def test_second_instance_is_blocked(self):
        handle = state.acquire_lock()
        try:
            with self.assertRaises(RuntimeError):
                state.acquire_lock()
        finally:
            handle.close()

    def test_running_steam_blocks_transfer(self):
        with patch("verify.is_steam_running", return_value=True):
            result = self.move_first(self.journal())
        self.assertFalse(result["success"])
        self.assertTrue(self.first["game_path"].exists())

    def test_steam_detection_does_not_match_arbitrary_command_arguments(self):
        fake = type("Result", (), {"stdout": "steamhelper\npython\nsteamwebhelper\n"})()
        original = self._steam_detector
        with patch("verify.subprocess.run", return_value=fake):
            self.assertTrue(original())
        fake.stdout = "python\nsteamhelper\n"
        with patch("verify.subprocess.run", return_value=fake):
            self.assertFalse(original())

    _steam_detector = staticmethod(verify.is_steam_running)

    def test_browser_filter_and_selection(self):
        keys = iter(["B", "é", "t", "a", "ENTER"])
        with patch("tui.enable_raw_mode"), patch("tui.disable_raw_mode"), \
                patch("tui.get_key", side_effect=lambda: next(keys)), patch("sys.stdout", new=io.StringIO()):
            game = tui.browse_games(self.secondary, "Secondary")
        self.assertEqual(game["appid"], "20")

    def test_browser_empty_filter_backspace_and_cancel(self):
        keys = iter(["x", "ENTER", "BACKSPACE", "ESC"])
        with patch("tui.enable_raw_mode"), patch("tui.disable_raw_mode"), \
                patch("tui.get_key", side_effect=lambda: next(keys)), patch("sys.stdout", new=io.StringIO()):
            self.assertIsNone(tui.browse_games(self.main, "Main"))

    def test_not_enough_space_blocks_swap(self):
        disk = shutil._ntuple_diskusage(1, 1, 0)
        with patch("gameswap.shutil.disk_usage", return_value=disk):
            with self.assertRaisesRegex(ValueError, "Neither transfer order"):
                gameswap.plan_swap(self.first, self.second)

    def test_corrupt_recovery_record_is_not_discarded(self):
        state.STATE_FILE.parent.mkdir()
        state.STATE_FILE.write_text("{broken")
        with self.assertRaises(ValueError):
            state.load_state()
        self.assertTrue(state.STATE_FILE.exists())


if __name__ == "__main__":
    unittest.main()
