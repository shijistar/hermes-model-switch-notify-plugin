"""Shared pytest fixtures: path injection and a clean per-test plugin state."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import model_switch_notify as msn  # noqa: E402

# The autouse fixture below patches configured_primary per test; stash the real
# implementation on the module so the cache-behaviour test can exercise it.
setattr(msn, "_REAL_CONFIGURED_PRIMARY", msn.configured_primary)


@pytest.fixture(autouse=True)
def clean_plugin_state(monkeypatch):
    """Every test starts from empty caches and a known configured route."""
    msn.reset_state()
    msn.reset_chat_cache()
    msn.reset_env_cache()
    msn.reset_primary_cache()
    msn.reset_profile_home_cache()

    monkeypatch.setattr(
        msn, "configured_primary", lambda: ("deepseek-v4.1-flash", "opencode-go")
    )
    monkeypatch.setenv("MODEL_WATCH_ERROR_HOLD_SECONDS", "0.15")
    monkeypatch.delenv("MODEL_WATCH_FORCE_CHAT", raising=False)
    monkeypatch.delenv("MODEL_WATCH_ENABLED", raising=False)
    monkeypatch.delenv("MODEL_WATCH_DRY_RUN", raising=False)
    yield
    msn.reset_state()


@pytest.fixture
def sent(monkeypatch):
    """Capture notices instead of resolving a chat and calling Feishu."""
    rows: list[tuple[str, str]] = []

    def record(session_id, state, text):
        rows.append((session_id, text))

    monkeypatch.setattr(msn, "_dispatch", record)
    return rows
