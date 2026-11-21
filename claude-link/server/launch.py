"""Starts the ClaudeLink MCP server from a plugin or Claude Desktop extension install.

Uses only the standard library.

Updates: on each start it asks GitHub (natanel80/claudelink-wow, branch main)
which version is current. The repository may be private: then a read-only
GitHub token is needed (the extension's "GitHub token" setting,
CLAUDELINK_GITHUB_TOKEN). If that is newer than what it has, it downloads the
server and addon code into ~/.claudelink/app-<version> and runs that copy. The
server then copies the new addon into the game folder. Turn this off with the
extension's "Automatic updates" setting (CLAUDELINK_AUTO_UPDATE=false).

Packages: on first run it installs the server's packages into a private folder
(pip --target) and runs server.py in this same Python process. No virtual
environment: the Microsoft Store Python redirects files it writes under AppData
to a hidden folder, so a venv created there can't be started as a separate
program. The private folder is under the home folder for the same reason.

stdout is the MCP channel, so this script prints to stderr only.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import runpy
import shutil
import site
import subprocess
import sys
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Optional

HERE = Path(__file__).resolve().parent          # .../server
BUNDLED = HERE.parent                           # holds server/ and addon/
REPO = "natanel80/claudelink-wow"
BRANCH = "main"
UPDATE_BASE = os.environ.get("CLAUDELINK_UPDATE_BASE", "")  # for tests


def log(msg: str) -> None:
    print(f"[ClaudeLink] {msg}", file=sys.stderr, flush=True)


def is_store_python() -> bool:
    paths = (sys.executable, sys.prefix, sys.base_prefix)
    return any("WindowsApps" in p or "PythonSoftwareFoundation" in p for p in paths)


def data_dir() -> Path:
    value = os.environ.get("CLAUDELINK_DATA", "")
    if value and "${" not in value:
        p = Path(value)
        if not (is_store_python() and "appdata" in str(p).lower()):
            return p
    return Path.home() / ".claudelink"


# ---------------------------------------------------------------------------
# Versions and updates
# ---------------------------------------------------------------------------
def parse_version(v: Optional[str]) -> tuple:
    try:
        return tuple(int(x) for x in str(v).strip().split("."))
    except ValueError:
        return ()


def code_version(root: Path) -> Optional[str]:
    """Version of a code folder (server/ + addon/), from the addon's .toc."""
    toc = root / "addon" / "ClaudeLink" / "ClaudeLink.toc"
    try:
        for line in toc.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("## Version:"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return None


def is_complete(root: Path) -> bool:
    return (root / "server" / "server.py").is_file() and (root / "server" / "requirements.txt").is_file() \
        and code_version(root) is not None


def best_code(base: Path) -> Path:
    """The newest complete code folder: the bundled one or a downloaded update."""
    best, best_v = BUNDLED, parse_version(code_version(BUNDLED))
    for d in base.glob("app-*"):
        v = parse_version(code_version(d))
        if is_complete(d) and v > best_v:
            best, best_v = d, v
    return best


def github_token() -> str:
    token = os.environ.get("CLAUDELINK_GITHUB_TOKEN", "").strip()
    return "" if "${" in token else token


def _get(url: str, timeout: float, accept: Optional[str] = None) -> bytes:
    headers = {"User-Agent": "ClaudeLink-updater"}
    if accept:
        headers["Accept"] = accept
    token = github_token()
    if token and url.startswith("https://api.github.com/"):
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403, 404) and not UPDATE_BASE:
            hint = "check the GitHub token" if token else "the repository is private: add a GitHub token"
            raise RuntimeError(f"GitHub answered {exc.code} ({hint})") from None
        raise


def remote_version(timeout: float = 4) -> Optional[str]:
    if UPDATE_BASE:
        data = _get(f"{UPDATE_BASE}/claude-link/extension/manifest.json", timeout)
    else:
        data = _get(f"https://api.github.com/repos/{REPO}/contents/claude-link/extension/manifest.json?ref={BRANCH}",
                    timeout, accept="application/vnd.github.raw")
    return json.loads(data.decode("utf-8")).get("version")


