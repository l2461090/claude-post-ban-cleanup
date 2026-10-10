#!/usr/bin/env python3
"""Native Windows Claude cleanup, with reviewed plans and recoverable moves.

Uses Python standard library and Windows PowerShell. No browser database writes,
registry edits, package removal, process termination or credential-manager scans.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile
import uuid

from local_cleanup import ACCOUNT_FIELDS, Stop, canonical, emit, plan_digest, terminal_confirm

SCHEMA = 1
OPTIONS = {"desktop", "reset_account", "credentials"}
MARKER = ".claude-windows-cleanup-marker.json"
BATCH = re.compile(r"claude-windows-cleanup-\d{8}T\d{6}Z-[0-9a-f]{32}\Z")
CLI_CACHES = ("cache", "stats-cache.json", "telemetry", "usage-data", "usage.jsonl", "usage.with-fix.jsonl")
DESKTOP_CACHES = ("Cache", "Code Cache", "GPUCache", "DawnGraphiteCache", "DawnWebGPUCache", "logs", "Crashpad")
DESKTOP_STORAGE = ("Network", "Cookies", "Cookies-journal", "Local Storage", "Session Storage",
                   "IndexedDB", "Service Worker", "WebStorage")
AUTH_KEY = "claudeAiOauth"


def require_windows() -> None:
    if sys.platform != "win32":
        raise Stop("This backend supports native Windows only. Use local_cleanup.py on macOS.")


def exists(path: Path) -> bool:
    return os.path.lexists(path)


def is_reparse(info) -> bool:
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)


def safe_path(path: Path) -> None:
    """Reject symlinks, junctions, cloud reparse points and traversal components."""
    if not path.is_absolute() or ".." in path.parts:
        raise Stop("An absolute path without '..' is required.")
    for component in (path, *path.parents):
        if exists(component) and is_reparse(component.lstat()):
            raise Stop(f"Reparse point / symlink refused: {component}")


def entries(root: Path, *, hashes: bool = True) -> list[dict]:
    safe_path(root)
    if not exists(root):
        return []
    result = []

    def visit(path: Path, relative: str) -> None:
        safe_path(path)
        info = path.lstat()
        record = {"path": relative, "mode": stat.S_IMODE(info.st_mode)}
        if stat.S_ISDIR(info.st_mode):
            record["kind"] = "directory"
        elif stat.S_ISREG(info.st_mode):
            record.update(kind="file", size=info.st_size)
            if hashes:
                digest = hashlib.sha256()
                with path.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        digest.update(chunk)
                record["sha256"] = digest.hexdigest()
            else:
                record["mtime_ns"] = info.st_mtime_ns
        else:
            raise Stop(f"Special file refused: {path}")
        result.append(record)
        if record["kind"] == "directory":
            for child in sorted(path.iterdir(), key=lambda p: p.name):
                visit(child, child.name if relative == "." else relative + "/" + child.name)

    visit(root, ".")
    return result


def fingerprint(path: Path) -> dict:
    tree = entries(path)
    return {"path": str(path), "kind": tree[0]["kind"],
            "files": sum(e["kind"] == "file" for e in tree),
            "bytes": sum(e.get("size", 0) for e in tree),
            "content_sha256": hashlib.sha256(canonical(tree)).hexdigest()}


def powershell(script: str, path_env: dict | None = None) -> str:
    # Use the system binary, never a PowerShell executable found on user PATH.
    executable = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    env = os.environ.copy()
    env.update(path_env or {})
    # A caller launched from PowerShell 7 can export its module search path.
    # Load only this Windows PowerShell's built-in modules, avoiding both a
    # cross-version autoload failure and user module shadowing. Child only.
    env["PSModulePath"] = str(executable.parent / "Modules")
    command = "$ErrorActionPreference='Stop'; [Console]::OutputEncoding=[Text.UTF8Encoding]::new(); " + script
    try:
        result = subprocess.run([str(executable), "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", command],
                                capture_output=True, encoding="utf-8", env=env, timeout=45)
    except (OSError, subprocess.SubprocessError):
        raise Stop("Windows PowerShell unavailable or timed out; private outputs withheld.") from None
    if result.returncode:
        raise Stop("Windows inspection / ACL operation denied or failed; private outputs withheld.")
    return result.stdout.strip().lstrip("\ufeff")


def processes() -> list[dict]:
    # Command lines stay inside this local process and are never emitted.
    raw = powershell("$p=@(Get-CimInstance Win32_Process | Select-Object ProcessId,Name,CommandLine); "
                     "ConvertTo-Json -InputObject $p -Compress -Depth 3")
    rows = json.loads(raw)
    if not isinstance(rows, list) or not rows:
        raise Stop("Process visibility failed; cleanup is blocked.")
    found = []
    for row in rows:
        name = str(row.get("Name", "")).lower()
        args = row.get("CommandLine")
        if not isinstance(row.get("ProcessId"), int) or not name:
            raise Stop("Unexpected process metadata; cleanup is blocked.")
        if row["ProcessId"] == os.getpid():
            continue
        if name in {"wsl.exe", "wslhost.exe"}:
            role = "WSL active; native Windows cleanup cannot verify Linux sessions"
        elif name in {"claude.exe", "claude-code.exe", "claude-desktop.exe", "claude desktop.exe",
                       "claude-native-host.exe", "claude-helper.exe", "claude helper.exe"}:
            role = "Claude Desktop / CLI / helper"
        elif name == "chrome-native-host.exe" and isinstance(args, str) and re.search(
                r'[\\/](?:Claude|AnthropicClaude|Claude_[^\\/]+)[\\/]', args, re.I):
            role = "Claude native helper"
        elif isinstance(args, str) and ("@anthropic-ai/claude-code/" in args.replace("\\", "/").lower()
                or re.search(r'(?:^|[\\/\s"])claude(?:-code)?(?:\.exe)?(?:\s|"|$)', args, re.I)):
            role = "Claude CLI / native helper"
        elif name in {"node.exe", "bun.exe", "chrome-native-host.exe"} and args is None:
            raise Stop("A possible CLI / helper command line is inaccessible; cleanup is blocked.")
        else:
            continue
        found.append({"pid": row["ProcessId"], "role": role})
    return found


def packages() -> list[str]:
    raw = powershell("$p=@(Get-AppxPackage -Name Claude | Select-Object Name,Publisher,PackageFamilyName); "
                     "ConvertTo-Json -InputObject $p -Compress -Depth 3")
    rows = json.loads(raw)
    if not isinstance(rows, list):
        raise Stop("Unexpected MSIX package metadata.")
    names = []
    for row in rows:
        family = row.get("PackageFamilyName", "")
        # Known official family. Never clean arbitrary *Claude* packages.
        if (row.get("Name") != "Claude" or family != "Claude_pzs8sxrjxfjjc"
                or not re.search(r"\bAnthropic\b", str(row.get("Publisher", "")), re.I)):
            raise Stop("Unrecognized Claude package identity; inspect it before cleaning.")
        names.append(family)
    return sorted(set(names))


def layout(home: Path) -> dict:
    safe_path(home)
    if home.drive.startswith("\\\\"):
        raise Stop("Network / extended-path user profiles need a separate reviewed plan.")
    config = os.environ.get("CLAUDE_CONFIG_DIR")
    if config and Path(config).absolute() != home / ".claude":
        raise Stop("Custom CLAUDE_CONFIG_DIR needs a separate reviewed plan; default paths were not used.")
    roots = {"roaming": Path(os.environ.get("APPDATA", str(home / "AppData/Roaming"))),
             "local": Path(os.environ.get("LOCALAPPDATA", str(home / "AppData/Local")))}
    for root in roots.values():
        safe_path(root)
        if root == home or home not in root.parents:
            raise Stop("Redirected / external AppData is outside this backend's supported user scope.")
    roots["package_families"] = packages()
    return {key: str(value) if isinstance(value, Path) else value for key, value in roots.items()}


def desktop_roots(context: dict) -> list[Path]:
    roots = [Path(context["roaming"]) / "Claude"]
    for family in context["package_families"]:
        package = Path(context["local"]) / "Packages" / family
        roots.extend([package / "LocalCache/Roaming/Claude", package / "LocalCache/Local/Claude"])
    return roots


def discover(home: Path, options: dict, context: dict) -> tuple[list[dict], list[dict]]:
    if set(options) != OPTIONS or any(type(v) is not bool for v in options.values()):
        raise Stop("Unknown or missing Windows options.")
    candidates = [home / ".claude" / name for name in CLI_CACHES]
    for root in desktop_roots(context):
        safe_path(root)
        candidates.extend(root / name for name in DESKTOP_CACHES)
        if options["desktop"]:
            candidates.extend(root / name for name in DESKTOP_STORAGE)
    targets = [fingerprint(path) for path in sorted(set(candidates), key=str) if exists(path)]
    configs = []
    paths = []
    if options["reset_account"]:
        paths.append((home / ".claude.json", "account"))
        backups = home / ".claude/backups"
        safe_path(backups)
        if backups.is_dir():
            paths.extend((p, "account") for p in sorted(backups.glob(".claude.json.backup.*")))
    if options["credentials"]:
        paths.append((home / ".claude/.credentials.json", "oauth"))
    for path, kind in paths:
        if not exists(path):
            continue
        data = load_json(path)
        if kind == "oauth" and AUTH_KEY in data and not isinstance(data[AUTH_KEY], dict):
            raise Stop("Unrecognized OAuth credential shape; no credential values were emitted.")
        configs.append({**fingerprint(path), "operation": kind})
    return targets, configs


def metadata_path(path: Path, home: Path, context: dict) -> None:
    safe_path(path)
    forbidden = [home / ".claude", home / ".claude.json", home / ".claude-cleanup-recovery",
                 home / ".claude-cleanup-quarantine", *desktop_roots(context)]
    if any(path == root or root in path.parents for root in forbidden):
        raise Stop("Plan / receipt must be outside source and recovery locations.")


def load_json(path: Path) -> dict:
    safe_path(path)
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise Stop("Expected a JSON object; contents withheld.")
    return value


def copy_acl(source: Path, destination: Path) -> None:
    if os.name == "nt":
        powershell("$a=Get-Acl -LiteralPath $env:CC_SOURCE; Set-Acl -LiteralPath $env:CC_DESTINATION -AclObject $a; "
                   "$b=Get-Acl -LiteralPath $env:CC_DESTINATION; "
                   "$section=[Security.AccessControl.AccessControlSections]::Access; "
                   "if ($a.GetSecurityDescriptorSddlForm($section) -ne $b.GetSecurityDescriptorSddlForm($section)) "
                   "{throw 'File ACL preservation failed'}",
                   {"CC_SOURCE": str(source), "CC_DESTINATION": str(destination)})
    else:
        os.chmod(destination, stat.S_IMODE(source.stat().st_mode))


def atomic_json(path: Path, value: dict, *, new: bool = False) -> None:
    safe_path(path)
    if new and exists(path):
        raise Stop("Output already exists; select a new plan / receipt path.")
    fd, temporary = tempfile.mkstemp(prefix=".claude-cleanup-", dir=path.parent)
    temp = Path(temporary)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            # Protect the temporary file before writing any credential fields.
            if exists(path):
                copy_acl(path, temp)
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        if new and exists(path):
            raise Stop("Output appeared during execution.")
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def private_directory(path: Path) -> None:
    safe_path(path)
    path.mkdir(mode=0o700)  # exclusive creation; do not inherit an old batch
    if os.name != "nt":
        os.chmod(path, 0o700)
        return
    powershell("$sid=[Security.Principal.WindowsIdentity]::GetCurrent().User.Value; "
               "$acl=New-Object Security.AccessControl.DirectorySecurity; "
               "$acl.SetSecurityDescriptorSddlForm(('D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;'+$sid+')')); "
               "Set-Acl -LiteralPath $env:CC_PRIVATE -AclObject $acl; "
               "$check=Get-Acl -LiteralPath $env:CC_PRIVATE; "
               "$rules=@($check.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier])); "
               "if (!$check.AreAccessRulesProtected -or $rules.Count -ne 2) {throw 'ACL mismatch'}; "
               "foreach($r in $rules) {if ($r.IdentityReference.Value -notin @($sid,'S-1-5-18') "
               "-or $r.AccessControlType -ne 'Allow' -or $r.FileSystemRights -ne 'FullControl') {throw 'ACL mismatch'}}",
               {"CC_PRIVATE": str(path)})


def audit(plan_path: Path | None, options: dict, home: Path) -> dict:
    require_windows()
    context = layout(home)
    if plan_path:
        metadata_path(plan_path, home, context)
    targets, configs = discover(home, options, context)
    running = processes()
    plan = {"schema": SCHEMA, "platform": "win32", "nonce": uuid.uuid4().hex, "home": str(home),
            "context": context, "options": options, "targets": targets, "configs": configs}
    plan["plan_id"] = plan_digest(plan)
    if plan_path:
        atomic_json(plan_path, plan, new=True)
    return {"status": "audit", "platform": "win32", "plan": str(plan_path) if plan_path else None,
            "plan_id": plan["plan_id"] if plan_path else None, "targets": targets,
            "config_files": [{"path": c["path"], "operation": c["operation"]} for c in configs],
            "desktop_roots": [str(p) for p in desktop_roots(context)],
            "options": options, "running_processes": running, "apply_blocked": bool(running),
            "source_modified": False, "credential_manager": "not scanned or modified",
            "retained": "Desktop MCP configs, sessions, attachments, VMs, unknown files and other app data"}


def validate_plan(plan: dict, home: Path) -> None:
    fields = {"schema", "platform", "nonce", "home", "context", "options", "targets", "configs", "plan_id"}
    if (set(plan) != fields or type(plan["schema"]) is not int or plan["schema"] != SCHEMA
            or plan["platform"] != "win32" or plan["home"] != str(home)
            or not re.fullmatch(r"[0-9a-f]{32}", str(plan["nonce"]))
            or not re.fullmatch(r"[0-9a-f]{64}", str(plan["plan_id"]))):
        raise Stop("Windows plan fields, platform, home or version mismatch.")
    if not secrets.compare_digest(plan["plan_id"], plan_digest(plan)):
        raise Stop("Plan no longer matches its confirmation ID; audit and confirm again.")
    context = layout(home)
    if context != plan["context"]:
        raise Stop("AppData / MSIX package identity changed; audit and confirm again.")
    targets, configs = discover(home, plan["options"], context)
    if targets != plan["targets"] or configs != plan["configs"]:
        raise Stop("Selected files changed since audit; audit and confirm again.")


def protected_snapshot(home: Path, plan: dict) -> list[dict]:
    excluded = [Path(e["path"]) for e in plan["targets"] + plan["configs"]]
    snapshot = []
    for root in [home / ".claude", *desktop_roots(plan["context"])]:
        for e in entries(root):
            path = root if e["path"] == "." else root / e["path"]
            if e["kind"] != "file" or any(path == p or p in path.parents for p in excluded):
                continue
            snapshot.append({"root": str(root), **e})
    return snapshot


def parent_directory(path: Path) -> None:
    safe_path(path)
    if not exists(path):
        path.mkdir(mode=0o700)
    if not path.is_dir():
        raise Stop("Recovery parent is not a directory.")


def apply(plan_path: Path, home: Path) -> dict:
    require_windows()
    plan = load_json(plan_path)
    validate_plan(plan, home)
    metadata_path(plan_path, home, plan["context"])
    receipt_path = plan_path.with_name(plan_path.stem + ".receipt.json")
    metadata_path(receipt_path, home, plan["context"])
    if exists(receipt_path):
        raise Stop("Receipt already exists; do not replay an old plan.")
    if processes():
        raise Stop("Claude / WSL is running; close it normally before cleanup.")
    terminal_confirm("CONFIRM " + plan["plan_id"], {
        "action": "apply_windows", "targets_moved_to_quarantine": plan["targets"], "configs": plan["configs"],
        "risks": ["Desktop website storage removal signs out the app and removes local offline site data.",
                  "Desktop MCP configs, Cowork / Code sessions, attachments and VM directories remain.",
                  "Only known account fields and the selected claudeAiOauth object are removed; IDs and unknown keys remain.",
                  "Private backups and quarantine retain old credentials; separate confirmation is required to purge.",
                  "Quarantine is a dedicated recovery directory, not the Windows Recycle Bin.",
                  "No credential-manager, registry, browser, network or system identity changes are performed."]})
    validate_plan(plan, home)
    if processes():
        raise Stop("A Claude / WSL process started during confirmation.")
    protected = protected_snapshot(home, plan)
    batch = "claude-windows-cleanup-" + dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex
    recovery = home / ".claude-cleanup-recovery" / batch
    quarantine = home / ".claude-cleanup-quarantine" / batch
    receipt = {"schema": SCHEMA, "platform": "win32", "home": str(home), "batch_id": batch,
               "nonce": secrets.token_hex(32), "plan_id": plan["plan_id"], "status": "partial",
               "recovery": str(recovery), "quarantine": str(quarantine), "recoverable": True,
               "backups": [], "rewritten": [], "moved": []}
    try:
        atomic_json(receipt_path, receipt, new=True)
        for root, kind in [(recovery, "recovery"), (quarantine, "quarantine")]:
            parent_directory(root.parent)
            private_directory(root)
            atomic_json(root / MARKER, {"schema": SCHEMA, "batch_id": batch, "home": str(home),
                                       "kind": kind, "nonce": receipt["nonce"]}, new=True)
        for source, destination in [(home / ".claude", recovery / "dot-claude"),
                                    (home / ".claude.json", recovery / "claude.json")]:
            if not exists(source):
                continue
            before = entries(source)
            if source.is_dir():
                shutil.copytree(source, destination)
            else:
                shutil.copy2(source, destination)
            if entries(source) != before or entries(destination) != before:
                raise Stop("Backup verification failed; original files were not changed.")
            receipt["backups"].append({"source": str(source), "destination": str(destination), "content_verified": True})
            atomic_json(receipt_path, receipt)
        validate_plan(plan, home)
        if processes():
            raise Stop("Claude / WSL started during backup; original writes stopped.")
        for e in plan["configs"]:
            path = Path(e["path"])
            if fingerprint(path) != {key: value for key, value in e.items() if key != "operation"}:
                raise Stop("Configuration changed during execution.")
            original = load_json(path)
            keys = ACCOUNT_FIELDS if e["operation"] == "account" else {AUTH_KEY}
            updated = {k: v for k, v in original.items() if k not in keys}
            if updated == original:
                continue
            atomic_json(path, updated)
            receipt["rewritten"].append(str(path))
            atomic_json(receipt_path, receipt)
            if load_json(path) != updated:
                raise Stop("Configuration verification failed.")
        for index, e in enumerate(plan["targets"], 1):
            source = Path(e["path"])
            if fingerprint(source) != e:
                raise Stop("Target changed during execution.")
            before = entries(source)
            destination = quarantine / f"{index:03d}-{source.name}"
            record = {"source": str(source), "destination": str(destination), "move_returned": False,
                      "content_verified": False}
            receipt["moved"].append(record); atomic_json(receipt_path, receipt)
            shutil.move(str(source), str(destination))
            record["move_returned"] = True; atomic_json(receipt_path, receipt)
            # A same-volume move can retain an old ACL. Apply the batch's private
            # ACL recursively before reporting the relocated data as protected.
            if os.name == "nt":
                powershell("& (Join-Path $env:SystemRoot 'System32\\icacls.exe') $env:CC_MOVED /reset /T /Q; "
                           "if ($LASTEXITCODE -ne 0) {throw 'Moved-data ACL reset failed'}",
                           {"CC_MOVED": str(destination)})
            if exists(source) or entries(destination) != before:
                raise Stop("Move verification failed; use receipt mapping to recover.")
            record["content_verified"] = True; atomic_json(receipt_path, receipt)
        if any(exists(Path(e["path"])) for e in plan["targets"]) or protected_snapshot(home, plan) != protected:
            raise Stop("Target reappeared or protected data changed; inspect recovery materials.")
        receipt["status"] = "complete"; atomic_json(receipt_path, receipt)
        return {"status": "complete", "receipt": str(receipt_path), "recovery": str(recovery),
                "quarantine": str(quarantine), "moved_count": len(receipt["moved"]),
                "rewritten_count": len(receipt["rewritten"]), "recoverable": True, "purged": False}
    except (Exception, KeyboardInterrupt) as error:
        if exists(receipt_path):
            atomic_json(receipt_path, receipt)
        emit({"status": "partial", "receipt": str(receipt_path) if exists(receipt_path) else None,
              "recovery": str(recovery), "quarantine": str(quarantine),
              "message": str(error) if isinstance(error, Stop) else "Operation failed; private details withheld.",
              "remaining_actions_executed": False})
        raise Stop("Windows cleanup stopped; preserve recovery materials and do not replay this plan.") from None


def validate_receipt(receipt: dict, home: Path) -> list[Path]:
    fields = {"schema", "platform", "home", "batch_id", "nonce", "plan_id", "status", "recovery",
              "quarantine", "recoverable", "backups", "rewritten", "moved"}
    if (set(receipt) != fields or type(receipt["schema"]) is not int or receipt["schema"] != SCHEMA
            or receipt["platform"] != "win32" or receipt["home"] != str(home)
            or not BATCH.fullmatch(str(receipt["batch_id"]))
            or not re.fullmatch(r"[0-9a-f]{64}", str(receipt["nonce"]))
            or receipt["status"] == "purged" or receipt["recoverable"] is not True):
        raise Stop("Unrecognized / purged Windows receipt.")
    roots = []
    for kind, parent in [("recovery", ".claude-cleanup-recovery"), ("quarantine", ".claude-cleanup-quarantine")]:
        root = home / parent / receipt["batch_id"]
        if receipt[kind] != str(root):
            raise Stop("Arbitrary purge path refused.")
        safe_path(root)
        if exists(root):
            expected = {"schema": SCHEMA, "batch_id": receipt["batch_id"], "home": str(home),
                        "kind": kind, "nonce": receipt["nonce"]}
            if load_json(root / MARKER) != expected:
                raise Stop("Generated recovery marker mismatch.")
            entries(root, hashes=False)
        roots.append(root)
    return roots


def purge(receipt_path: Path, home: Path) -> dict:
    require_windows()
    receipt = load_json(receipt_path)
    roots = validate_receipt(receipt, home)
    if any(receipt_path == root or root in receipt_path.parents for root in roots):
        raise Stop("Receipt must remain outside the purged batch.")
    terminal_confirm("DELETE " + receipt["batch_id"], {"action": "purge_windows", "directories": list(map(str, roots)),
        "risks": ["These private backup / quarantine copies may contain old credentials and sessions.",
                  "Deletion is permanent. Other recovery batches and the Windows Recycle Bin are untouched."]})
    validate_receipt(receipt, home)
    try:
        for root in roots:
            if exists(root):
                shutil.rmtree(root)
        if any(exists(root) for root in roots):
            raise Stop("Purge verification failed.")
        receipt.update(status="purged", recoverable=False); atomic_json(receipt_path, receipt)
        return {"status": "purged", "receipt": str(receipt_path), "recoverable": False}
    except (OSError, KeyboardInterrupt):
        raise Stop("Purge stopped partway; inspect exact batch paths before retrying.") from None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    scan = sub.add_parser("audit", help="Read-only native Windows inventory")
    scan.add_argument("--plan", type=Path)
    scan.add_argument("--desktop", action="store_true", help="Include known Electron website / login storage")
    scan.add_argument("--reset-account", action="store_true", help="Remove known account-cache fields, preserving IDs")
    scan.add_argument("--credentials", action="store_true", help="Remove only claudeAiOauth from .credentials.json")
    apply_parser = sub.add_parser("apply", help="Apply a reviewed Windows plan after terminal confirmation")
    apply_parser.add_argument("--plan", type=Path, required=True)
    purge_parser = sub.add_parser("purge", help="Separately confirm permanent deletion of this recovery batch")
    purge_parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        home = Path.home().absolute()
        if args.command == "audit":
            result = audit(args.plan.absolute() if args.plan else None, {k: getattr(args, k) for k in OPTIONS}, home)
        elif args.command == "apply":
            result = apply(args.plan.absolute(), home)
        else:
            result = purge(args.receipt.absolute(), home)
        emit(result); return 0
    except Stop as error:
        emit({"status": "stopped", "message": str(error)}); return 2
    except (OSError, ValueError, subprocess.SubprocessError):
        emit({"status": "stopped", "message": "Operation failed; private contents withheld. No remaining actions executed."}); return 2
    except (KeyboardInterrupt, EOFError):
        emit({"status": "stopped", "message": "Cancelled; no remaining actions executed."}); return 2


if __name__ == "__main__":
    raise SystemExit(main())
