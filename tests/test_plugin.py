"""Plugin registration, manifest contract, profile detection, and message shape."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
import yaml

import model_switch_notify as msn

ROOT = Path(__file__).resolve().parent.parent


class _Ctx:
    def __init__(self):
        self.hooks: list[tuple[str, object]] = []
        self.commands: list[str] = []

    def register_hook(self, name, callback):
        self.hooks.append((name, callback))

    def register_command(self, name, handler=None, description=""):
        self.commands.append(name)


def test_manifest_declares_both_hooks():
    manifest = yaml.safe_load((ROOT / "plugin.yaml").read_text(encoding="utf-8"))

    assert manifest["name"] == "model-switch-notify"
    assert manifest["provides_hooks"] == ["post_api_request", "api_request_error"]
    assert manifest["version"].count(".") == 2


def test_register_wires_both_hooks():
    ctx = _Ctx()
    msn.register(ctx)

    names = [name for name, _ in ctx.hooks]
    assert names == ["post_api_request", "api_request_error"]
    assert all(callable(cb) for _, cb in ctx.hooks)


def test_package_entry_delegates_to_register(monkeypatch):
    """Hermes imports the package __init__; it must forward to the module."""
    spec = importlib.util.spec_from_file_location(
        "msn_pkg", ROOT / "__init__.py", submodule_search_locations=[str(ROOT)]
    )
    package = importlib.util.module_from_spec(spec)
    sys.modules["msn_pkg"] = package
    spec.loader.exec_module(package)  # type: ignore[union-attr]

    ctx = _Ctx()
    package.register(ctx)

    assert [name for name, _ in ctx.hooks] == ["post_api_request", "api_request_error"]


def test_profile_home_follows_an_installed_symlink(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    profile = home / "profiles" / "coder"
    plugins = profile / "plugins"
    plugins.mkdir(parents=True)
    (plugins / "model-switch-notify").symlink_to(ROOT, target_is_directory=True)

    monkeypatch.setattr(msn, "_HERMES_HOME", home)
    monkeypatch.delenv("HERMES_PROFILE", raising=False)
    msn.reset_profile_home_cache()

    assert msn.profile_home() == profile


def test_profile_home_prefers_explicit_profile_env(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    profile = home / "profiles" / "excel"
    profile.mkdir(parents=True)

    monkeypatch.setattr(msn, "_HERMES_HOME", home)
    monkeypatch.setenv("HERMES_PROFILE", "excel")
    msn.reset_profile_home_cache()

    assert msn.profile_home() == profile


def test_profile_home_falls_back_to_default_home(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    home.mkdir()

    monkeypatch.setattr(msn, "_HERMES_HOME", home)
    monkeypatch.delenv("HERMES_PROFILE", raising=False)
    msn.reset_profile_home_cache()

    assert msn.profile_home() == home


def test_switch_message_names_cause_and_both_routes():
    text = msn._switch_message(
        ("old-model", "old-provider"),
        ("new-model", "new-provider"),
        {"status": 429, "reason": "rate_limit", "count": 2},
    )

    assert "原模型：old-model（old-provider）" in text
    assert "现模型：new-model（new-provider）" in text
    assert "HTTP 429" in text and "rate_limit" in text
    assert "连续 2 次失败" in text


def test_error_message_marks_whether_it_was_the_primary():
    primary = msn._error_message(("m", "p"), {"status": 500}, is_primary=True)
    fallback = msn._error_message(("m", "p"), {"status": 500}, is_primary=False)

    assert "主模型调用失败" in primary
    assert "当前模型调用失败" in fallback


def test_reason_text_handles_missing_details():
    assert msn._reason_text({}) == "调用失败"
    assert msn._reason_text({"status": 502}) == "HTTP 502"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1", True),
        ("0", False),
        ("off", False),
        ("", True),
    ],
)
def test_enabled_flag(raw, expected, monkeypatch):
    monkeypatch.setenv("MODEL_WATCH_ENABLED", raw)
    assert msn._enabled() is expected


def test_read_dotenv_ignores_comments_and_quotes(tmp_path):
    env = tmp_path / ".env"
    env.write_text('# comment\nFEISHU_APP_ID="cli_1"\nFEISHU_APP_SECRET=\'s3cret\'\n\n', encoding="utf-8")

    assert msn._read_dotenv(env) == {"FEISHU_APP_ID": "cli_1", "FEISHU_APP_SECRET": "s3cret"}
