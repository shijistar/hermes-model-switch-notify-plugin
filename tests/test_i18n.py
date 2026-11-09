"""Localization: locale files, language resolution and fallback chains."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

import model_switch_notify as msn

ROOT = Path(__file__).resolve().parent.parent
LOCALES = ROOT / "locales"


def _set_language(monkeypatch, value):
    monkeypatch.setenv("MODEL_WATCH_LANGUAGE", value)
    msn.reset_locale_cache()


def test_locale_files_share_the_same_keys():
    """A missing translation is caught here, not in production."""
    sets = {
        code: set(json.loads((LOCALES / f"{code}.json").read_text(encoding="utf-8")))
        for code in ("en", "zh-CN", "zh-TW", "zh-HK")
    }
    assert sets["en"] == sets["zh-CN"] == sets["zh-TW"] == sets["zh-HK"]


@pytest.mark.parametrize(
    "language,expected_title",
    [
        ("en", "⚠️ Model switched"),
        ("zh-CN", "⚠️ 模型已切换"),
        ("zh-TW", "⚠️ 模型已切換"),
        ("zh-HK", "⚠️ 模型已切換"),
    ],
)
def test_switch_message_is_localized(monkeypatch, language, expected_title):
    _set_language(monkeypatch, language)
    text = msn._switch_message(("a", "p1"), ("b", "p2"), {"reason": "boom", "count": 1})
    assert text.splitlines()[0] == expected_title


def test_default_language_is_english(monkeypatch):
    monkeypatch.delenv("MODEL_WATCH_LANGUAGE", raising=False)
    msn.reset_config_cache()
    assert msn._language() == "en"
    assert msn._t("switch.title") == "⚠️ Model switched"


def test_unknown_language_falls_back_to_english(monkeypatch):
    _set_language(monkeypatch, "fr")
    assert msn._language() == "en"
    assert msn._t("switch.title") == "⚠️ Model switched"


def test_auto_follows_ui_language(monkeypatch, tmp_path):
    (tmp_path / "config.yaml").write_text("ui:\n  language: zh-TW\n", encoding="utf-8")
    monkeypatch.setattr(msn, "profile_home", lambda: tmp_path)
    _set_language(monkeypatch, "auto")
    assert msn._language() == "zh-TW"


def test_auto_falls_back_to_lang(monkeypatch, tmp_path):
    monkeypatch.setattr(msn, "profile_home", lambda: tmp_path)
    monkeypatch.setenv("LANG", "zh_CN.UTF-8")
    monkeypatch.delenv("LC_ALL", raising=False)
    monkeypatch.delenv("LC_MESSAGES", raising=False)
    _set_language(monkeypatch, "auto")
    assert msn._language() == "zh-CN"


def test_missing_key_falls_back_through_the_chain(monkeypatch):
    _set_language(monkeypatch, "zh-TW")
    msn._locale("zh-CN")["switch.title"] = "should-not-be-used"
    msn._locale("zh-TW").pop("switch.title", None)
    assert msn._t("switch.title") == "should-not-be-used"
    msn._locale("zh-CN").pop("switch.title", None)
    assert msn._t("switch.title") == "⚠️ Model switched"


def test_missing_locale_file_degrades_to_english(monkeypatch, tmp_path):
    """Chinese files missing, English present: the chain still resolves."""
    fake = tmp_path / "locales"
    fake.mkdir()
    shutil.copy(LOCALES / "en.json", fake / "en.json")
    monkeypatch.setattr(msn, "_LOCALES_DIR", fake)
    _set_language(monkeypatch, "zh-TW")
    assert msn._t("switch.title") == "⚠️ Model switched"


def test_all_locale_files_missing_returns_the_key(monkeypatch, tmp_path):
    """With no locale data at all, the key is the last-resort placeholder."""
    monkeypatch.setattr(msn, "_LOCALES_DIR", tmp_path / "none")
    _set_language(monkeypatch, "en")
    assert msn._t("switch.title") == "switch.title"


def test_timeout_detail_includes_duration_and_threshold(monkeypatch):
    _set_language(monkeypatch, "en")
    monkeypatch.delenv("HERMES_STREAM_STALE_TIMEOUT", raising=False)
    pending = {
        "reason": "timeout",
        "duration": 180.4,
        "provider": "opencode-go",
        "model": "hy4",
        "count": 1,
    }
    text = msn._reason_text(pending)
    assert "timeout" in text
    assert "180.4s" in text
    assert "watchdog 180s" in text


def test_timeout_detail_uses_configured_provider_threshold(monkeypatch, tmp_path):
    (tmp_path / "config.yaml").write_text(
        "providers:\n  opencode-go:\n    stale_timeout_seconds: 240\n", encoding="utf-8"
    )
    monkeypatch.setattr(msn, "profile_home", lambda: tmp_path)
    _set_language(monkeypatch, "en")
    pending = {"reason": "timeout", "duration": 240.2, "provider": "opencode-go", "model": "x"}
    assert "watchdog 240s" in msn._reason_text(pending)


def test_timeout_detail_is_localized(monkeypatch):
    _set_language(monkeypatch, "zh-CN")
    monkeypatch.delenv("HERMES_STREAM_STALE_TIMEOUT", raising=False)
    pending = {"reason": "timeout", "duration": 180.0, "provider": "", "model": ""}
    text = msn._reason_text(pending)
    assert "已等待 180.0s" in text
    assert "watchdog 180s" in text


def test_timeout_without_duration_degrades(monkeypatch):
    _set_language(monkeypatch, "en")
    assert msn._reason_text({"reason": "timeout", "count": 1}) == "timeout"


def test_hong_kong_copy_uses_local_vocabulary(monkeypatch):
    """zh-HK says 通話/本次 where zh-TW says 呼叫/本輪."""
    _set_language(monkeypatch, "zh-TW")
    tw = msn._error_message(("m", "p"), {"reason": "x"}, is_primary=True)
    assert "呼叫失敗" in tw
    assert "通話" not in tw

    _set_language(monkeypatch, "zh-HK")
    hk = msn._error_message(("m", "p"), {"reason": "x"}, is_primary=True)
    assert "通話失敗" in hk
    assert "呼叫" not in hk

    _set_language(monkeypatch, "zh-TW")
    assert "本輪" in msn._error_message(("m", "p"), {"reason": "x"})
    _set_language(monkeypatch, "zh-HK")
    assert "本次" in msn._error_message(("m", "p"), {"reason": "x"})


def test_auto_detects_hong_kong_locale(monkeypatch, tmp_path):
    monkeypatch.setattr(msn, "profile_home", lambda: tmp_path)
    monkeypatch.setenv("LANG", "zh_HK.UTF-8")
    monkeypatch.delenv("LC_ALL", raising=False)
    monkeypatch.delenv("LC_MESSAGES", raising=False)
    _set_language(monkeypatch, "auto")
    assert msn._language() == "zh-HK"


def test_hong_kong_falls_back_to_taiwan(monkeypatch):
    _set_language(monkeypatch, "zh-HK")
    msn._locale("zh-HK").pop("switch.title", None)
    assert msn._t("switch.title") == "⚠️ 模型已切換"


def test_short_timeout_reports_transport_not_watchdog(monkeypatch):
    """A transport failure at 31.7s is not a 180s stale-stream watchdog kill."""
    _set_language(monkeypatch, "en")
    monkeypatch.delenv("HERMES_STREAM_STALE_TIMEOUT", raising=False)
    pending = {
        "reason": "timeout", "duration": 31.7, "provider": "opencode-go",
        "model": "hy4", "error_type": "ReadTimeout", "count": 1,
    }
    text = msn._reason_text(pending)
    assert "waited 31.7s" in text
    assert "transport: ReadTimeout" in text
    assert "watchdog" not in text


def test_short_timeout_without_error_type_degrades_to_duration(monkeypatch):
    """No exception class available: fall back to the duration-only copy."""
    _set_language(monkeypatch, "en")
    monkeypatch.delenv("HERMES_STREAM_STALE_TIMEOUT", raising=False)
    text = msn._reason_text({
        "reason": "timeout", "duration": 39.8, "provider": "", "model": "",
    })
    assert "waited 39.8s" in text
    assert "watchdog" not in text
    assert "transport" not in text


def test_timeout_at_threshold_still_names_watchdog(monkeypatch):
    """Exactly reaching the configured budget keeps the watchdog copy."""
    _set_language(monkeypatch, "en")
    monkeypatch.delenv("HERMES_STREAM_STALE_TIMEOUT", raising=False)
    pending = {
        "reason": "timeout", "duration": 180.0, "provider": "", "model": "",
        "error_type": "ReadTimeout",
    }
    assert "watchdog 180s" in msn._reason_text(pending)


def test_transport_copy_is_localized(monkeypatch):
    """The transport-copy key is translated, not left as an English fallback."""
    _set_language(monkeypatch, "zh-CN")
    text = msn._reason_text({
        "reason": "timeout", "duration": 31.7, "error_type": "ReadTimeout",
    })
    assert "传输层：ReadTimeout" in text
    assert "watchdog" not in text


def test_disabled_watchdog_budget_omits_watchdog_copy(monkeypatch):
    """A zero stale budget means no watchdog; never print 'watchdog 0s'."""
    _set_language(monkeypatch, "en")
    monkeypatch.setenv("HERMES_STREAM_STALE_TIMEOUT", "0")
    text = msn._reason_text({
        "reason": "timeout", "duration": 31.7, "error_type": "ReadTimeout",
    })
    assert "waited 31.7s" in text
    assert "watchdog" not in text


def test_timeout_copy_never_reads_the_developer_profile():
    """The suite's isolation invariant: no developer config.yaml is in reach.

    conftest points ``_HERMES_HOME`` at a path that does not exist, so the formatter
    cannot inherit a machine-specific provider budget. Without that guard a profile
    pinning ``stale_timeout_seconds`` would flip the 31.7s assertions above.
    """
    assert not (msn.profile_home() / "config.yaml").exists()


def test_configured_budget_still_overrides_the_isolated_default(monkeypatch, tmp_path):
    """A profile budget of 30s must win over both the default and the env var.

    Pairs with the invariant above: re-enabling the profile seam has to change the
    copy, otherwise the isolation would be hiding a dead code path.
    """
    (tmp_path / "config.yaml").write_text(
        "providers:\n  opencode-go:\n    stale_timeout_seconds: 30\n", encoding="utf-8"
    )
    monkeypatch.setattr(msn, "profile_home", lambda: tmp_path)
    _set_language(monkeypatch, "en")
    pending = {
        "reason": "timeout", "duration": 31.7, "provider": "opencode-go",
        "model": "hy4", "error_type": "ReadTimeout", "count": 1,
    }
    text = msn._reason_text(pending)
    assert "watchdog 30s" in text
    assert "transport" not in text