def download_update(base: Path, version: str, timeout: float = 30) -> Path:
    url = (UPDATE_BASE + "/archive.zip") if UPDATE_BASE else \
        f"https://api.github.com/repos/{REPO}/zipball/{BRANCH}"
    archive = zipfile.ZipFile(io.BytesIO(_get(url, timeout)))
    target = base / f"app-{version}"
    tmp = base / f".app-{version}.tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    for name in archive.namelist():
        # GitHub archives start with "<repo>-<branch>/"; keep claude-link/server and claude-link/addon.
        parts = name.split("/", 2)
        if len(parts) < 3 or parts[1] != "claude-link" or name.endswith("/"):
            continue
        rel = parts[2]
        if not (rel.startswith("server/") or rel.startswith("addon/")) or "/tests/" in rel or "__pycache__" in rel:
            continue
        dest = tmp / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(archive.read(name))
    if not is_complete(tmp) or code_version(tmp) != version:
        shutil.rmtree(tmp, ignore_errors=True)
        raise RuntimeError("the downloaded update is incomplete")
    shutil.rmtree(target, ignore_errors=True)
    tmp.rename(target)
    return target


def check_for_update(base: Path) -> None:
    if os.environ.get("CLAUDELINK_AUTO_UPDATE", "true").strip().lower() in ("false", "0", "no", "off"):
        return
    try:
        have = best_code(base)
        latest = remote_version()
        if latest and parse_version(latest) > parse_version(code_version(have)):
            log(f"Updating to version {latest}...")
            download_update(base, latest)
            log(f"Updated to version {latest}.")
    except Exception as exc:  # offline, GitHub down, ...: run what we have
        log(f"Update check skipped: {exc}")
    # Keep only the newest two downloaded versions.
    apps = sorted((d for d in base.glob("app-*") if d.is_dir()),
                  key=lambda d: parse_version(code_version(d)), reverse=True)
    for old in apps[2:]:
        shutil.rmtree(old, ignore_errors=True)


# ---------------------------------------------------------------------------
# Packages
# ---------------------------------------------------------------------------
def ensure_packages(base: Path, requirements: Path) -> Path:
    lib = base / f"lib-py{sys.version_info.major}{sys.version_info.minor}"
    marker = lib / ".requirements.sha256"
    wanted = hashlib.sha256(requirements.read_bytes()).hexdigest()
    if marker.exists() and marker.read_text().strip() == wanted:
        return lib
    log(f"Installing Python packages into {lib} (about a minute)...")
    lib.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--no-input", "-q",
         "--upgrade", "--target", str(lib), "-r", str(requirements)],
        check=True, stdout=sys.stderr, stderr=sys.stderr, stdin=subprocess.DEVNULL,
    )
    marker.write_text(wanted)
    log("Packages installed.")
    return lib


def main() -> int:
    if sys.version_info < (3, 10):
        log("Python 3.10 or newer is needed (python.org).")
        return 1
    base = data_dir()
    try:
        base.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        log(f"Could not create {base}: {exc}")
        return 1
    check_for_update(base)
    code = best_code(base)
    log(f"Running version {code_version(code)} from {code}")
    try:
        lib = ensure_packages(base, code / "server" / "requirements.txt")
    except (subprocess.CalledProcessError, OSError) as exc:
        log(f"Could not install the packages: {exc}")
        return 1
    # addsitedir also runs the folder's .pth files; pywin32 (needed by the mcp
    # package on Windows) only becomes importable through its pywin32.pth.
    site.addsitedir(str(lib))
    sys.path.insert(0, str(lib))
    os.environ["CLAUDELINK_DATA"] = str(base)
    runpy.run_path(str(code / "server" / "server.py"), run_name="__main__")
    return 0


if __name__ == "__main__":
    sys.exit(main())
