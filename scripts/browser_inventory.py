#!/usr/bin/env python3
"""Read-only browser profile / official-domain Cookie inventory on Mac / Windows.

No values, encrypted values, passwords or account emails are queried or emitted.
The result is a live SQLite snapshot, not a certificate that all site data is gone.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import configparser
import json
import os
from pathlib import Path
import sqlite3
import sys

DOMAINS = ("claude.ai", "claude.com", "anthropic.com")


def counts(database: Path) -> dict:
    try:
        with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=2)) as connection:
            rows = connection.execute("SELECT host_key, COUNT(*) FROM cookies GROUP BY host_key").fetchall()
        result = {d: 0 for d in DOMAINS}
        for host, count in rows:
            host = host.lstrip(".").lower()
            for domain in DOMAINS:
                if host == domain or host.endswith("." + domain):
                    result[domain] += count
        return {"database": str(database), "official_domain_cookie_counts": result,
                "method": "read-only live SQLite snapshot", "wal_present": Path(str(database) + "-wal").exists()}
    except (OSError, sqlite3.Error, ValueError):
        return {"database": str(database), "status": "not_verified", "reason": "Read denied / database unavailable"}


def chromium_profiles(root: Path) -> list[dict]:
    metadata = {}
    state = root / "Local State"
    if state.is_file():
        metadata = json.loads(state.read_text(encoding="utf-8")).get("profile", {}).get("info_cache", {})
    names = set(metadata)
    if root.is_dir():
        names.update(p.name for p in root.iterdir() if p.is_dir() and
                     (p.name in {"Default", "Guest Profile"} or p.name.startswith("Profile ")))
    result = []
    for name in sorted(names):
        # Never trust a Local State entry to name a path outside this data root.
        if name in {".", ".."} or any(c in name for c in ("/", "\\", ":")):
            continue
        path = root / name
        if not path.is_dir():
            continue
        databases = [p for p in [path / "Cookies", path / "Network/Cookies"] if p.is_file()]
        result.append({"name": metadata.get(name, {}).get("name", name), "directory": str(path),
                       "cookies": [counts(p) for p in databases],
                       "status": "profile_found" if databases else "cookie_database_not_found",
                       "site_storage": "Requires per-profile browser settings; not cleared by inventory"})
    return result


def inventory(home: Path, platform: str) -> list[dict]:
    if platform == "darwin":
        base = home / "Library/Application Support"
        roots = {"Chrome": base / "Google/Chrome", "Edge": base / "Microsoft Edge",
                 "Brave": base / "BraveSoftware/Brave-Browser", "Chromium": base / "Chromium"}
        firefox = base / "Firefox"
    elif platform == "win32":
        local = Path(os.environ.get("LOCALAPPDATA", str(home / "AppData/Local")))
        roaming = Path(os.environ.get("APPDATA", str(home / "AppData/Roaming")))
        roots = {"Chrome": local / "Google/Chrome/User Data", "Edge": local / "Microsoft/Edge/User Data",
                 "Brave": local / "BraveSoftware/Brave-Browser/User Data", "Chromium": local / "Chromium/User Data"}
        firefox = roaming / "Mozilla/Firefox"
    else:
        raise ValueError("Browser inventory supports macOS and native Windows only.")
    output = []
    for name, root in roots.items():
        try:
            if root.is_dir():
                output.append({"browser": name, "data_root": str(root), "profiles": chromium_profiles(root)})
        except (OSError, ValueError, TypeError, AttributeError):
            output.append({"browser": name, "data_root": str(root), "status": "not_verified"})
    ini = firefox / "profiles.ini"
    try:
        if ini.is_file():
            parser = configparser.ConfigParser(interpolation=None); parser.read(ini, encoding="utf-8")
            profiles = []
            for section in parser.sections():
                if not section.startswith("Profile") or not parser.has_option(section, "Path"):
                    continue
                path = Path(parser.get(section, "Path"))
                if parser.get(section, "IsRelative", fallback="1") == "1":
                    path = firefox / path
                profiles.append({"name": parser.get(section, "Name", fallback=section), "directory": str(path),
                                 "status": "UI verification required; Firefox Cookie data not queried"})
            output.append({"browser": "Firefox", "data_root": str(firefox), "profiles": profiles})
    except (OSError, configparser.Error):
        output.append({"browser": "Firefox", "status": "not_verified"})
    if platform == "darwin":
        output.append({"browser": "Safari", "status": "Use Safari Settings > Privacy > Manage Website Data; not inspected"})
    return output


def main() -> int:
    argparse.ArgumentParser(description=__doc__).parse_args()
    try:
        print(json.dumps({"source_modified": False, "browsers": inventory(Path.home().absolute(), sys.platform)},
                         ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError):
        print(json.dumps({"status": "not_verified", "source_modified": False, "reason": "Inventory unavailable"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
