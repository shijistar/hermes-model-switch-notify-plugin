"""The installer must resolve the same home and profile the runtime reads."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
INSTALLER = ROOT / "post-install.sh"


@pytest.fixture
def hermes_stub(tmp_path):
    """A `hermes` executable that only records the arguments it receives."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "hermes.log"
    stub = bin_dir / "hermes"
    stub.write_text(f'#!/usr/bin/env bash\nprintf "%s\\n" "$*" >> "{log}"\n')
    stub.chmod(0o755)
    return bin_dir, log


def _env(bin_dir: Path, home: Path) -> dict[str, str]:
    return {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "HERMES_HOME": str(home),
    }


def _run(bin_dir: Path, home: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(INSTALLER), *args],
        env=_env(bin_dir, home),
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_profile_scoped_hermes_home_is_not_nested(tmp_path, hermes_stub):
    """HERMES_HOME=<root>/profiles/<name> must not become profiles/<name>/profiles/<name>."""
    bin_dir, log = hermes_stub
    profile = tmp_path / "hermes" / "profiles" / "coder"
    profile.mkdir(parents=True)

    result = _run(bin_dir, profile, "--profile", "coder")

    assert result.returncode == 0, result.stderr
    link = profile / "plugins" / "model-switch-notify"
    assert link.is_symlink()
    assert link.resolve() == ROOT.resolve()
    assert "-p coder plugins enable model-switch-notify" in log.read_text()


def test_profile_scoped_home_selects_its_profile(tmp_path, hermes_stub):
    """Without --profile the home's own profile is enabled, not `default`."""
    bin_dir, log = hermes_stub
    profile = tmp_path / "hermes" / "profiles" / "coder"
    profile.mkdir(parents=True)

    result = _run(bin_dir, profile)

    assert result.returncode == 0, result.stderr
    assert (profile / "plugins" / "model-switch-notify").is_symlink()
    assert "-p coder plugins enable model-switch-notify" in log.read_text()


def test_root_home_without_profile_targets_default(tmp_path, hermes_stub):
    bin_dir, log = hermes_stub
    root = tmp_path / "hermes"
    root.mkdir()

    result = _run(bin_dir, root)

    assert result.returncode == 0, result.stderr
    assert (root / "plugins" / "model-switch-notify").is_symlink()
    assert "-p default plugins enable model-switch-notify" in log.read_text()
    assert f"HERMES_HOME={root} hermes -p default plugins info model-switch-notify" in result.stdout


def test_summary_prints_the_selected_home_and_profile(tmp_path, hermes_stub):
    """A --hermes-home install must print a check command that targets that home."""
    bin_dir, _log = hermes_stub
    root = tmp_path / "hermes"
    (root / "profiles" / "coder").mkdir(parents=True)

    result = _run(bin_dir, root, "--profile", "coder")

    assert result.returncode == 0, result.stderr
    assert (
        f"HERMES_HOME={root} hermes -p coder plugins info model-switch-notify"
        in result.stdout
    )


def test_explicit_profile_wins_over_profile_scoped_home(tmp_path, hermes_stub):
    bin_dir, log = hermes_stub
    root = tmp_path / "hermes"
    (root / "profiles" / "coder").mkdir(parents=True)
    other = root / "profiles" / "other"
    other.mkdir()

    result = _run(bin_dir, root / "profiles" / "coder", "--profile", "other")

    assert result.returncode == 0, result.stderr
    assert (other / "plugins" / "model-switch-notify").is_symlink()
    assert "-p other plugins enable model-switch-notify" in log.read_text()


def test_existing_directory_is_backed_up_outside_plugins(tmp_path, hermes_stub):
    """A backup left in plugins/ would shadow the real plugin (same manifest key)."""
    bin_dir, _log = hermes_stub
    profile = tmp_path / "hermes" / "profiles" / "coder"
    plugin_dir = profile / "plugins" / "model-switch-notify"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.yaml").write_text("name: model-switch-notify\nversion: 0.0.1\n")

    result = _run(bin_dir, profile, "--profile", "coder")

    assert result.returncode == 0, result.stderr
    backups = list((profile / "plugin-backups").glob("model-switch-notify.bak.*"))
    assert len(backups) == 1
    assert (backups[0] / "plugin.yaml").is_file()
    assert plugin_dir.is_symlink()
    assert not list((profile / "plugins").glob("model-switch-notify.bak.*"))


def test_runs_from_an_installed_plugin_directory(tmp_path, hermes_stub):
    """A Hermes-managed install is a full checkout, so setup may run from it."""
    bin_dir, _log = hermes_stub
    profile = tmp_path / "hermes" / "profiles" / "coder"
    plugin_dir = profile / "plugins" / "model-switch-notify"
    plugin_dir.mkdir(parents=True)
    shutil.copy2(INSTALLER, plugin_dir / "post-install.sh")
    shutil.copytree(ROOT / "skill", plugin_dir / "skill")

    result = subprocess.run(
        ["bash", str(plugin_dir / "post-install.sh")],
        env=_env(bin_dir, profile),
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, result.stderr
    assert "already is this checkout" in result.stdout
    assert (plugin_dir / "skill").is_dir()
    assert (profile / "skills" / "devops" / "model-switch-notify").is_symlink()
