"""Build the Claude Desktop extension: claude-link/dist/wow-forever-link.mcpb

An .mcpb file is a zip with manifest.json at its root. Run: python claude-link/extension/build.py
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
OUT = ROOT / "dist" / "wow-forever-link.mcpb"

FILES = {
    "manifest.json": HERE / "manifest.json",
    "icon.png": ROOT / ".claude-plugin" / "icon.png",
    "server/launch.py": ROOT / "server" / "launch.py",
    "server/server.py": ROOT / "server" / "server.py",
    "server/requirements.txt": ROOT / "server" / "requirements.txt",
}
DIRS = {
    "server/wowlink": ROOT / "server" / "wowlink",
    "addon/ClaudeLink": ROOT / "addon" / "ClaudeLink",
}


def main() -> None:
    manifest = json.loads((HERE / "manifest.json").read_text(encoding="utf-8"))
    toc = (ROOT / "addon" / "ClaudeLink" / "ClaudeLink.toc").read_text(encoding="utf-8")
    addon_version = next(l.split(":", 1)[1].strip() for l in toc.splitlines() if l.startswith("## Version:"))
    if manifest["version"] != addon_version:
        raise SystemExit(f"manifest version {manifest['version']} != addon version {addon_version}")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
        for name, src in FILES.items():
            z.write(src, name)
        for prefix, folder in DIRS.items():
            for f in sorted(folder.rglob("*")):
                if f.is_file() and "__pycache__" not in f.parts:
                    z.write(f, f"{prefix}/{f.relative_to(folder).as_posix()}")
    print(f"built {OUT} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
