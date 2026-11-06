"""config.toml loading, env overrides and graceful degradation."""

from __future__ import annotations

import model_switch_notify as msn


def _use_config(monkeypatch, tmp_path, body: str) -> None:
    path = tmp_path / "config.toml"
    path.write_text(body, encoding="utf-8")
    monkeypatch.setattr(msn, "_CONFIG_PATH", path)
    msn.reset_config_cache()


def test_defaults_without_a_config_file(monkeypatch, tmp_path):
    monkeypatch.setattr(msn, "_CONFIG_PATH", tmp_path / "missing.toml")
    msn.reset_config_cache()
    monkeypatch.delenv("MODEL_WATCH_RATE_PER_MIN", raising=False)
    monkeypatch.delenv("MODEL_WATCH_ENABLED", raising=False)
    monkeypatch.delenv("MODEL_WATCH_DRY_RUN", raising=False)
    monkeypatch.delenv("MODEL_WATCH_ERROR_HOLD_SECONDS", raising=False)
    assert msn._enabled() is True
    assert msn._dry_run() is False
    assert msn._rate_limit() == 10
    assert msn._hold_seconds() == msn._DEFAULT_HOLD_SECONDS
    assert msn._force_chat() == ""


def test_values_come_from_config(monkeypatch, tmp_path):
    _use_config(
        monkeypatch,
        tmp_path,
        """
[notify]
enabled = false
dry_run = true
rate_per_min = 3
error_hold_seconds = 1.5
force_chat = "oc_test"
language = "zh-TW"
""",
    )
    for name in (
        "MODEL_WATCH_ENABLED",
        "MODEL_WATCH_DRY_RUN",
        "MODEL_WATCH_RATE_PER_MIN",
        "MODEL_WATCH_ERROR_HOLD_SECONDS",
        "MODEL_WATCH_LANGUAGE",
    ):
        monkeypatch.delenv(name, raising=False)
    assert msn._enabled() is False
    assert msn._dry_run() is True
    assert msn._rate_limit() == 3
    assert msn._hold_seconds() == 1.5
    assert msn._force_chat() == "oc_test"
    assert msn._language() == "zh-TW"


def test_env_overrides_config(monkeypatch, tmp_path):
    _use_config(monkeypatch, tmp_path, "[notify]\nrate_per_min = 3\nlanguage = \"en\"\n")
    monkeypatch.setenv("MODEL_WATCH_RATE_PER_MIN", "7")
    monkeypatch.setenv("MODEL_WATCH_LANGUAGE", "zh-CN")
    assert msn._rate_limit() == 7
    assert msn._language() == "zh-CN"


def test_invalid_env_falls_through_to_config(monkeypatch, tmp_path):
    """A typo in the env override must not discard a valid config.toml value."""
    _use_config(monkeypatch, tmp_path, "[notify]\nrate_per_min = 3\nlanguage = \"zh-TW\"\n")
    monkeypatch.setenv("MODEL_WATCH_RATE_PER_MIN", "abc")
    monkeypatch.setenv("MODEL_WATCH_LANGUAGE", "fr")
    assert msn._rate_limit() == 3
    assert msn._language() == "zh-TW"


def test_invalid_values_fall_back(monkeypatch, tmp_path):
    _use_config(
        monkeypatch,
        tmp_path,
        """
[notify]
enabled = "maybe"
rate_per_min = 0
error_hold_seconds = "soon"
""",
    )
    for name in (
        "MODEL_WATCH_ENABLED",
        "MODEL_WATCH_RATE_PER_MIN",
        "MODEL_WATCH_ERROR_HOLD_SECONDS",
    ):
        monkeypatch.delenv(name, raising=False)
    assert msn._enabled() is True
    assert msn._rate_limit() == 10
    assert msn._hold_seconds() == msn._DEFAULT_HOLD_SECONDS


def test_broken_toml_does_not_raise(monkeypatch, tmp_path):
    _use_config(monkeypatch, tmp_path, "[notify\nbogus =")
    monkeypatch.delenv("MODEL_WATCH_RATE_PER_MIN", raising=False)
    assert msn._rate_limit() == 10


def test_missing_notify_table_uses_defaults(monkeypatch, tmp_path):
    _use_config(monkeypatch, tmp_path, "[other]\nvalue = 1\n")
    monkeypatch.delenv("MODEL_WATCH_RATE_PER_MIN", raising=False)
    assert msn._rate_limit() == 10
