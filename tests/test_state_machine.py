"""Route-change state machine: merge window, retry, recovery, dedupe, rate limit."""

from __future__ import annotations

import threading
import time

import pytest

import model_switch_notify as msn

SID = "session-under-test"
PRIMARY = ("deepseek-v4.1-flash", "opencode-go")
FALLBACK = ("stepfun/step-3.7-flash:free", "nous")


def post(session_id=SID, model=PRIMARY[0], provider=PRIMARY[1], platform="feishu"):
    msn.on_post_api_request(session_id=session_id, model=model, provider=provider, platform=platform)


def error(session_id=SID, model=PRIMARY[0], provider=PRIMARY[1], status=429,
          reason="FailoverReason.rate_limit", retryable=True, platform="feishu"):
    msn.on_api_request_error(
        session_id=session_id, model=model, provider=provider, status_code=status,
        reason=reason, retryable=retryable, platform=platform,
    )


def test_first_success_only_primes_state(sent):
    post()
    assert sent == []


def test_repeated_same_route_is_silent(sent):
    post()
    post()
    post()
    assert sent == []


def test_error_then_switch_merges_into_one_message(sent):
    post()
    error()
    time.sleep(0.03)
    post(model=FALLBACK[0], provider=FALLBACK[1])
    time.sleep(0.25)

    assert len(sent) == 1
    text = sent[0][1]
    assert "模型已切换" in text
    assert "429" in text and "rate_limit" in text
    assert PRIMARY[0] in text and FALLBACK[0] in text


def test_switch_back_emits_recovery(sent):
    post()
    post(model=FALLBACK[0], provider=FALLBACK[1])
    post()

    assert len(sent) == 2
    assert "已切回主模型" in sent[1][1]


def test_error_with_successful_retry_reports_once(sent):
    post()
    error(status=500, reason="FailoverReason.server_error")
    post()
    time.sleep(0.25)

    assert len(sent) == 1
    assert "主模型调用失败" in sent[0][1]
    assert "已自动重试成功" in sent[0][1]


def test_lone_error_flushes_after_hold(sent):
    post()
    error(status=503, reason="FailoverReason.unavailable")
    time.sleep(0.3)

    assert len(sent) == 1
    assert "主模型调用失败" in sent[0][1]


def test_repeated_errors_collapse_with_count(sent):
    post()
    error()
    error()
    error()
    time.sleep(0.3)

    assert len(sent) == 1
    assert "连续 3 次失败" in sent[0][1]


def test_new_episode_reports_the_same_switch_again(sent):
    post()
    post(model=FALLBACK[0], provider=FALLBACK[1])
    post()
    post(model=FALLBACK[0], provider=FALLBACK[1])

    assert len(sent) == 3
    kinds = [("已切换" in text, "已切回" in text) for _, text in sent]
    assert kinds == [(True, False), (False, True), (True, False)]


def test_auxiliary_route_error_is_ignored(sent):
    post()
    error(model="some-other-model", provider="other")

    assert sent == []


def test_unknown_primary_falls_back_to_first_observed_route(sent, monkeypatch):
    monkeypatch.setattr(msn, "configured_primary", lambda: None)
    post(model="custom-model", provider="custom")
    post(model=FALLBACK[0], provider=FALLBACK[1])

    assert len(sent) == 1
    assert "模型已切换" in sent[0][1]


def test_rate_limit_caps_at_ten_per_minute(monkeypatch):
    captured: list[tuple[str, str]] = []
    monkeypatch.setattr(msn, "resolve_chat_id", lambda sid: "oc_test")
    monkeypatch.setattr(msn, "_ensure_worker", lambda: None)
    monkeypatch.setattr(msn._outbox, "put_nowait", lambda item: captured.append(item))

    state = msn._state("rate-session")
    for index in range(15):
        msn._dispatch("rate-session", state, f"msg-{index}")

    assert len(captured) == 10
    assert state["suppressed"] == 5

    captured.clear()
    state["sent"].clear()  # simulate the 60s window opening
    msn._dispatch("rate-session", state, "next")

    assert len(captured) == 1
    assert "另有 5 条" in captured[0][1]
    assert state["suppressed"] == 0


def test_non_feishu_platform_is_skipped(monkeypatch):
    captured: list[tuple[str, str]] = []
    monkeypatch.setattr(msn, "resolve_chat_id", lambda sid: "oc_test")
    monkeypatch.setattr(msn, "_ensure_worker", lambda: None)
    monkeypatch.setattr(msn._outbox, "put_nowait", lambda item: captured.append(item))

    state = msn._state("cli-session")
    state["platform"] = "cli"
    msn._dispatch("cli-session", state, "hello")

    assert captured == []


def test_missing_fields_do_not_raise(sent):
    msn.on_post_api_request(session_id="", model="m", provider="p")
    msn.on_post_api_request(session_id="s", model="", provider="p")
    msn.on_api_request_error(session_id="", model="m", provider="p")

    assert sent == []


