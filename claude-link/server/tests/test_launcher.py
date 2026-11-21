"""The launcher's self-update, against a local web server that looks like GitHub."""
from __future__ import annotations

import importlib.util
import io
import json
import threading
import zipfile
from functools import partial
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

import pytest

LAUNCH = Path(__file__).resolve().parents[1] / "launch.py"


def load_launch(monkeypatch, base_url: str):
    monkeypatch.setenv("CLAUDELINK_UPDATE_BASE", base_url)
    spec = importlib.util.spec_from_file_location("launch_under_test", LAUNCH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def fake_github(tmp_path):
    """Serves <root>/claude-link/extension/manifest.json and <root>/archive.zip."""
    root = tmp_path / "web"
    (root / "claude-link" / "extension").mkdir(parents=True)

    def publish(version: str, complete: bool = True):
        (root / "claude-link" / "extension" / "manifest.json").write_text(json.dumps({"version": version}))
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            prefix = "claudelink-wow-main/claude-link/"
            z.writestr(prefix + "server/server.py", "print('new server')\n")
            if complete:
                z.writestr(prefix + "server/requirements.txt", "mcp>=1.9,<2\n")
            z.writestr(prefix + "server/wowlink/__init__.py", "")
            z.writestr(prefix + "server/tests/test_x.py", "")
            z.writestr(prefix + "addon/ClaudeLink/ClaudeLink.toc", f"## Version: {version}\n")
            z.writestr(prefix + "README.md", "not copied")
        (root / "archive.zip").write_bytes(buf.getvalue())

    handler = partial(SimpleHTTPRequestHandler, directory=str(root))
    handler.log_message = lambda *a: None
    server = HTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}", publish
    server.shutdown()


def test_downloads_a_newer_version_and_runs_it(monkeypatch, tmp_path, fake_github):
    url, publish = fake_github
    publish("99.0.0")
    launch = load_launch(monkeypatch, url)
    data = tmp_path / "data"
    data.mkdir()
    launch.check_for_update(data)
    app = data / "app-99.0.0"
    assert (app / "server" / "server.py").read_text() == "print('new server')\n"
    assert not (app / "server" / "tests").exists() and not (app / "README.md").exists()
    assert launch.best_code(data) == app


def test_keeps_the_bundled_code_when_github_is_not_newer(monkeypatch, tmp_path, fake_github):
    url, publish = fake_github
    publish("0.0.1")
    launch = load_launch(monkeypatch, url)
    data = tmp_path / "data"
    data.mkdir()
    launch.check_for_update(data)
    assert not list(data.glob("app-*"))
    assert launch.best_code(data) == launch.BUNDLED


def test_rejects_an_incomplete_download(monkeypatch, tmp_path, fake_github):
    url, publish = fake_github
    publish("99.0.0", complete=False)
    launch = load_launch(monkeypatch, url)
    data = tmp_path / "data"
    data.mkdir()
    launch.check_for_update(data)
    assert not list(data.glob("app-*")) and not list(data.glob(".app-*"))
    assert launch.best_code(data) == launch.BUNDLED


def test_offline_and_disabled(monkeypatch, tmp_path):
    launch = load_launch(monkeypatch, "http://127.0.0.1:9")  # nothing listens there
    data = tmp_path / "data"
    data.mkdir()
    launch.check_for_update(data)  # must not raise
    assert launch.best_code(data) == launch.BUNDLED
    monkeypatch.setenv("CLAUDELINK_AUTO_UPDATE", "false")
    launch.check_for_update(data)
    assert not list(data.glob("app-*"))


def test_old_downloads_are_cleaned_up(monkeypatch, tmp_path, fake_github):
    url, publish = fake_github
    launch = load_launch(monkeypatch, url)
    data = tmp_path / "data"
    data.mkdir()
    for v in ("97.0.0", "98.0.0", "99.0.0"):
        publish(v)
        launch.check_for_update(data)
    assert sorted(d.name for d in data.glob("app-*")) == ["app-98.0.0", "app-99.0.0"]


def test_hands_off_to_the_newest_downloaded_launcher(monkeypatch, tmp_path, fake_github):
    """An old install must run the downloaded launcher, so launcher changes arrive through updates."""
    url, publish = fake_github
    publish("99.0.0")
    launch = load_launch(monkeypatch, url)
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("CLAUDELINK_DATA", str(data))
    monkeypatch.delenv("CLAUDELINK_HANDOFF", raising=False)
    launch.check_for_update(data)
    new_launcher = data / "app-99.0.0" / "server" / "launch.py"
    marker = tmp_path / "handed-off.txt"
    new_launcher.write_text(
        "import os, pathlib\n"
        f"pathlib.Path({str(marker)!r}).write_text(os.environ.get('CLAUDELINK_HANDOFF', ''))\n"
    )
    monkeypatch.setattr(launch, "check_for_update", lambda base: None)
    assert launch.main() == 0
    assert marker.read_text() == "1"
