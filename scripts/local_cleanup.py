#!/usr/bin/env python3
"""Auditable macOS Claude cleanup; standard library only, no unattended writes.

audit writes only the requested metadata plan. apply requires a reviewed plan and
a human confirmation in a real terminal. Browser / CC Switch work is separate.
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

VERSION = 1
OPTION_KEYS = {"desktop", "reset_account", "keychain", "rotate_local_id", "uninstall"}
ACCOUNT_FIELDS = frozenset({
    "additionalModelCostsCache", "additionalModelOptionsCache", "anonymousId",
    "autoCompactWindowsCache", "cachedChromeExtensionInstalled", "cachedDynamicConfigs",
    "cachedExperimentData", "cachedExperimentFeatures", "cachedExtraUsageDisabledReason",
    "cachedGrowthBookFeatures", "cachedGrowthBookFeaturesAt", "cachedStatsigGates",
    "clientDataCache", "clientDataCacheSlots", "feedbackSurveyState", "groveConfigCache",
    "metricsStatusCache", "modelAccessCache", "oauthAccount", "orgModelDefaultCache",
    "passesEligibilityCache", "s1mAccessCache",
})
PROTECTED = frozenset({
    "CLAUDE.md", "agents", "backups", "commands", "debug", "file-history", "history.jsonl",
    "hooks", "mcp-servers", "plans", "plugins", "projects", "scripts", "session-env",
    "sessions", "settings.json", "settings.local.json", "skills", "tasks", "todos",
})
CACHE_PATHS = (
    ".claude/cache", ".claude/stats-cache.json", ".claude/telemetry", ".claude/usage-data",
    ".claude/usage.jsonl", ".claude/usage.with-fix.jsonl", "Library/Caches/claude-cli-nodejs",
    "Library/Caches/com.anthropic.claudefordesktop",
    "Library/Caches/com.anthropic.claudefordesktop.ShipIt", "Library/Logs/Claude",
)
DESKTOP_PATHS = (
    "Library/Application Support/Claude", "Library/Application Support/Claude-3p",
    "Library/Application Support/com.anthropic.claudefordesktop",
    "Library/HTTPStorages/com.anthropic.claudefordesktop",
    "Library/Preferences/com.anthropic.claudefordesktop.plist",
    "Library/Saved Application State/com.anthropic.claudefordesktop.savedState",
    "Library/WebKit/com.anthropic.claudefordesktop",
)
BYHOST_RE = re.compile(r"com\.anthropic\.claudefordesktop(?:\.ShipIt)?\.[0-9A-Fa-f-]{36}\.plist\Z")
DIAGNOSTIC_RE = re.compile(r"Claude[-_][0-9][A-Za-z0-9_.-]*\.(?:ips|crash|diag)\Z")
CRASH_REPORTER_RE = re.compile(r"Claude_[0-9A-Fa-f-]+(?:\.plist)?\Z")
BATCH_RE = re.compile(r"claude-local-cleanup-\d{8}T\d{6}Z-[0-9a-f]{32}\Z")
MARKER = ".claude-local-cleanup-marker.json"
SERVICE = "Claude Code-credentials"


class Stop(Exception):
    """A deliberate refusal, without revealing private contents."""


def emit(value: dict) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def plan_digest(plan: dict) -> str:
    """Bind the confirmation string to every reviewed field and fresh nonce."""
    return hashlib.sha256(canonical({key: value for key, value in plan.items() if key != "plan_id"})).hexdigest()


def exists(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def safe_path(path: Path) -> None:
    """Reject symlink components, including dangling links, before accessing a path."""
    if not path.is_absolute() or ".." in path.parts:
        raise Stop("An absolute path without '..' is required.")
    for component in (path, *path.parents):
        if component.is_symlink():
            raise Stop(f"Symlink path refused: {path}")


def load_json(path: Path) -> dict:
    safe_path(path)
    if not path.is_file():
        raise Stop(f"Required regular JSON file missing: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeError, ValueError):
        raise Stop(f"Invalid JSON file; contents withheld: {path}") from None
    if not isinstance(value, dict):
        raise Stop(f"JSON object required: {path}")
    return value


def atomic_json(path: Path, value: dict, *, overwrite: bool = True) -> None:
    safe_path(path)
    safe_path(path.parent)
    if not path.parent.is_dir():
        raise Stop(f"Output parent must already exist: {path.parent}")
    if not overwrite and exists(path):
        raise Stop(f"Output already exists; choose a new path: {path}")
    fd, temp_name = tempfile.mkstemp(prefix=".claude-cleanup-", dir=path.parent)
    temp = Path(temp_name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        if not overwrite and exists(path):
            raise Stop("Output appeared during execution; stopped.")
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def tree_entries(root: Path, *, hashes: bool, allow_links: bool = False) -> list[dict]:
    """lstat / scandir only; never recurse through symlinks."""
    safe_path(root)
    if not exists(root):
        return []
    output = []

    def visit(path: Path, relative: str) -> None:
        info = path.lstat()
        item = {"path": relative, "mode": stat.S_IMODE(info.st_mode)}
        if stat.S_ISLNK(info.st_mode):
            if not allow_links:
                raise Stop(f"Symlink inside selected path refused: {path}")
            item.update(kind="symlink", link=os.readlink(path))
        elif stat.S_ISDIR(info.st_mode):
            item.update(kind="directory")
        elif stat.S_ISREG(info.st_mode):
            item.update(kind="file", size=info.st_size)
            if hashes:
                digest = hashlib.sha256()
                # O_NOFOLLOW prevents a final-component symlink substitution.
                descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
                with os.fdopen(descriptor, "rb") as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        digest.update(chunk)
                item["sha256"] = digest.hexdigest()
            else:
                item["mtime_ns"] = info.st_mtime_ns
        else:
            raise Stop(f"Special file refused: {path}")
        output.append(item)
        if item["kind"] == "directory":
            with os.scandir(path) as iterator:
                children = sorted(iterator, key=lambda entry: entry.name)
            for child in children:
                child_relative = child.name if relative == "." else f"{relative}/{child.name}"
                visit(Path(child.path), child_relative)

    visit(root, ".")
    return output


def fingerprint(path: Path) -> dict:
    entries = tree_entries(path, hashes=False)
    return {
        "path": str(path), "kind": entries[0]["kind"],
        "files": sum(entry["kind"] == "file" for entry in entries),
        "bytes": sum(entry.get("size", 0) for entry in entries),
        "metadata_sha256": hashlib.sha256(canonical(entries)).hexdigest(),
    }


def validate_options(options: dict) -> None:
    if not isinstance(options, dict) or set(options) != OPTION_KEYS:
        raise Stop("Unknown or missing options in plan.")
    if any(type(value) is not bool for value in options.values()):
        raise Stop("Plan options must be booleans.")
    if options["rotate_local_id"] and not options["reset_account"]:
        raise Stop("--rotate-local-id requires --reset-account.")


def app_paths(home: Path) -> tuple[Path, Path]:
    return Path("/Applications/Claude.app"), home / "Applications/Claude.app"


def discover(home: Path, options: dict) -> tuple[list[dict], list[dict]]:
    validate_options(options)
    safe_path(home)
    candidates = [home / relative for relative in CACHE_PATHS]
    for relative, pattern in (("Library/Logs/DiagnosticReports", DIAGNOSTIC_RE),
                              ("Library/Application Support/CrashReporter", CRASH_REPORTER_RE)):
        parent = home / relative
        safe_path(parent)
        if parent.is_dir():
            candidates += [path for path in parent.iterdir() if pattern.fullmatch(path.name)]
    if options["desktop"]:
        candidates += [home / relative for relative in DESKTOP_PATHS]
        byhost = home / "Library/Preferences/ByHost"
        safe_path(byhost)
        if byhost.is_dir():
            candidates += [path for path in byhost.iterdir() if BYHOST_RE.fullmatch(path.name)]
    if options["uninstall"]:
        candidates += list(app_paths(home))
    selected = sorted(set(path for path in candidates if exists(path)), key=str)
    for path in selected:
        safe_path(path)
        claude = home / ".claude"
        if path == claude or any(path == claude / name or claude / name in path.parents for name in PROTECTED):
            raise Stop(f"Protected target refused: {path}")
    targets = [fingerprint(path) for path in selected]
    configs = []
    if options["reset_account"]:
        identity = home / ".claude.json"
        config_paths = [identity] if exists(identity) else []
        backups = home / ".claude/backups"
        safe_path(backups)
        if backups.is_dir():
            config_paths += sorted(backups.glob(".claude.json.backup.*"), key=str)
        if options["rotate_local_id"] and not exists(identity):
            raise Stop("Cannot rotate application IDs without ~/.claude.json.")
        for path in config_paths:
            load_json(path)
            entry = fingerprint(path)
            entry["content_sha256"] = tree_entries(path, hashes=True)[0]["sha256"]
            configs.append(entry)
    return targets, configs


def processes() -> list[dict]:
    """Inspect args privately; return only PID and role, never a command line."""
    output = {}
    for column in ("comm", "args"):
        result = subprocess.run(["/bin/ps", "-axo", f"pid=,{column}="], capture_output=True, text=True)
        if result.returncode != 0 or not result.stdout.strip():
            raise Stop("Cannot inspect processes; apply is blocked. Grant process visibility or use a regular terminal.")
        output[column] = {}
        for line in result.stdout.splitlines():
            fields = line.strip().split(maxsplit=1)
            if len(fields) == 2 and fields[0].isdigit():
                output[column][int(fields[0])] = fields[1]
    found = []
    for pid, comm in output["comm"].items():
        if pid == os.getpid():
            continue
        args = output["args"].get(pid, "")
        basename = Path(comm).name.lower()
        first = Path(args.split(maxsplit=1)[0]).name.lower() if args else ""
        if basename in {"claude", "claude-code"} or first in {"claude", "claude-code"}:
            role = "Claude CLI"
        elif "/Claude.app/" in args or "chrome-native-host" in comm and "Claude.app" in comm:
            role = "Claude Desktop / native helper"
        elif "@anthropic-ai/claude-code/" in args or re.search(r"(?:^|/)claude(?:\s|$)", args):
            role = "Claude CLI"
        else:
            continue
        found.append({"pid": pid, "role": role})
    return found


def keychain_present() -> bool:
    result = subprocess.run(["/usr/bin/security", "find-generic-password", "-s", SERVICE], capture_output=True)
    if result.returncode not in (0, 44):
        raise Stop("Keychain lookup denied or failed; no credential output is printed.")
    return result.returncode == 0


def require_macos() -> None:
    if sys.platform != "darwin":
        raise Stop("Unsupported platform: automated writes are macOS-only. Use references/client.md for read-only inventory / manual cleanup.")


def metadata_output_path(path: Path, home: Path) -> None:
    safe_path(path)
    forbidden = [home / ".claude", home / ".claude.json", home / ".claude-cleanup-recovery", home / ".Trash"]
    forbidden += [home / relative for relative in CACHE_PATHS + DESKTOP_PATHS]
    forbidden += list(app_paths(home))
    if any(path == root or root in path.parents for root in forbidden):
        raise Stop("Plan / receipt cannot be stored inside source, recovery, or cleanup targets.")


def audit(plan_path: Path | None, options: dict, home: Path) -> dict:
    if sys.platform != "darwin":
        return {"status": "unsupported_read_only", "platform": sys.platform, "plan_written": False,
                "reference": "references/client.md", "message": "No system modification was performed."}
    if plan_path is not None:
        metadata_output_path(plan_path, home)
    targets, configs = discover(home, options)
    running = processes()
    keychain = keychain_present() if options["keychain"] else None
    plan = {"schema": VERSION, "nonce": uuid.uuid4().hex, "home": str(home), "options": options,
            "targets": targets, "configs": configs, "keychain_present": keychain}
    plan["plan_id"] = plan_digest(plan)
    if plan_path is not None:
        atomic_json(plan_path, plan, overwrite=False)
    return {"status": "audit", "plan": str(plan_path) if plan_path is not None else None,
            "plan_written": plan_path is not None, "plan_id": plan["plan_id"] if plan_path is not None else None, "options": options,
            "targets": targets, "config_files": [entry["path"] for entry in configs],
            "keychain_present": keychain, "running_processes": running,
            "apply_blocked": bool(running), "source_modified": False}


def validate_plan(plan: dict, home: Path) -> None:
    if set(plan) != {"schema", "plan_id", "nonce", "home", "options", "targets", "configs", "keychain_present"}:
        raise Stop("Unrecognized plan fields.")
    if (type(plan["schema"]) is not int or plan["schema"] != VERSION or plan["home"] != str(home)
            or not re.fullmatch(r"[0-9a-f]{64}", str(plan["plan_id"]))
            or not re.fullmatch(r"[0-9a-f]{32}", str(plan["nonce"]))):
        raise Stop("Plan version, home, or ID mismatch.")
    if not secrets.compare_digest(plan["plan_id"], plan_digest(plan)):
        raise Stop("Plan contents no longer match its confirmation ID. Audit again and obtain confirmation for the new plan.")
    targets, configs = discover(home, plan["options"])
    if targets != plan["targets"] or configs != plan["configs"]:
        raise Stop("Selected files changed, appeared, or disappeared since audit. Run a new audit and obtain a new confirmation.")
    current_keychain = keychain_present() if plan["options"]["keychain"] else None
    if current_keychain != plan["keychain_present"]:
        raise Stop("Keychain existence changed since audit. Run a new audit.")


def terminal_confirm(expected: str, checklist: dict) -> None:
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise Stop("A real interactive terminal is required; piped input, --yes, and unattended confirmation are not supported.")
    emit(checklist)
    print(f"Human approval required. Enter exactly: {expected}")
    if input().strip() != expected:
        raise Stop("Cancelled; no cleanup writes performed.")


def backup_tree(source: Path, destination: Path) -> dict:
    """Full hash-verified copy. Symlinks are preserved as links, never followed."""
    if not exists(source):
        return {"source": str(source), "present": False}
    before = tree_entries(source, hashes=True, allow_links=True)
    if source.is_dir():
        shutil.copytree(source, destination, symlinks=True)
    else:
        shutil.copy2(source, destination, follow_symlinks=False)
    after_source = tree_entries(source, hashes=True, allow_links=True)
    after_copy = tree_entries(destination, hashes=True, allow_links=True)
    if before != after_source or before != after_copy:
        # File permissions are compared before tightening the private copy.
        raise Stop(f"Backup content / permissions verification failed: {source}")
    secure_tree(destination)
    return {"source": str(source), "present": True, "destination": str(destination), "entries": before,
            "content_verified": True}


def protected_snapshot(home: Path, options: dict) -> list[dict]:
    """Verify protected user data while allowing only reviewed identity backups."""
    claude = home / ".claude"
    output = []
    for entry in tree_entries(claude, hashes=True, allow_links=True):
        relative = entry["path"]
        if relative.split("/", 1)[0] not in PROTECTED:
            continue
        if options["reset_account"] and relative.startswith("backups/.claude.json.backup."):
            continue
        output.append(entry)
    return output


def secure_tree(root: Path) -> None:
    for entry in tree_entries(root, hashes=False, allow_links=True):
        path = root if entry["path"] == "." else root / entry["path"]
        if entry["kind"] == "directory":
            os.chmod(path, 0o700)
        elif entry["kind"] == "file":
            os.chmod(path, 0o600)


def ensure_private_parent(path: Path) -> None:
    safe_path(path)
    if not exists(path):
        path.mkdir(mode=0o700)
    if not path.is_dir():
        raise Stop(f"Expected directory: {path}")


def apply(plan_path: Path, home: Path) -> dict:
    require_macos()
    metadata_output_path(plan_path, home)
    plan = load_json(plan_path)
    validate_plan(plan, home)
    running = processes()
    if running:
        raise Stop("Claude CLI / Desktop / native helper is running. Exit them normally and repeat the audit; no processes are killed.")
    receipt_path = plan_path.with_name(plan_path.stem + ".receipt.json")
    metadata_output_path(receipt_path, home)
    if exists(receipt_path):
        raise Stop("Receipt file already exists; choose a new audit plan path.")
    terminal_confirm("CONFIRM " + plan["plan_id"], {
        "action": "apply", "targets_moved_to_trash": plan["targets"],
        "configuration_files_rewritten": [entry["path"] for entry in plan["configs"]],
        "options": plan["options"], "keychain_credential_deleted": plan["keychain_present"],
        "risks": ["Desktop data may include Cowork work, local attachments, and bundled VM data; --desktop removes this data.",
                  "Keychain credentials cannot be restored from the filesystem backup; --keychain signs out CLI authentication.",
                  "Account reset rewrites only known top-level fields in listed config files; projects, sessions, settings, and skills remain.",
                  "Local ID rotation affects only Claude application IDs; hardware, network, timezone, and telemetry are unchanged.",
                  "Moving files to Trash does not erase them; backup and Trash require separate confirmation to purge.",
                  "This does not reverse an account suspension or guarantee that login will be accepted."],
    })
    # Revalidate after the user has had time to read and respond.
    validate_plan(plan, home)
    if processes():
        raise Stop("A Claude process started during confirmation; stopped before writes.")
    protected_before = protected_snapshot(home, plan["options"])
    batch_id = "claude-local-cleanup-" + dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex
    recovery = home / ".claude-cleanup-recovery" / batch_id
    trash = home / ".Trash" / batch_id
    nonce = secrets.token_hex(32)
    receipt = {"schema": VERSION, "batch_id": batch_id, "home": str(home), "marker_nonce": nonce,
               "recovery": str(recovery), "trash": str(trash), "status": "partial", "recoverable": True,
               "backups": [], "moved": [], "rewritten": [], "keychain_deleted": False, "plan_id": plan["plan_id"]}
    try:
        # The first writes create the private, verifiable recovery batch.
        ensure_private_parent(recovery.parent)
        recovery.mkdir(mode=0o700)
        atomic_json(recovery / MARKER, {"schema": VERSION, "batch_id": batch_id, "home": str(home), "kind": "recovery", "nonce": nonce})
        atomic_json(receipt_path, receipt, overwrite=False)
        for source, destination in ((home / ".claude", recovery / "dot-claude"),
                                    (home / ".claude.json", recovery / "claude.json")):
            receipt["backups"].append(backup_tree(source, destination))
            atomic_json(receipt_path, receipt)
        atomic_json(recovery / "manifest.json", {"schema": VERSION, "backups": receipt["backups"]})
        # No selected files may have changed during the potentially long backup.
        validate_plan(plan, home)
        if processes():
            raise Stop("A Claude process started during backup; source writes stopped.")
        ensure_private_parent(trash.parent)
        trash.mkdir(mode=0o700)
        atomic_json(trash / MARKER, {"schema": VERSION, "batch_id": batch_id, "home": str(home), "kind": "trash", "nonce": nonce})
        ids = {"userID": secrets.token_hex(32), "machineID": secrets.token_hex(32)} if plan["options"]["rotate_local_id"] else {}
        for entry in plan["configs"]:
            path = Path(entry["path"])
            data = load_json(path)
            updated = {key: value for key, value in data.items() if key not in ACCOUNT_FIELDS}
            updated.update(ids)
            if updated != data:
                atomic_json(path, updated)
                receipt["rewritten"].append(str(path))
                atomic_json(receipt_path, receipt)
                checked = load_json(path)
                if checked != updated or ACCOUNT_FIELDS.intersection(checked):
                    raise Stop(f"Config verification failed: {path}")
        for index, entry in enumerate(plan["targets"], start=1):
            source = Path(entry["path"])
            if fingerprint(source) != entry:
                raise Stop(f"Target changed during execution: {source}")
            destination = trash / f"{index:03d}-{source.name}"
            before = tree_entries(source, hashes=True)
            move_record = {"source": str(source), "destination": str(destination), "attempted": True,
                           "move_returned": False, "content_verified": False}
            receipt["moved"].append(move_record)
            atomic_json(receipt_path, receipt)
            shutil.move(str(source), str(destination))
            move_record["move_returned"] = True
            atomic_json(receipt_path, receipt)
            if exists(source) or tree_entries(destination, hashes=True) != before:
                raise Stop(f"Move verification failed: {source}")
            move_record["content_verified"] = True
            atomic_json(receipt_path, receipt)
        if plan["options"]["keychain"] and plan["keychain_present"]:
            result = subprocess.run(["/usr/bin/security", "delete-generic-password", "-s", SERVICE], capture_output=True)
            if result.returncode != 0:
                raise Stop("Keychain deletion or verification failed; outputs withheld.")
            receipt["keychain_deleted"] = True
            atomic_json(receipt_path, receipt)
            if keychain_present():
                raise Stop("Keychain deletion or verification failed; outputs withheld.")
        if any(exists(Path(entry["path"])) for entry in plan["targets"]):
            raise Stop("A selected target reappeared; verification incomplete.")
        if protected_snapshot(home, plan["options"]) != protected_before:
            raise Stop("Protected data changed during execution; verification incomplete. Recover from the verified backup.")
        receipt["status"] = "complete"
        atomic_json(receipt_path, receipt)
        return {"status": "complete", "receipt": str(receipt_path), "recovery": str(recovery), "trash": str(trash),
                "moved_count": len(receipt["moved"]), "rewritten_count": len(receipt["rewritten"]),
                "keychain_deleted": receipt["keychain_deleted"], "recoverable": True, "purged": False}
    except (Exception, KeyboardInterrupt) as error:
        receipt["status"] = "partial"
        if exists(receipt_path):
            atomic_json(receipt_path, receipt)
        emit({"status": "partial", "receipt": str(receipt_path), "recovery": str(recovery), "trash": str(trash),
              "message": str(error) if isinstance(error, Stop) else "Filesystem / subprocess operation failed; private details withheld.",
              "remaining_actions_executed": False})
        raise Stop("Cleanup stopped; use the reported recovery paths. Do not retry apply on the old plan.") from None


def validate_receipt(receipt: dict, home: Path) -> tuple[Path, Path]:
    fields = {"schema", "batch_id", "home", "marker_nonce", "recovery", "trash", "status", "recoverable",
              "backups", "moved", "rewritten", "keychain_deleted", "plan_id"}
    if set(receipt) != fields or type(receipt["schema"]) is not int or receipt["schema"] != VERSION or receipt["home"] != str(home):
        raise Stop("Unrecognized receipt or home mismatch.")
    if not BATCH_RE.fullmatch(str(receipt["batch_id"])) or not re.fullmatch(r"[0-9a-f]{64}", str(receipt["marker_nonce"])):
        raise Stop("Invalid batch marker fields.")
    if receipt["status"] == "purged" or not receipt["recoverable"]:
        raise Stop("This batch has already been purged and cannot be restored.")
    recovery = home / ".claude-cleanup-recovery" / receipt["batch_id"]
    trash = home / ".Trash" / receipt["batch_id"]
    if receipt["recovery"] != str(recovery) or receipt["trash"] != str(trash):
        raise Stop("Receipt directory mismatch; arbitrary paths are forbidden.")
    for root, kind in ((recovery, "recovery"), (trash, "trash")):
        safe_path(root)
        if not exists(root):
            # A partial apply may have stopped before creating the Trash batch.
            # A purge retry may find a previously verified batch already removed.
            continue
        if not root.is_dir():
            raise Stop(f"Generated batch directory missing: {root}")
        expected = {"schema": VERSION, "batch_id": receipt["batch_id"], "home": str(home), "kind": kind, "nonce": receipt["marker_nonce"]}
        if load_json(root / MARKER) != expected:
            raise Stop(f"Generated marker mismatch: {root}")
        # Refuse special files. Tree walking records links but never follows them.
        tree_entries(root, hashes=False, allow_links=True)
    return recovery, trash


def purge(receipt_path: Path, home: Path) -> dict:
    require_macos()
    metadata_output_path(receipt_path, home)
    receipt = load_json(receipt_path)
    recovery, trash = validate_receipt(receipt, home)
    terminal_confirm("DELETE " + receipt["batch_id"], {
        "action": "permanent_purge", "directories": [str(recovery), str(trash)],
        "risks": ["Permanent deletion removes recovery copies and this batch's Trash contents.",
                  "Old credentials / sessions stored in backups may be present; this operation removes the entire two generated batches.",
                  "Other Trash contents are untouched. This receipt cannot restore anything after purge."],
    })
    validate_receipt(receipt, home)
    if not shutil.rmtree.avoids_symlink_attacks:
        raise Stop("This Python runtime lacks symlink-resistant tree deletion; purge is refused.")
    try:
        if exists(recovery):
            shutil.rmtree(recovery)
        if exists(trash):
            shutil.rmtree(trash)
        if exists(recovery) or exists(trash):
            raise Stop("Purge verification failed.")
        receipt["status"] = "purged"
        receipt["recoverable"] = False
        atomic_json(receipt_path, receipt)
        return {"status": "purged", "receipt": str(receipt_path), "recovery_exists": False,
                "trash_batch_exists": False, "recoverable": False}
    except (Exception, KeyboardInterrupt):
        raise Stop("Purge stopped partway; inspect both exact batch paths. Remaining deletion actions were not attempted.") from None


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    inspect = commands.add_parser("audit", help="Read-only inventory; write metadata plan only")
    inspect.add_argument("--plan", type=Path, help="Optional: save a new plan JSON in an existing task directory; omission writes nothing")
    inspect.add_argument("--desktop", action="store_true", help="Include Desktop persistent / Cowork data (not only caches)")
    inspect.add_argument("--reset-account", action="store_true", help="Remove 22 known top-level account fields; also synchronize internal config backups")
    inspect.add_argument("--keychain", action="store_true", help="Delete exactly the Claude Code-credentials keychain service during apply")
    inspect.add_argument("--rotate-local-id", action="store_true", help="Optional Claude application IDs only; requires --reset-account")
    inspect.add_argument("--uninstall", action="store_true", help="Include only existing /Applications/Claude.app and ~/Applications/Claude.app")
    execute = commands.add_parser("apply", help="Apply reviewed plan after real-terminal human confirmation")
    execute.add_argument("--plan", type=Path, required=True)
    remove = commands.add_parser("purge", help="Separately confirm permanent deletion of this script's generated batches only")
    remove.add_argument("--receipt", type=Path, required=True)
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    home = Path.home().absolute()
    try:
        safe_path(home)
        if args.command == "audit":
            options = {name: getattr(args, name) for name in OPTION_KEYS}
            result = audit(args.plan.absolute() if args.plan is not None else None, options, home)
        elif args.command == "apply":
            result = apply(args.plan.absolute(), home)
        else:
            result = purge(args.receipt.absolute(), home)
        emit(result)
        return 0
    except Stop as error:
        emit({"status": "stopped", "message": str(error)})
        return 2
    except (OSError, subprocess.SubprocessError, ValueError):
        emit({"status": "stopped", "message": "Operation failed; private file / credential contents withheld. No remaining actions executed."})
        return 2
    except (KeyboardInterrupt, EOFError):
        emit({"status": "stopped", "message": "Cancelled or input ended; no remaining actions executed."})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
