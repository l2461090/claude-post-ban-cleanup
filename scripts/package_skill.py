#!/usr/bin/env python3
"""Rebuild the portable skill ZIP from an explicit, non-private allowlist."""
import hashlib
from pathlib import Path
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED


def main():
    root = Path(__file__).resolve().parents[1]
    files = [root / "SKILL.md", root / "使用说明.md", root / "agents/openai.yaml"]
    files += sorted((root / "references").glob("*.md"))
    files += [root / "references/upstream-license.txt"]
    files += [root / "scripts" / name for name in
              ["local_cleanup.py", "windows_cleanup.py", "browser_inventory.py"]]
    output = root / "dist/claude-post-ban-cleanup.zip"
    output.parent.mkdir(exist_ok=True)
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        for path in sorted(files):
            info = ZipInfo("claude-post-ban-cleanup/" + path.relative_to(root).as_posix(), (2026, 10, 10, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes())
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix(".zip.sha256").write_text(f"{digest}  {output.name}\n", encoding="ascii")
    print(f"Built {output.name}: {len(files)} files; SHA256 {digest}")


if __name__ == "__main__":
    main()
