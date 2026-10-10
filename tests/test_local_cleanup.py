"""Isolated fixtures only: no real home, browser, keychain, or app mutations."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/local_cleanup.py"
spec = importlib.util.spec_from_file_location("cleanup", SCRIPT)
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)
REAL_PROCESSES = c.processes


@unittest.skipIf(os.name == "nt", "macOS backend: exercised on macOS; native Windows has its own suite")
class CleanupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent)
        self.root = Path(self.temporary.name).resolve()
        self.home = self.root / "fixture-home"
        self.home.mkdir()
        self.plan = self.root / "plan.json"
        self.options = {key: False for key in c.OPTION_KEYS}
        self.platform = patch.object(c.sys, "platform", "darwin")
        self.platform.start()
        self.processes = patch.object(c, "processes", return_value=[])
        self.processes.start()

    def tearDown(self):
        self.processes.stop()
        self.platform.stop()
        self.temporary.cleanup()

    def put(self, relative, content="fixture"):
        target = self.home / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        os.chmod(target, 0o600)
        return target

    def config(self):
        original = {"oauthAccount": {"token": "fixture-private-secret"}, "anonymousId": "old-account-id",
                    "userID": "application-user", "machineID": "application-machine",
                    "projects": {"kept": "project config"}, "unknownFutureKey": {"keep": True}}
        self.put(".claude.json", json.dumps(original))
        self.put(".claude/backups/.claude.json.backup.1", json.dumps(original))
        return original

    def audited(self, **options):
        self.options.update(options)
        result = c.audit(self.plan, self.options, self.home)
        self.assertFalse(result["source_modified"])
        return c.load_json(self.plan)

    def applied(self):
        with patch.object(c, "terminal_confirm") as confirmation:
            result = c.apply(self.plan, self.home)
        confirmation.assert_called_once()
        return result, c.load_json(Path(result["receipt"]))

    def test_audit_is_read_only_and_exactly_scoped(self):
        target = self.put(".claude/cache/data", "cache")
        kept = self.put(".claude/projects/history.jsonl", "session")
        before = kept.read_bytes()
        plan = self.audited()
        self.assertEqual([entry["path"] for entry in plan["targets"]], [str(target.parent)])
        self.assertEqual(kept.read_bytes(), before)
        self.assertFalse((self.home / ".Trash").exists())

    def test_audit_without_plan_writes_nothing(self):
        target = self.put(".claude/cache/data")
        result = c.audit(None, self.options, self.home)
        self.assertFalse(result["plan_written"])
        self.assertIsNone(result["plan"])
        self.assertIsNone(result["plan_id"])
        self.assertTrue(target.exists())
        self.assertEqual(set(self.root.iterdir()), {self.home})

    def test_crash_names_are_narrowly_filtered(self):
        diagnostic = self.put("Library/Logs/DiagnosticReports/Claude-2026-10-02.ips")
        crash = self.put("Library/Application Support/CrashReporter/Claude_A12B-3456.plist")
        kept = self.put("Library/Logs/DiagnosticReports/Claude-unrelated-user-notes.txt")
        other = self.put("Library/Application Support/CrashReporter/OtherApp_A12B.plist")
        result = c.audit(None, self.options, self.home)
        paths = [entry["path"] for entry in result["targets"]]
        self.assertIn(str(diagnostic), paths)
        self.assertIn(str(crash), paths)
        self.assertNotIn(str(kept), paths)
        self.assertNotIn(str(other), paths)

    def test_full_backup_move_and_separate_purge_leave_unrelated_trash(self):
        target = self.put(".claude/cache/data", "cache-content")
        protected = self.put(".claude/projects/preserved.jsonl", "project-history")
        self.put(".claude/settings.json", '{"env":{"DISABLE_TELEMETRY":"1"}}')
        original = self.config()
        unrelated = self.put(".Trash/unrelated.txt", "do-not-delete")
        self.audited()
        result, receipt = self.applied()
        self.assertEqual(result["status"], "complete")
        self.assertEqual(protected.read_text(), "project-history")
        self.assertFalse(target.exists())
        backup = Path(result["recovery"])
        self.assertEqual((backup / "dot-claude/cache/data").read_text(), "cache-content")
        self.assertEqual(c.load_json(backup / "claude.json"), original)
        self.assertEqual((backup / "claude.json").stat().st_mode & 0o777, 0o600)
        self.assertEqual(backup.stat().st_mode & 0o777, 0o700)
        with patch.object(c, "terminal_confirm") as confirmation:
            purged = c.purge(Path(result["receipt"]), self.home)
        confirmation.assert_called_once()
        self.assertFalse(purged["recoverable"])
        self.assertFalse(backup.exists())
        self.assertFalse(Path(result["trash"]).exists())
        self.assertEqual(unrelated.read_text(), "do-not-delete")
        with self.assertRaises(c.Stop):
            c.purge(Path(result["receipt"]), self.home)

    def test_reset_preserves_app_ids_and_unrecognized_config(self):
        original = self.config()
        self.audited(reset_account=True)
        result, receipt = self.applied()
        for relative in (".claude.json", ".claude/backups/.claude.json.backup.1"):
            updated = c.load_json(self.home / relative)
            self.assertFalse(c.ACCOUNT_FIELDS.intersection(updated))
            self.assertEqual(updated["userID"], original["userID"])
            self.assertEqual(updated["machineID"], original["machineID"])
            self.assertEqual(updated["unknownFutureKey"], original["unknownFutureKey"])
            self.assertEqual(updated["projects"], original["projects"])
        self.assertEqual(len(receipt["rewritten"]), 2)

    def test_optional_ids_synchronize_internal_backups(self):
        original = self.config()
        self.audited(reset_account=True, rotate_local_id=True)
        self.applied()
        primary = c.load_json(self.home / ".claude.json")
        internal = c.load_json(self.home / ".claude/backups/.claude.json.backup.1")
        for field in ("userID", "machineID"):
            self.assertNotEqual(primary[field], original[field])
            self.assertEqual(primary[field], internal[field])
            self.assertEqual(len(primary[field]), 64)

    def test_new_changed_or_tampered_targets_refuse_before_confirmation(self):
        self.put(".claude/cache/file", "one")
        self.audited()
        self.put("Library/Logs/Claude/new.log", "new-target")
        with patch.object(c, "terminal_confirm") as confirmation:
            with self.assertRaises(c.Stop):
                c.apply(self.plan, self.home)
        confirmation.assert_not_called()
        self.assertFalse((self.home / ".claude-cleanup-recovery").exists())
        plan = c.load_json(self.plan)
        plan["targets"] = [{"path": str(self.home / "Documents")}]
        c.atomic_json(self.plan, plan)
        with self.assertRaises(c.Stop):
            c.apply(self.plan, self.home)

    def test_confirmation_id_binds_options_and_consistently_expanded_targets(self):
        self.put(".claude/cache/file", "cache")
        self.put("Library/Application Support/Claude/local-work", "preserve-until-new-confirmation")
        plan = self.audited()
        approved_id = plan["plan_id"]
        plan["options"]["desktop"] = True
        plan["targets"], plan["configs"] = c.discover(self.home, plan["options"])
        with self.assertRaises(c.Stop):
            c.validate_plan(plan, self.home)
        plan["plan_id"] = c.plan_digest(plan)
        self.assertNotEqual(plan["plan_id"], approved_id)
        c.validate_plan(plan, self.home)
        c.atomic_json(self.plan, plan)
        captured = io.StringIO()
        with contextlib.redirect_stdout(captured), patch.object(c.sys.stdin, "isatty", return_value=True), \
             patch.object(c.sys.stdout, "isatty", return_value=True), \
             patch("builtins.input", return_value="CONFIRM " + approved_id), self.assertRaises(c.Stop):
            c.apply(self.plan, self.home)
        self.assertFalse((self.home / ".claude-cleanup-recovery").exists())
        self.assertTrue((self.home / "Library/Application Support/Claude/local-work").exists())

    def test_symlink_targets_and_parents_refused_backup_links_not_followed(self):
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "data").write_text("do-not-touch")
        (self.home / ".claude").mkdir()
        (self.home / ".claude/cache").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(c.Stop):
            self.audited()
        (self.home / ".claude/cache").unlink()
        (self.home / ".claude/plugins").symlink_to(outside, target_is_directory=True)
        self.audited()
        result, _ = self.applied()
        self.assertTrue((Path(result["recovery"]) / "dot-claude/plugins").is_symlink())
        with patch.object(c, "terminal_confirm"):
            c.purge(Path(result["receipt"]), self.home)
        self.assertEqual((outside / "data").read_text(), "do-not-touch")

    def test_running_process_and_non_tty_refuse_without_writes(self):
        self.put(".claude/cache/file")
        self.audited()
        with patch.object(c, "processes", return_value=[{"pid": 123, "role": "Claude CLI"}]):
            with self.assertRaises(c.Stop):
                c.apply(self.plan, self.home)
        with patch.object(c.sys.stdin, "isatty", return_value=False):
            with self.assertRaises(c.Stop):
                c.apply(self.plan, self.home)
        self.assertFalse((self.home / ".claude-cleanup-recovery").exists())

    def test_unknown_options_home_changes_and_rotation_dependency_rejected(self):
        self.audited()
        plan = c.load_json(self.plan)
        for invalid in ({**self.options, "anything": True}, {**self.options, "desktop": 1},
                        {**self.options, "rotate_local_id": True}):
            plan["options"] = invalid
            with self.assertRaises(c.Stop):
                c.validate_plan(plan, self.home)
        plan["options"] = self.options
        plan["home"] = str(self.root)
        with self.assertRaises(c.Stop):
            c.validate_plan(plan, self.home)

    def test_purge_marker_or_receipt_tampering_protects_unrelated_directory(self):
        self.put(".claude/cache/data")
        self.audited()
        result, receipt = self.applied()
        original = dict(receipt)
        receipt["trash"] = str(self.home / ".Trash")
        c.atomic_json(Path(result["receipt"]), receipt)
        with self.assertRaises(c.Stop):
            c.purge(Path(result["receipt"]), self.home)
        c.atomic_json(Path(result["receipt"]), original)
        marker = Path(result["trash"]) / c.MARKER
        marker.unlink()
        with self.assertRaises(c.Stop):
            c.purge(Path(result["receipt"]), self.home)
        self.assertTrue(Path(result["trash"]).exists())

    def test_desktop_option_is_explicit_and_partial_failure_stops(self):
        desktop = self.put("Library/Application Support/Claude/local-attachment", "attachment")
        self.put(".claude/cache/file")
        plan = self.audited()
        self.assertNotIn(str(desktop.parent), [entry["path"] for entry in plan["targets"]])
        self.plan.unlink()
        self.audited(desktop=True)
        with patch.object(c, "terminal_confirm"), patch.object(c.shutil, "move", side_effect=OSError("private secret")):
            captured = io.StringIO()
            with contextlib.redirect_stdout(captured), self.assertRaises(c.Stop):
                c.apply(self.plan, self.home)
        self.assertIn('"status": "partial"', captured.getvalue())
        self.assertNotIn("private secret", captured.getvalue())
        receipt = c.load_json(self.root / "plan.receipt.json")
        self.assertEqual(receipt["status"], "partial")
        self.assertTrue(desktop.exists())
        self.assertTrue(Path(receipt["recovery"]).exists())

    def test_unsupported_platform_writes_nothing(self):
        with patch.object(c.sys, "platform", "linux"):
            result = c.audit(self.plan, self.options, self.home)
            self.assertEqual(result["status"], "unsupported_read_only")
            self.assertFalse(self.plan.exists())
            with self.assertRaises(c.Stop):
                c.apply(self.plan, self.home)

    def test_move_verification_failure_receipt_identifies_moved_destination(self):
        target = self.put(".claude/cache/data", "recover-me")
        self.audited()
        real_entries = c.tree_entries
        def entries(path, **kwargs):
            if path.name.startswith("001-") and kwargs.get("hashes"):
                raise c.Stop("Fixture post-move verification failure")
            return real_entries(path, **kwargs)
        with patch.object(c, "terminal_confirm"), patch.object(c, "tree_entries", side_effect=entries), \
             contextlib.redirect_stdout(io.StringIO()), self.assertRaises(c.Stop):
            c.apply(self.plan, self.home)
        receipt = c.load_json(self.root / "plan.receipt.json")
        self.assertEqual(receipt["status"], "partial")
        self.assertEqual(len(receipt["moved"]), 1)
        moved = receipt["moved"][0]
        self.assertTrue(moved["attempted"])
        self.assertTrue(moved["move_returned"])
        self.assertFalse(moved["content_verified"])
        self.assertFalse(target.exists())
        self.assertEqual((Path(moved["destination"]) / "data").read_text(), "recover-me")

    def test_keychain_verification_failure_records_completed_deletion(self):
        state = {"deleted": False}
        def present():
            if state["deleted"]:
                raise c.Stop("Fixture keychain visibility loss after deletion")
            return True
        class Result:
            returncode = 0
        def command(args, **kwargs):
            self.assertEqual(args, ["/usr/bin/security", "delete-generic-password", "-s", c.SERVICE])
            state["deleted"] = True
            return Result()
        with patch.object(c, "keychain_present", side_effect=present):
            self.audited(keychain=True)
            with patch.object(c, "terminal_confirm"), patch.object(c.subprocess, "run", side_effect=command), \
                 contextlib.redirect_stdout(io.StringIO()), self.assertRaises(c.Stop):
                c.apply(self.plan, self.home)
        receipt = c.load_json(self.root / "plan.receipt.json")
        self.assertTrue(receipt["keychain_deleted"])
        self.assertEqual(receipt["status"], "partial")

    def test_keychain_lookup_never_reads_secret_and_process_output_withheld(self):
        class Result:
            returncode = 0
            stdout = b"secret"
        with patch.object(c.subprocess, "run", return_value=Result()) as command:
            self.assertTrue(c.keychain_present())
        self.assertEqual(command.call_args.args[0], ["/usr/bin/security", "find-generic-password", "-s", c.SERVICE])
        self.assertNotIn("-g", command.call_args.args[0])

    def test_process_visibility_failure_and_sanitized_detection(self):
        class Result:
            returncode = 0
            def __init__(self, stdout):
                self.stdout = stdout
        responses = [Result("99199 node\n"),
                     Result("99199 node /fixture/node_modules/@anthropic-ai/claude-code/cli.js --token private-test-token\n")]
        with patch.object(c.subprocess, "run", side_effect=responses):
            found = REAL_PROCESSES()
        self.assertEqual(found, [{"pid": 99199, "role": "Claude CLI"}])
        self.assertNotIn("private-test-token", json.dumps(found))
        denied = Result("")
        denied.returncode = 1
        with patch.object(c.subprocess, "run", return_value=denied), self.assertRaises(c.Stop):
            REAL_PROCESSES()

    def test_explicit_confirmation_and_cancellation(self):
        captured = io.StringIO()
        with contextlib.redirect_stdout(captured), patch.object(c.sys.stdin, "isatty", return_value=True), \
             patch.object(c.sys.stdout, "isatty", return_value=True), patch("builtins.input", return_value="CONFIRM id"):
            c.terminal_confirm("CONFIRM id", {"fixture": "reviewed"})
        with contextlib.redirect_stdout(captured), patch.object(c.sys.stdin, "isatty", return_value=True), \
             patch.object(c.sys.stdout, "isatty", return_value=True), patch("builtins.input", return_value="yes"), self.assertRaises(c.Stop):
            c.terminal_confirm("CONFIRM id", {"fixture": "reviewed"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
