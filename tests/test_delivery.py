"""Chat resolution and the Feishu HTTP client contract."""

from __future__ import annotations

import io
import json
import sqlite3
import urllib.error
from email.message import Message

import pytest

import model_switch_notify as msn


@pytest.fixture
def session_db(tmp_path, monkeypatch):
    db = tmp_path / "state.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, chat_id TEXT, source TEXT)")
    conn.executemany(
        "INSERT INTO sessions (id, chat_id, source) VALUES (?, ?, ?)",
        [
            ("feishu-session", "oc_abc123", "feishu"),
            ("openid-session", "ou_def456", "feishu"),
            ("oneshot-session", "local-xyz", "oneshot"),
            ("bad-prefix", "local-abc", "feishu"),
            ("empty-chat", None, "feishu"),
        ],
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(msn, "_candidate_state_dbs", lambda: [db])
    return db


@pytest.mark.parametrize(
    ("session_id", "expected"),
    [
        ("feishu-session", "oc_abc123"),
        ("openid-session", "ou_def456"),
        ("oneshot-session", None),
        ("bad-prefix", None),
        ("empty-chat", None),
        ("missing-session", None),
    ],
)
def test_resolve_chat_id(session_db, session_id, expected):
    assert msn.resolve_chat_id(session_id) == expected


def test_resolve_chat_id_caches(session_db, monkeypatch):
    calls = {"n": 0}
    real = msn.sqlite3.connect

    def counting(*args, **kwargs):
        calls["n"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(msn.sqlite3, "connect", counting)
    msn.resolve_chat_id("feishu-session")
    msn.resolve_chat_id("feishu-session")

    assert calls["n"] == 1


class _Response:
    def __init__(self, payload: dict):
        self._body = json.dumps(payload).encode()

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def feishu(monkeypatch):
    monkeypatch.setattr(
        msn, "feishu_env",
        lambda: {"FEISHU_APP_ID": "app", "FEISHU_APP_SECRET": "secret", "FEISHU_DOMAIN": "feishu"},
    )
    return msn.FeishuClient()


def test_send_text_posts_expected_payload(feishu, monkeypatch):
    seen: list[tuple[str, dict]] = []

    def urlopen(req, timeout=None):
        body = json.loads(req.data.decode())
        seen.append((req.full_url, body))
        if "tenant_access_token" in req.full_url:
            return _Response({"code": 0, "tenant_access_token": "tok-1", "expire": 7200})
        return _Response({"code": 0, "data": {"message_id": "om_reply"}})

    monkeypatch.setattr(msn.urllib.request, "urlopen", urlopen)

    assert feishu.send_text("oc_abc", "hello") == "om_reply"
    url, body = seen[-1]
    assert url.endswith("/open-apis/im/v1/messages?receive_id_type=chat_id")
    assert body["receive_id"] == "oc_abc"
    assert body["msg_type"] == "text"
    assert json.loads(body["content"]) == {"text": "hello"}


def test_token_is_cached_between_sends(feishu, monkeypatch):
    urls: list[str] = []

    def urlopen(req, timeout=None):
        urls.append(req.full_url)
        if "tenant_access_token" in req.full_url:
            return _Response({"code": 0, "tenant_access_token": "tok-1", "expire": 7200})
        return _Response({"code": 0, "data": {"message_id": "om_reply"}})

    monkeypatch.setattr(msn.urllib.request, "urlopen", urlopen)

    feishu.send_text("oc_abc", "one")
    feishu.send_text("oc_abc", "two")

    assert sum("tenant_access_token" in url for url in urls) == 1


def test_lark_domain_uses_larksuite(feishu, monkeypatch):
    monkeypatch.setattr(
        msn, "feishu_env",
        lambda: {"FEISHU_APP_ID": "app", "FEISHU_APP_SECRET": "secret", "FEISHU_DOMAIN": "lark"},
    )
    assert feishu._base_url() == "https://open.larksuite.com"


def test_http_error_is_reported_not_raised(feishu, monkeypatch):
    def urlopen(req, timeout=None):
        if "tenant_access_token" in req.full_url:
            return _Response({"code": 0, "tenant_access_token": "tok-1", "expire": 7200})
        raise urllib.error.HTTPError(
            req.full_url, 400, "Bad Request", Message(), io.BytesIO(b'{"code":230001}')
        )

    monkeypatch.setattr(msn.urllib.request, "urlopen", urlopen)

    assert feishu.send_text("oc_missing", "hello") is None


def test_missing_credentials_send_nothing(feishu, monkeypatch):
    monkeypatch.setattr(msn, "feishu_env", lambda: {})
    feishu._token, feishu._expires_at = None, 0.0

    assert feishu.tenant_token() is None
    assert feishu.send_text("oc_abc", "hello") is None


def test_rejected_token_is_retried_once(feishu, monkeypatch):
    state = {"token_calls": 0, "sends": 0}

    def urlopen(req, timeout=None):
        if "tenant_access_token" in req.full_url:
            state["token_calls"] += 1
            return _Response({"code": 0, "tenant_access_token": f"tok-{state['token_calls']}", "expire": 7200})
        state["sends"] += 1
        if state["sends"] == 1:
            return _Response({"code": 99991663, "msg": "token invalid"})
        return _Response({"code": 0, "data": {"message_id": "om_ok"}})

    monkeypatch.setattr(msn.urllib.request, "urlopen", urlopen)

    assert feishu.send_text("oc_abc", "hello") == "om_ok"
    assert state == {"token_calls": 2, "sends": 2}