@pytest.mark.parametrize("enabled", ["0", "false", "no", "off"])
def test_disabled_switch_suppresses_everything(sent, monkeypatch, enabled):
    monkeypatch.setenv("MODEL_WATCH_ENABLED", enabled)
    post()
    post(model=FALLBACK[0], provider=FALLBACK[1])

    assert sent == []


def test_session_starting_on_fallback_reports_recovery(sent):
    """A session born on a fallback route: returning to the primary is a recovery."""
    post(model=FALLBACK[0], provider=FALLBACK[1])
    post()

    assert len(sent) == 1
    assert "已切回主模型" in sent[0][1]
    assert "已切换" not in sent[0][1]


def test_session_re_pins_primary_once_config_is_readable(sent, monkeypatch):
    """A session primed during a broken config re-baselines when it heals.

    The first observed route becomes the baseline while the config is
    unreadable; the baseline is re-pinned on the next call once the config
    reads, so the move to the real primary is reported (honestly labelled as
    a switch: the user never saw a fallback notice for this session).
    """
    monkeypatch.setattr(msn, "configured_primary", lambda: None)
    post(model=FALLBACK[0], provider=FALLBACK[1])   # observed baseline = fallback route
    monkeypatch.setattr(msn, "configured_primary", lambda: PRIMARY)
    post(model=FALLBACK[0], provider=FALLBACK[1])   # same route: silent re-pin
    post()                                          # to the configured primary

    assert len(sent) == 1
    text = sent[0][1]
    assert "已切换" in text
    assert "已切回主模型" not in text
    assert FALLBACK[0] in text and PRIMARY[0] in text


def test_session_state_is_capped():
    for index in range(msn._MAX_SESSIONS + 20):
        msn._state(f"s-{index}")

    assert len(msn._sessions) == msn._MAX_SESSIONS
    assert "s-0" not in msn._sessions                      # oldest evicted
    assert f"s-{msn._MAX_SESSIONS + 19}" in msn._sessions  # newest kept
    assert msn._state("s-0")["current"] is None            # evicted state re-primes


def test_concurrent_dispatch_respects_the_rate_window(monkeypatch):
    """Turn thread and flush timer can dispatch at once; the cap must hold."""
    captured: list[tuple[str, str]] = []
    monkeypatch.setenv("MODEL_WATCH_RATE_PER_MIN", "10")
    monkeypatch.setattr(msn, "resolve_chat_id", lambda sid: "oc_race")
    monkeypatch.setattr(msn, "_ensure_worker", lambda: None)
    monkeypatch.setattr(msn._outbox, "put_nowait", lambda item: captured.append(item))

    st = msn._state("race-session")
    st["platform"] = "feishu"

    def spam():
        for index in range(8):
            msn._dispatch("race-session", st, f"m-{index}")

    threads = [threading.Thread(target=spam) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(captured) == 10
    assert st["suppressed"] == 6


def test_force_chat_with_invalid_prefix_is_ignored(monkeypatch):
    monkeypatch.setenv("MODEL_WATCH_FORCE_CHAT", "session-not-a-chat")
    captured: list[tuple[str, str]] = []
    monkeypatch.setattr(msn, "resolve_chat_id", lambda sid: "oc_real")
    monkeypatch.setattr(msn, "_ensure_worker", lambda: None)
    monkeypatch.setattr(msn._outbox, "put_nowait", lambda item: captured.append(item))

    st = msn._state("force-session")
    st["platform"] = "feishu"
    msn._dispatch("force-session", st, "hello")

    assert captured and captured[0][0] == "oc_real"


def test_error_hook_keeps_exception_type_not_message(sent):
    """Only the exception class is retained; upstream messages may hold secrets."""
    post()
    msn.on_api_request_error(
        session_id=SID, model=PRIMARY[0], provider=PRIMARY[1],
        status_code=None, reason="FailoverReason.timeout", retryable=True,
        platform="feishu", api_duration=31.7,
        error={"type": "ReadTimeout", "message": "Authorization: Bearer REDACTED"},
    )
    pending = msn._state(SID).get("pending_error")
    assert pending is not None
    assert pending["error_type"] == "ReadTimeout"
    assert "message" not in pending
    assert "REDACTED" not in str(pending)


def test_error_hook_clears_stale_exception_type(sent):
    """A later error without an exception class must not inherit the previous one."""
    post()
    msn.on_api_request_error(
        session_id=SID, model=PRIMARY[0], provider=PRIMARY[1],
        reason="FailoverReason.timeout", platform="feishu", api_duration=31.7,
        error={"type": "ReadTimeout", "message": "x"},
    )
    assert msn._state(SID)["pending_error"]["error_type"] == "ReadTimeout"
    msn.on_api_request_error(
        session_id=SID, model=PRIMARY[0], provider=PRIMARY[1],
        reason="FailoverReason.timeout", platform="feishu", api_duration=39.8,
    )
    assert msn._state(SID)["pending_error"]["error_type"] == ""
