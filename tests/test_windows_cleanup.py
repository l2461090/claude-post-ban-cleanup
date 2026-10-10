"""Native Windows + portable fixture tests. Never operate on real user data."""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import windows_cleanup as w
import local_cleanup as entrypoint

REAL_PROCESSES = w.processes
REAL_PACKAGES = w.packages


class WindowsCleanupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent)
        self.root = Path(self.temp.name).resolve()
        self.home = self.root / "fixture-user-测试"
        self.home.mkdir()
        self.plan_path = self.root / "plan.json"
        self.options = {key: False for key in w.OPTIONS}
        self.patches = [patch.object(w.sys, "platform", "win32"),
                        patch.object(w, "processes", return_value=[]),
                        patch.object(w, "packages", return_value=[]),
                        patch.dict(os.environ, {"APPDATA": str(self.home / "AppData/Roaming"),
                                               "LOCALAPPDATA": str(self.home / "AppData/Local"),
                                               "CLAUDE_CONFIG_DIR": str(self.home / ".claude")})]
        for p in self.patches:
            p.start()
        if os.name == "nt":
            # Diagnostics only for isolated fake fixtures on CI. Production
            # PowerShell output remains withheld by windows_cleanup.py.
            run = subprocess.run
            def fixture_command(args, **kwargs):
                result = run(args, **kwargs)
                if result.returncode and str(args[0]).lower().endswith("powershell.exe"):
                    raise AssertionError("Fixture PowerShell failure: " + str(result.stderr))
                return result
            diagnostic = patch.object(w.subprocess, "run", side_effect=fixture_command)
            diagnostic.start(); self.patches.append(diagnostic)

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.temp.cleanup()

    def put(self, name, content="fixture"):
        path = self.home / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def audit(self, **options):
        self.options.update(options)
        result = w.audit(self.plan_path, self.options, self.home)
        self.assertFalse(result["source_modified"])
        return w.load_json(self.plan_path)

    def apply(self):
        with patch.object(w, "terminal_confirm") as confirmation:
            result = w.apply(self.plan_path, self.home)
        confirmation.assert_called_once()
        return result, w.load_json(Path(result["receipt"]))

    def test_audit_exact_cache_scope_no_recovery_and_no_secret_output(self):
        cache = self.put(".claude/cache/data")
        desktop = self.put("AppData/Roaming/Claude/Local Storage/data", "private-storage")
        kept = self.put(".claude/projects/session.jsonl", "private-session")
        self.put(".claude/.credentials.json", '{"claudeAiOauth":{"accessToken":"fixture-secret"}}')
        result = w.audit(None, self.options, self.home)
        self.assertEqual([e["path"] for e in result["targets"]], [str(cache.parent)])
        self.assertIsNone(result["plan"])
        self.assertTrue(desktop.exists()); self.assertTrue(kept.exists())
        self.assertFalse((self.home / ".claude-cleanup-recovery").exists())
        self.assertNotIn("fixture-secret", json.dumps(result))

    def test_desktop_and_msix_storage_selected_but_mcp_sessions_and_other_packages_kept(self):
        prefix = "AppData/Local/Packages/Claude_pzs8sxrjxfjjc/LocalCache/Roaming/Claude/"
        storage = self.put(prefix + "Network/Cookies")
        kept = [self.put(prefix + name, "keep") for name in ["claude_desktop_config.json", "local-agent-mode-sessions/s",
                "claude-code-sessions/s", "vm_bundles/vhd", "unknownFutureStorage/data"]]
        other = self.put("AppData/Local/Packages/OtherClaude_xyz/LocalCache/Roaming/Claude/Network/Cookies", "other")
        with patch.object(w, "packages", return_value=["Claude_pzs8sxrjxfjjc"]):
            plan = self.audit(desktop=True)
            self.assertIn(str(storage.parent), [e["path"] for e in plan["targets"]])
            result, receipt = self.apply()
        self.assertFalse(storage.exists())
        self.assertTrue(all(p.read_text() == "keep" for p in kept)); self.assertEqual(other.read_text(), "other")
        self.assertEqual(receipt["status"], "complete")
        self.assertEqual((Path(result["quarantine"]) / "001-Network/Cookies").read_text(), "fixture")

    def test_reset_account_and_oauth_preserve_ids_unknown_fields_and_other_credentials(self):
        account = {"oauthAccount": {"token": "fixture-secret"}, "userID": "keep-id", "machineID": "keep-machine",
                   "projects": {"p": 1}, "unknown": {"keep": True}}
        credentials = {"claudeAiOauth": {"accessToken": "fixture-secret"}, "otherProvider": {"key": "keep-key"}}
        self.put(".claude.json", json.dumps(account))
        self.put(".claude/backups/.claude.json.backup.1", json.dumps(account))
        auth = self.put(".claude/.credentials.json", json.dumps(credentials))
        session = self.put(".claude/sessions/s.jsonl", "keep-session")
        mcp = self.put(".claude/settings.json", '{"mcpServers":{"keep":true}}')
        self.audit(reset_account=True, credentials=True)
        result, receipt = self.apply()
        expected = {k: v for k, v in account.items() if k != "oauthAccount"}
        self.assertEqual(w.load_json(self.home / ".claude.json"), expected)
        self.assertEqual(w.load_json(self.home / ".claude/backups/.claude.json.backup.1"), expected)
        self.assertEqual(w.load_json(auth), {"otherProvider": credentials["otherProvider"]})
        self.assertEqual(session.read_text(), "keep-session")
        self.assertEqual(w.load_json(mcp), {"mcpServers": {"keep": True}})
        self.assertEqual(len(receipt["rewritten"]), 3)
        self.assertEqual(w.load_json(Path(result["recovery"]) / "dot-claude/.credentials.json"), credentials)

    def test_backup_failure_changes_no_originals_and_records_partial_receipt(self):
        cache = self.put(".claude/cache/data", "keep-until-backup")
        self.audit()
        with patch.object(w, "terminal_confirm"), patch.object(w.shutil, "copytree", side_effect=OSError("fixture-secret")), \
                contextlib.redirect_stdout(io.StringIO()) as capture, self.assertRaises(w.Stop):
            w.apply(self.plan_path, self.home)
        self.assertEqual(cache.read_text(), "keep-until-backup")
        receipt = w.load_json(self.root / "plan.receipt.json")
        self.assertEqual(receipt["status"], "partial")
        self.assertEqual(receipt["moved"], [])
        self.assertNotIn("fixture-secret", capture.getvalue())

    def test_move_failure_after_one_move_records_recoverable_destinations(self):
        first = self.put(".claude/cache/data", "cache")
        second = self.put(".claude/stats-cache.json", "statistics")
        self.audit()
        real_move = w.shutil.move
        count = []
        def move(source, destination):
            count.append(source)
            if len(count) == 2:
                raise OSError("fixture-secret")
            return real_move(source, destination)
        with patch.object(w, "terminal_confirm"), patch.object(w.shutil, "move", side_effect=move), \
                contextlib.redirect_stdout(io.StringIO()), self.assertRaises(w.Stop):
            w.apply(self.plan_path, self.home)
        receipt = w.load_json(self.root / "plan.receipt.json")
        self.assertEqual(receipt["status"], "partial")
        self.assertTrue(receipt["moved"][0]["content_verified"])
        self.assertFalse(receipt["moved"][1]["move_returned"])
        self.assertEqual((Path(receipt["moved"][0]["destination"]) / "data").read_text(), "cache")
        self.assertFalse(first.exists()); self.assertEqual(second.read_text(), "statistics")

    def test_tampered_plan_and_changed_credentials_refuse_without_writes(self):
        auth = self.put(".claude/.credentials.json", '{"claudeAiOauth":{}}')
        plan = self.audit(credentials=True)
        auth.write_text('{"claudeAiOauth":{"accessToken":"changed"}}')
        with patch.object(w, "terminal_confirm") as confirm, self.assertRaises(w.Stop):
            w.apply(self.plan_path, self.home)
        confirm.assert_not_called()
        self.assertFalse((self.home / ".claude-cleanup-recovery").exists())
        plan["options"]["desktop"] = True
        with self.assertRaises(w.Stop): w.validate_plan(plan, self.home)

    def test_wrong_home_platform_options_or_appdata_refuse(self):
        plan = self.audit()
        for changes in [{"platform": "darwin"}, {"home": str(self.root)}, {"schema": True}]:
            invalid = {**plan, **changes}; invalid["plan_id"] = w.plan_digest(invalid)
            with self.assertRaises(w.Stop): w.validate_plan(invalid, self.home)
        with self.assertRaises(w.Stop): w.discover(self.home, {"uninstall": True}, plan["context"])
        with patch.dict(os.environ, {"APPDATA": str(self.root / "outside")}):
            with self.assertRaises(w.Stop): w.layout(self.home)
        with patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(self.root / "custom")}):
            with self.assertRaises(w.Stop): w.layout(self.home)

    def test_new_target_and_new_msix_identity_refuse(self):
        self.audit()
        new = self.put("AppData/Roaming/Claude/Cache/new-data")
        with self.assertRaises(w.Stop): w.apply(self.plan_path, self.home)
        self.assertTrue(new.exists())
        new.unlink(); new.parent.rmdir()
        with patch.object(w, "packages", return_value=["Claude_pzs8sxrjxfjjc"]), self.assertRaises(w.Stop):
            w.apply(self.plan_path, self.home)

    def test_running_processes_and_non_tty_refuse(self):
        cache = self.put(".claude/cache/data")
        self.audit()
        with patch.object(w, "processes", return_value=[{"pid": 1, "role": "Claude"}]), self.assertRaises(w.Stop):
            w.apply(self.plan_path, self.home)
        with patch.object(w.sys.stdin, "isatty", return_value=False), self.assertRaises(w.Stop):
            w.apply(self.plan_path, self.home)
        self.assertTrue(cache.exists()); self.assertFalse((self.home / ".claude-cleanup-recovery").exists())

    def test_purge_only_own_marked_batch_preserves_unrelated_recovery_and_windows_trash(self):
        self.put(".claude/cache/data", "old-cache")
        unrelated = self.put(".claude-cleanup-quarantine/unrelated/data", "keep")
        trash = self.put("$Recycle.Bin/unrelated", "keep-trash")
        self.audit(); result, receipt = self.apply()
        receipt_path = Path(result["receipt"])
        bad = {**receipt, "quarantine": str(self.home / ".claude-cleanup-quarantine")}
        with self.assertRaises(w.Stop): w.validate_receipt(bad, self.home)
        with patch.object(w, "terminal_confirm") as confirm:
            purged = w.purge(receipt_path, self.home)
        confirm.assert_called_once(); self.assertFalse(purged["recoverable"])
        self.assertFalse(Path(result["recovery"]).exists()); self.assertFalse(Path(result["quarantine"]).exists())
        self.assertEqual(unrelated.read_text(), "keep"); self.assertEqual(trash.read_text(), "keep-trash")
        with self.assertRaises(w.Stop): w.purge(receipt_path, self.home)

    def test_marker_tampering_blocks_purge(self):
        self.put(".claude/cache/data"); self.audit(); result, receipt = self.apply()
        w.atomic_json(Path(result["quarantine"]) / w.MARKER, {"tampered": True})
        with self.assertRaises(w.Stop): w.purge(Path(result["receipt"]), self.home)
        self.assertTrue(Path(result["recovery"]).exists())

    def test_process_metadata_sanitization_and_denied_visibility(self):
        rows = [{"ProcessId": 333, "Name": "node.exe", "CommandLine": r'node C:\node_modules\@anthropic-ai\claude-code\cli.js --token fixture-secret'},
                {"ProcessId": 334, "Name": "Chrome.exe", "CommandLine": "chrome"},
                {"ProcessId": 335, "Name": "Claude.exe", "CommandLine": "claude --token fixture-secret"},
                {"ProcessId": 336, "Name": "wslservice.exe", "CommandLine": None}]
        with patch.object(w, "powershell", return_value=json.dumps(rows)):
            found = REAL_PROCESSES()
        self.assertEqual([r["pid"] for r in found], [333, 335])
        self.assertNotIn("fixture-secret", json.dumps(found))
        for data in [[], [{"ProcessId": 2, "Name": "node.exe", "CommandLine": None}]]:
            with patch.object(w, "powershell", return_value=json.dumps(data)), self.assertRaises(w.Stop):
                REAL_PROCESSES()

    def test_msix_identity_exact_allowlist(self):
        known = {"Name": "Claude", "Publisher": "CN=Anthropic, PBC", "PackageFamilyName": "Claude_pzs8sxrjxfjjc"}
        with patch.object(w, "powershell", return_value=json.dumps([known])):
            self.assertEqual(REAL_PACKAGES(), ["Claude_pzs8sxrjxfjjc"])
        with patch.object(w, "powershell", return_value=json.dumps([{**known, "Publisher": 'CN="Anthropic, PBC"'}])):
            self.assertEqual(REAL_PACKAGES(), ["Claude_pzs8sxrjxfjjc"])
        for bad in [{**known, "Name": "UnrelatedClaude"}, {**known, "Publisher": "CN=Other"},
                    {**known, "PackageFamilyName": "Claude_unknown"}]:
            with patch.object(w, "powershell", return_value=json.dumps([bad])), self.assertRaises(w.Stop): REAL_PACKAGES()

    def test_reparse_target_and_parent_are_refused(self):
        path = self.put(".claude/cache/data")
        original = w.is_reparse
        cache_info = path.parent.lstat()
        def reparse(info):
            return info.st_ino == cache_info.st_ino or original(info)
        with patch.object(w, "is_reparse", side_effect=reparse), self.assertRaises(w.Stop): self.audit()

    @unittest.skipUnless(os.name == "nt", "actual NTFS junction test runs on Windows CI")
    def test_native_windows_junction_and_private_acl(self):
        outside = self.root / "outside"; outside.mkdir(); (outside / "data").write_text("keep")
        cli = self.home / ".claude"; cli.mkdir()
        junction = cli / "cache"
        result = subprocess.run(["cmd", "/c", "mklink", "/J", str(junction), str(outside)], capture_output=True)
        self.assertEqual(result.returncode, 0)
        try:
            with self.assertRaises(w.Stop): self.audit()
        finally:
            junction.rmdir()
        self.assertEqual((outside / "data").read_text(), "keep")
        private = self.root / "private"
        w.private_directory(private)
        output = w.powershell("$a=Get-Acl -LiteralPath $env:CC_PRIVATE; "
                             "@{Protected=$a.AreAccessRulesProtected; Count=@($a.Access).Count}|ConvertTo-Json -Compress",
                             {"CC_PRIVATE": str(private)})
        self.assertEqual(json.loads(output), {"Protected": True, "Count": 2})

    def test_entrypoint_dispatches_without_running_macos_operations(self):
        with patch.object(w, "main", return_value=17) as call:
            self.assertEqual(entrypoint.main(["audit"]), 17)
        call.assert_called_once_with(["audit"])

    def test_unknown_oauth_shape_refuses_and_powershell_errors_withhold_secrets(self):
        self.put(".claude/.credentials.json", '{"claudeAiOauth":"unknown-encrypted-shape"}')
        with self.assertRaises(w.Stop): self.audit(credentials=True)
        failed = subprocess.CompletedProcess([], 1, stdout="fixture-secret", stderr="fixture-secret")
        with patch.object(w.subprocess, "run", return_value=failed), self.assertRaises(w.Stop) as raised:
            w.powershell("fixture")
        self.assertNotIn("fixture-secret", str(raised.exception))

    def test_powershell_uses_its_own_system_modules_without_changing_parent_environment(self):
        success = subprocess.CompletedProcess([], 0, stdout="fixture", stderr="")
        with patch.dict(os.environ, {"PSModulePath": "unrelated-pwsh7-modules"}), \
                patch.object(w.subprocess, "run", return_value=success) as run:
            self.assertEqual(w.powershell("fixture"), "fixture")
            self.assertEqual(os.environ["PSModulePath"], "unrelated-pwsh7-modules")
        command = run.call_args.args[0]
        child = run.call_args.kwargs["env"]
        self.assertEqual(child["PSModulePath"], str(Path(command[0]).parent / "Modules"))

    @unittest.skipUnless(os.name == "nt", "native Windows PowerShell modules exercised on Windows CI")
    def test_native_windows_cim_and_appx_modules(self):
        # Native read-only queries on the disposable runner; no real home writes.
        count = int(w.powershell("@(Get-CimInstance Win32_Process).Count"))
        self.assertGreater(count, 0)
        self.assertIsInstance(REAL_PACKAGES(), list)


if __name__ == "__main__":
    unittest.main(verbosity=2)
