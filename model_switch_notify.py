"""Push a real-time Feishu notice when the model route changes mid-task.

Hermes buffers a fallback notice but only emits it at the end of a turn
(``agent/turn_final_response.py`` -> ``_emit_pending_fallback_notice``), so a
switch that happens during a long task stays invisible until the task is over.
This module watches the per-call hooks instead:

* ``post_api_request``  — the route that actually served a call (model/provider)
* ``api_request_error`` — why a call failed (status/reason/retryable)

and pushes one message to the *current* Feishu chat when the effective route
changes, when the primary route errors, or when it comes back.

Design constraints:

* Hook callbacks run on the turn thread, so they only touch in-memory state and
  a queue; every network call happens on a single background worker.
* An error is held for ``MODEL_WATCH_ERROR_HOLD_SECONDS`` so a switch that
  follows it can be merged into one message instead of two.
* Sends are not retried blindly: 4xx rejections and timeouts are final, since
  a resend could duplicate a notice Lark has already accepted.
* Credentials come from the profile ``.env`` (the gateway process does not
  export ``FEISHU_*``) and are never logged.
"""

from __future__ import annotations

import json
import logging
import os
import queue
import re
import sqlite3
import threading
import time
import tomllib
import urllib.error
import urllib.request
from collections import deque
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_HERMES_HOME = Path(os.environ.get("HERMES_HOME") or (Path.home() / ".hermes"))

_PLUGIN_ROOT = Path(__file__).resolve().parent
_CONFIG_PATH = _PLUGIN_ROOT / "config.toml"
_LOCALES_DIR = _PLUGIN_ROOT / "locales"
_DEFAULT_LANGUAGE = "en"
_SUPPORTED_LANGUAGES = ("en", "zh-CN", "zh-TW")

_RATE_WINDOW_SECONDS = 60.0
_DEDUPE_SECONDS = 60.0
_DEFAULT_HOLD_SECONDS = 8.0
_HTTP_TIMEOUT = 8.0
_MAX_SESSIONS = 256  # LRU cap on remembered sessions; gateway processes run for weeks

_FEISHU_ID_PREFIXES = ("oc_", "ou_", "on_")
# Tenant-token rejection codes: the only send error worth retrying with a fresh token.
_TOKEN_STALE_CODES = (99991661, 99991663, 99991668)


# --------------------------------------------------------------------------- #
# environment / profile resolution
# --------------------------------------------------------------------------- #


_config_lock = threading.Lock()
_config_cache: dict[str, Any] | None = None


def _load_config_file() -> dict[str, Any]:
    """Read the ``[notify]`` table from the plugin's local config.toml.

    Hook callbacks run on the API request path, so a missing, unreadable or
    malformed file degrades to defaults with a warning instead of raising.
    """
    if not _CONFIG_PATH.is_file():
        return {}
    try:
        data = tomllib.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - config must never break the hook
        logger.warning("model-switch-notify: cannot read %s: %s", _CONFIG_PATH, exc)
        return {}
    section = data.get("notify")
    if not isinstance(section, dict):
        logger.warning("model-switch-notify: %s has no [notify] table", _CONFIG_PATH)
        return {}
    return section


def _config() -> dict[str, Any]:
    global _config_cache
    with _config_lock:
        if _config_cache is None:
            _config_cache = _load_config_file()
        return _config_cache


def reset_config_cache() -> None:
    """Test hook: re-read config.toml on the next access."""
    global _config_cache
    with _config_lock:
        _config_cache = None


def _as_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        raw = value.strip().lower()
        if raw in {"1", "true", "yes", "on"}:
            return True
        if raw in {"0", "false", "no", "off"}:
            return False
    return None


def _as_int(value: Any, minimum: int = 0) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number >= minimum else None


def _as_float(value: Any, minimum: float = 0.0) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number >= minimum else None


def _setting(name: str, env_name: str, coerce) -> Any:
    """An explicit env value wins over config.toml; invalid input falls through."""
    raw = os.environ.get(env_name)
    if raw is not None:
        value = coerce(raw)
        if value is not None:
            return value
        logger.warning("model-switch-notify: ignoring invalid %s=%r", env_name, raw)
        return None
    section = _config()
    if name in section:
        value = coerce(section[name])
        if value is not None:
            return value
        logger.warning("model-switch-notify: ignoring invalid config value %s=%r", name, section[name])
    return None


def _enabled() -> bool:
    value = _setting("enabled", "MODEL_WATCH_ENABLED", _as_bool)
    return True if value is None else value


def _dry_run() -> bool:
    value = _setting("dry_run", "MODEL_WATCH_DRY_RUN", _as_bool)
    return False if value is None else value


def _rate_limit() -> int:
    value = _setting("rate_per_min", "MODEL_WATCH_RATE_PER_MIN", lambda v: _as_int(v, 1))
    return 10 if value is None else value


def _hold_seconds() -> float:
    value = _setting("error_hold_seconds", "MODEL_WATCH_ERROR_HOLD_SECONDS", lambda v: _as_float(v, 0.0))
    return _DEFAULT_HOLD_SECONDS if value is None else value


def _force_chat() -> str:
    raw = os.environ.get("MODEL_WATCH_FORCE_CHAT")
    if raw is None:
        candidate = _config().get("force_chat", "")
        raw = candidate if isinstance(candidate, str) else ""
    return raw.strip()


_profile_home_lock = threading.Lock()
_profile_home_cache: Path | None = None


def profile_home() -> Path:
    """The Hermes profile this plugin serves.

    Order: ``HERMES_PROFILE`` -> a ``profiles/<name>/plugins`` path segment
    (installed layout) -> a symlink under ``profiles/*/plugins`` that points at
    this checkout (development layout) -> the default profile.
    """
    global _profile_home_cache
    with _profile_home_lock:
        if _profile_home_cache is not None:
            return _profile_home_cache

        name = os.environ.get("HERMES_PROFILE", "").strip()
        candidate = _HERMES_HOME / "profiles" / name if name else None
        if candidate and candidate.is_dir():
            _profile_home_cache = candidate
            return candidate

        # Keep the un-resolved path: a symlinked install must report the profile
        # it is mounted into, not the checkout it points at.
        raw = Path(__file__).absolute()
        for parent in raw.parents:
            if parent.parent.name == "profiles":
                _profile_home_cache = parent
                return parent

        try:
            real = Path(__file__).resolve().parent
            for link in (_HERMES_HOME / "profiles").glob("*/plugins/*"):
                if link.is_symlink() and link.resolve() == real:
                    _profile_home_cache = link.parents[1]
                    return _profile_home_cache
        except OSError:
            pass

        _profile_home_cache = _HERMES_HOME
        return _profile_home_cache


def reset_profile_home_cache() -> None:
    """Test hook: forget the cached profile directory."""
    global _profile_home_cache
    with _profile_home_lock:
        _profile_home_cache = None


# --------------------------------------------------------------------------- #
# dotenv / config
# --------------------------------------------------------------------------- #


def _read_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            values[key.strip()] = val.strip().strip('"').strip("'")
    except OSError:
        pass
    return values


_env_lock = threading.Lock()
_env_cache: dict[str, str] | None = None


def feishu_env() -> dict[str, str]:
    """First .env carrying an app id: the profile's own, then HERMES_HOME's."""
    global _env_cache
    with _env_lock:
        if _env_cache is not None:
            return _env_cache
        candidates = [profile_home() / ".env", _HERMES_HOME / ".env"]
        try:
            candidates += sorted(_HERMES_HOME.glob("profiles/*/.env"))
        except OSError:
            pass
        for path in candidates:
            vals = _read_dotenv(path)
            if vals.get("FEISHU_APP_ID") and vals.get("FEISHU_APP_SECRET"):
                _env_cache = vals
                return vals
        _env_cache = {}
        return _env_cache


def reset_env_cache() -> None:
    """Test hook: forget cached credentials."""
    global _env_cache
    with _env_lock:
        _env_cache = None


def _norm_model(value: Any) -> str:
    """Comparable model identity: provider prefix and vendor case are noise."""
    return str(value or "").strip().lower().rsplit("/", 1)[-1]


def _norm_provider(value: Any) -> str:
    return str(value or "").strip().lower()


_primary_lock = threading.Lock()
_primary_cache: tuple[str, str] | None | bool = False


def configured_primary() -> tuple[str, str] | None:
    """The profile's configured route, used to recognise a recovery.

    A successful read is cached. A failure is *not*: caching it would pin the
    first observed route as "primary" for the whole process, so a transient
    read error or a config that gets fixed is picked up on the next call.
    """
    global _primary_cache
    with _primary_lock:
        if _primary_cache is not False:
            return _primary_cache  # type: ignore[return-value]
        found: tuple[str, str] | None = None
        try:
            import yaml  # declared in requirements.txt; ships with Hermes

            data = yaml.safe_load((profile_home() / "config.yaml").read_text(encoding="utf-8")) or {}
            model = data.get("model") or {}
            default, provider = model.get("default"), model.get("provider")
            if default and provider:
                found = (str(default), str(provider))
        except Exception as exc:  # noqa: BLE001 - a broken config must not break the hook
            logger.warning("model-switch-notify: cannot read the configured route: %s", exc)
        if found is not None:
            _primary_cache = found
        return found


def reset_primary_cache() -> None:
    """Test hook: re-read the configured primary route."""
    global _primary_cache
    with _primary_lock:
        _primary_cache = False


# --------------------------------------------------------------------------- #
# session -> chat_id
# --------------------------------------------------------------------------- #

_chat_lock = threading.Lock()
_chat_cache: dict[str, str | None] = {}


def _candidate_state_dbs() -> list[Path]:
    out = [profile_home() / "state.db", _HERMES_HOME / "state.db"]
    try:
        out += sorted(_HERMES_HOME.glob("profiles/*/state.db"))
    except OSError:
        pass
    seen: set[str] = set()
    unique: list[Path] = []
    for path in out:
        key = str(path)
        if key not in seen and path.exists():
            seen.add(key)
            unique.append(path)
    return unique


def _is_feishu_target(chat_id: Any, source: Any) -> bool:
    """A Feishu conversation id is `oc_`/`ou_`/`on_`; CLI rows store the session id."""
    return (
        bool(chat_id)
        and str(source or "") == "feishu"
        and str(chat_id).startswith(_FEISHU_ID_PREFIXES)
    )


def resolve_chat_id(session_id: str) -> str | None:
    if not session_id:
        return None
    with _chat_lock:
        if session_id in _chat_cache:
            return _chat_cache[session_id]
    found: str | None = None
    for db in _candidate_state_dbs():
        try:
            conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=1.0)
            try:
                row = conn.execute(
                    "SELECT chat_id, source FROM sessions WHERE id = ? AND chat_id IS NOT NULL LIMIT 1",
                    (session_id,),
                ).fetchone()
            finally:
                conn.close()
            if row and _is_feishu_target(row[0], row[1]):
                found = str(row[0])
                break
        except Exception as exc:  # noqa: BLE001 - a locked/gone DB is not fatal
            logger.debug("model-switch-notify: chat lookup failed in %s: %s", db, exc)
    if found is not None:
        with _chat_lock:
            _chat_cache[session_id] = found
    # A miss is deliberately not cached: a locked or half-written DB must not
    # silence a session for the rest of the process lifetime.
    return found


def reset_chat_cache() -> None:
    """Test hook: forget resolved chat ids."""
    with _chat_lock:
        _chat_cache.clear()


# --------------------------------------------------------------------------- #
# Feishu client
# --------------------------------------------------------------------------- #


class FeishuClient:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._token: str | None = None
        self._expires_at = 0.0

    def _base_url(self) -> str:
        domain = (feishu_env().get("FEISHU_DOMAIN") or "feishu").strip().lower()
        return "https://open.larksuite.com" if domain == "lark" else "https://open.feishu.cn"

    def tenant_token(self) -> str | None:
        with self._lock:
            if self._token and time.time() < self._expires_at:
                return self._token
            env = feishu_env()
            app_id, secret = env.get("FEISHU_APP_ID"), env.get("FEISHU_APP_SECRET")
            if not (app_id and secret):
                logger.warning("model-switch-notify: FEISHU_APP_ID/SECRET missing in profile .env")
                return None
            body = json.dumps({"app_id": app_id, "app_secret": secret}).encode()
            req = urllib.request.Request(
                f"{self._base_url()}/open-apis/auth/v3/tenant_access_token/internal",
                data=body,
                headers={"Content-Type": "application/json; charset=utf-8"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:
                    data = json.loads(resp.read().decode("utf-8", "replace"))
            except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
                logger.warning("model-switch-notify: tenant token request failed: %s", exc)
                return None
            token = data.get("tenant_access_token")
            if data.get("code") != 0 or not token:
                logger.warning("model-switch-notify: tenant token rejected: code=%s msg=%s",
                               data.get("code"), data.get("msg"))
                return None
            self._token = str(token)
            self._expires_at = time.time() + max(60, int(data.get("expire", 7200)) - 60)
            return self._token

    def send_text(self, chat_id: str, text: str) -> str | None:
        payload = {
            "receive_id": chat_id,
            "msg_type": "text",
            "content": json.dumps({"text": text}, ensure_ascii=False),
        }
        for attempt in (1, 2):
            token = self.tenant_token()
            if not token:
                return None
            req = urllib.request.Request(
                f"{self._base_url()}/open-apis/im/v1/messages?receive_id_type=chat_id",
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                    "Authorization": f"Bearer {token}",
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:
                    data = json.loads(resp.read().decode("utf-8", "replace"))
                if data.get("code") == 0:
                    return (data.get("data") or {}).get("message_id")
                # A stale token is the one error worth retrying with a fresh one.
                if data.get("code") in _TOKEN_STALE_CODES and attempt == 1:
                    with self._lock:
                        self._token, self._expires_at = None, 0.0
                    continue
                logger.warning("model-switch-notify: send rejected: code=%s msg=%s",
                               data.get("code"), data.get("msg"))
                return None
            except urllib.error.HTTPError as exc:
                detail = ""
                try:
                    detail = exc.read().decode("utf-8", "replace")[:300]
                except Exception:  # noqa: BLE001 - diagnostics only
                    pass
                logger.warning("model-switch-notify: send HTTP %s (attempt %s): %s",
                               exc.code, attempt, detail)
                if exc.code >= 500 and attempt == 1:
                    continue  # server-side hiccup: one retry can help
                return None  # other 4xx: the request itself is wrong, a retry cannot fix it
            except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
                logger.warning("model-switch-notify: send failed (attempt %s): %s", attempt, exc)
                # A timeout may mean Feishu already accepted the message: resending
                # would duplicate it (Lark has no idempotency key for sends). An
                # unparsable body means the server answered too (a proxy can return
                # 200 with a non-JSON page), so it is equally final.
                timed_out = isinstance(getattr(exc, "reason", exc), TimeoutError)
                unparsable_body = isinstance(exc, ValueError)
                if attempt == 1 and not timed_out and not unparsable_body:
                    continue  # connection-level failure: one retry
                return None
        return None


client = FeishuClient()

_outbox: "queue.Queue[tuple[str, str]]" = queue.Queue(maxsize=200)
_worker_lock = threading.Lock()
_worker: threading.Thread | None = None


def _worker_loop() -> None:
    while True:
        chat_id, text = _outbox.get()
        try:
            if _dry_run():
                logger.info("model-switch-notify[dry-run]: would send to %s: %s",
                            chat_id, text.replace("\n", " | "))
            else:
                message_id = client.send_text(chat_id, text)
                if message_id:
                    logger.info("model-switch-notify: sent %s to %s", message_id, chat_id)
        except Exception as exc:  # noqa: BLE001 - the worker must never die
            logger.warning("model-switch-notify: worker error: %s", exc)
        finally:
            _outbox.task_done()


def _ensure_worker() -> None:
    global _worker
    with _worker_lock:
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_worker_loop, name="model-switch-notify", daemon=True)
            _worker.start()


# --------------------------------------------------------------------------- #
# per-session state
# --------------------------------------------------------------------------- #

_lock = threading.Lock()
_sessions: dict[str, dict[str, Any]] = {}


def _state(session_id: str) -> dict[str, Any]:
    st = _sessions.get(session_id)
    if st is not None:
        # LRU touch so an active session survives the cap below.
        _sessions.pop(session_id, None)
        _sessions[session_id] = st
        return st
    st = {
        "current": None,          # route that last served a call
        "primary": None,          # configured route (or first observed)
        "primary_source": None,   # "config" once authoritative, else "observed"
        "in_fallback": False,
        "announced_fallback": False,  # a switch notice actually reached the user
        "platform": "",           # surface of the last hook (feishu / cli / ...)
        "sent": deque(),          # timestamps for the rate window
        "suppressed": 0,
        "last_switch_key": None,
        "last_switch_at": 0.0,
        "pending_error": None,    # dict: first_ts, count, status, reason, is_primary, seq, timer
        "error_seq": 0,
    }
    # Bound the bookkeeping: a long-lived gateway sees many sessions and an
    # evicted one simply re-primes from its next hook event.
    while len(_sessions) >= _MAX_SESSIONS:
        oldest = next(iter(_sessions))
        dropped = _sessions.pop(oldest)
        pending = dropped.get("pending_error")
        timer = pending.get("timer") if pending else None
        if timer is not None:
            timer.cancel()
        logger.debug("model-switch-notify: evicted session state %s (cap %s)", oldest, _MAX_SESSIONS)
    _sessions[session_id] = st
    return st


def reset_state() -> None:
    """Test hook: drop every per-session record."""
    with _lock:
        _sessions.clear()


# --------------------------------------------------------------------------- #
# localization
# --------------------------------------------------------------------------- #

_locale_lock = threading.Lock()
_locale_cache: dict[str, dict[str, str]] = {}


def _config_language() -> str:
    value = _config().get("language", _DEFAULT_LANGUAGE)
    return value if isinstance(value, str) and value.strip() else _DEFAULT_LANGUAGE


def _language() -> str:
    raw = os.environ.get("MODEL_WATCH_LANGUAGE")
    if raw is None:
        raw = _config_language()
    return _normalize_language(raw)


def _language_from_locale(raw: str) -> str | None:
    value = raw.split(".")[0].split("@")[0].strip().lower().replace("_", "-")
    if not value:
        return None
    if value.startswith("zh"):
        if any(tag in value for tag in ("tw", "hk", "mo", "hant")):
            return "zh-TW"
        return "zh-CN"
    if value.startswith("en"):
        return "en"
    return None


def _ui_language() -> str | None:
    """The Hermes profile's ``ui.language``, falling back to the global one."""
    try:
        import yaml

        home = profile_home()
        candidates = [home / "config.yaml"]
        if home.parent.name == "profiles":
            candidates.append(home.parent.parent / "config.yaml")
        for path in candidates:
            if not path.is_file():
                continue
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            ui = data.get("ui") if isinstance(data, dict) else None
            language = ui.get("language") if isinstance(ui, dict) else None
            if isinstance(language, str) and language.strip():
                resolved = _language_from_locale(language)
                if resolved:
                    return resolved
    except Exception as exc:  # noqa: BLE001 - detection is best-effort
        logger.debug("model-switch-notify: cannot read ui.language: %s", exc)
    return None


def _detect_language() -> str:
    detected = _ui_language()
    if detected:
        return detected
    for name in ("LC_ALL", "LC_MESSAGES", "LANG"):
        raw = os.environ.get(name)
        if raw:
            resolved = _language_from_locale(raw)
            if resolved:
                return resolved
    return _DEFAULT_LANGUAGE


def _normalize_language(value: Any) -> str:
    raw = str(value or "").strip().lower().replace("_", "-")
    if raw == "auto":
        return _detect_language()
    if raw in {"en", "en-us", "en-gb", "en-ca", "en-au", "en-nz"}:
        return "en"
    if raw in {"zh", "zh-cn", "zh-hans", "zh-sg", "zh-my"}:
        return "zh-CN"
    if raw in {"zh-tw", "zh-hk", "zh-mo", "zh-hant"}:
        return "zh-TW"
    logger.warning("model-switch-notify: unsupported language %r; using %s", value, _DEFAULT_LANGUAGE)
    return _DEFAULT_LANGUAGE


def _locale(language: str) -> dict[str, str]:
    with _locale_lock:
        cached = _locale_cache.get(language)
        if cached is not None:
            return cached
        data: dict[str, str] = {}
        path = _LOCALES_DIR / f"{language}.json"
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("locale file must contain a JSON object")
            data = {str(key): str(value) for key, value in raw.items()}
        except Exception as exc:  # noqa: BLE001 - fall back through the chain
            logger.warning("model-switch-notify: cannot load locale %s: %s", language, exc)
        _locale_cache[language] = data
        return data


def reset_locale_cache() -> None:
    """Test hook: drop cached locale files."""
    with _locale_lock:
        _locale_cache.clear()


def _fallback_chain(language: str) -> tuple[str, ...]:
    if language == "zh-TW":
        return ("zh-TW", "zh-CN", "en")
    if language == "zh-CN":
        return ("zh-CN", "en")
    return ("en",)


def _t(key: str, **kwargs: Any) -> str:
    for code in _fallback_chain(_language()):
        template = _locale(code).get(key)
        if template is None:
            continue
        try:
            return template.format(**kwargs)
        except (KeyError, IndexError, ValueError) as exc:
            logger.warning("model-switch-notify: bad placeholder in %s/%s: %s", code, key, exc)
    return key


def _route_label(model: Any, provider: Any) -> str:
    return _t("route.with_provider", model=model, provider=provider) if provider else str(model)


def _allow_send(st: dict[str, Any]) -> bool:
    now = time.time()
    window = st["sent"]
    while window and now - window[0] > _RATE_WINDOW_SECONDS:
        window.popleft()
    if len(window) >= _rate_limit():
        st["suppressed"] += 1
        return False
    window.append(now)
    return True


def _dispatch(session_id: str, st: dict[str, Any], text: str) -> None:
    """Enqueue a message if the chat resolves and the rate window allows it."""
    platform = str(st.get("platform") or "")
    force = _force_chat()
    if force and not force.startswith(_FEISHU_ID_PREFIXES):
        logger.warning("model-switch-notify: MODEL_WATCH_FORCE_CHAT is not a Feishu chat id; ignoring it")
        force = ""
    if platform and platform != "feishu" and not force:
        logger.debug("model-switch-notify: session %s runs on %s; no Feishu target", session_id, platform)
        return
    chat_id = force or resolve_chat_id(session_id)
    if not chat_id:
        logger.debug("model-switch-notify: no chat for session %s; dropping notice", session_id)
        return
    # The rate window and the suppressed counter are shared with concurrent
    # hook callbacks (turn thread + flush timer); mutate them under the lock so
    # two dispatches cannot both pass the limit check.
    with _lock:
        cur = _sessions.get(session_id) or st
        if not _allow_send(cur):
            logger.info("model-switch-notify: rate-limited (%s/min); suppressed=%s", _rate_limit(), cur["suppressed"])
            return
        if cur["suppressed"]:
            text = f"{text}\n{_t('suppressed', count=cur['suppressed'])}"
            cur["suppressed"] = 0
    _ensure_worker()
    try:
        _outbox.put_nowait((chat_id, text))
    except queue.Full:
        logger.warning("model-switch-notify: outbox full; dropping notice")


def _configured_stale_timeout(provider: str, model: str) -> float | None:
    """``providers.<id>[.models.<model>].stale_timeout_seconds``, if configured."""
    if not provider:
        return None
    try:
        import yaml

        data = yaml.safe_load((profile_home() / "config.yaml").read_text(encoding="utf-8")) or {}
    except Exception as exc:  # noqa: BLE001 - display detail only
        logger.debug("model-switch-notify: cannot read provider timeouts: %s", exc)
        return None
    providers = data.get("providers") if isinstance(data, dict) else None
    section = providers.get(provider) if isinstance(providers, dict) else None
    if not isinstance(section, dict):
        return None
    if model:
        models = section.get("models")
        model_config = models.get(model) if isinstance(models, dict) else None
        if isinstance(model_config, dict):
            value = _as_float(model_config.get("stale_timeout_seconds"), 0.0)
            if value is not None:
                return value
    return _as_float(section.get("stale_timeout_seconds"), 0.0)


def _watchdog_threshold(provider: str, model: str) -> float | None:
    explicit = _configured_stale_timeout(provider, model)
    if explicit is not None:
        return explicit
    from_env = _as_float(os.environ.get("HERMES_STREAM_STALE_TIMEOUT"), 0.0)
    return from_env if from_env is not None else 180.0


def _timeout_text(text: str, pending: dict[str, Any]) -> str:
    duration = pending.get("duration")
    if isinstance(duration, bool) or not isinstance(duration, (int, float)) or duration <= 0:
        return text
    threshold = _watchdog_threshold(
        str(pending.get("provider") or ""), str(pending.get("model") or "")
    )
    if threshold is None:
        return _t("timeout_detail_no_threshold", reason=text, duration=f"{duration:.1f}")
    return _t(
        "timeout_detail",
        reason=text,
        duration=f"{duration:.1f}",
        threshold=f"{threshold:g}",
    )


def _reason_text(pending: dict[str, Any]) -> str:
    parts: list[str] = []
    status = pending.get("status")
    reason = pending.get("reason")
    if status:
        parts.append(f"HTTP {status}")
    if reason:
        parts.append(str(reason))
    if pending.get("count", 1) > 1:
        parts.append(_t("reason.retries", count=pending["count"]))
    text = " · ".join(parts) if parts else _t("reason.failed")
    if str(reason or "").strip().lower() == "timeout":
        text = _timeout_text(text, pending)
    return text


def _switch_message(from_route, to_route, pending) -> str:
    lines = [_t("switch.title")]
    if pending:
        lines.append(_t("switch.reason", reason=_reason_text(pending)))
    lines.append(_t("switch.from", route=_route_label(*from_route)))
    lines.append(_t("switch.to", route=_route_label(*to_route)))
    lines.append(_t("time", time=time.strftime("%Y-%m-%d %H:%M:%S")))
    return "\n".join(lines)


def _error_message(route, pending, is_primary: bool = True, recovered: bool = False) -> str:
    title = _t("error.title_primary" if is_primary else "error.title_current")
    lines = [title, _t("error.model", route=_route_label(*route))]
    lines.append(_t("error.detail", reason=_reason_text(pending)))
    lines.append(_t("error.recovered") if recovered else _t("error.retrying"))
    lines.append(_t("time", time=time.strftime("%Y-%m-%d %H:%M:%S")))
    return "\n".join(lines)


def _recovery_message(route) -> str:
    return "\n".join([
        _t("recovery.title"),
        _t("error.model", route=_route_label(*route)),
        _t("time", time=time.strftime("%Y-%m-%d %H:%M:%S")),
    ])


def _take_pending(st: dict[str, Any]) -> dict[str, Any] | None:
    """Detach a held error and stop its flush timer (a switch or retry ended it)."""
    pending = st["pending_error"]
    if pending is None:
        return None
    st["pending_error"] = None
    timer = pending.get("timer")
    if timer is not None:
        timer.cancel()
    return pending


def _flush_error(session_id: str, seq: int) -> None:
    """Hold window expired: the error did not become a switch, so report it alone."""
    with _lock:
        st = _sessions.get(session_id)
        if st is None:
            return
        held = st["pending_error"]
        if held is None or held["seq"] != seq:
            return
        pending = _take_pending(st)
        if pending is None:  # unreachable under the lock; keeps type-checkers calm
            return
        route = st["current"]
        text = _error_message(route, pending, bool(pending.get("is_primary", True))) if route else None
    if text:
        _dispatch(session_id, st, text)


# --------------------------------------------------------------------------- #
# hooks
# --------------------------------------------------------------------------- #


def on_post_api_request(**kwargs: Any) -> None:
    if not _enabled():
        return
    session_id = str(kwargs.get("session_id") or "")
    model, provider = kwargs.get("model"), kwargs.get("provider")
    if not session_id or not model:
        return
    route = (str(model), str(provider or ""))
    notice: str | None = None

    with _lock:
        st = _state(session_id)
        st["platform"] = str(kwargs.get("platform") or st.get("platform") or "")
        if st["primary"] is None or st.get("primary_source") != "config":
            # Retry the config while the baseline is not authoritative: a
            # session that primed during a broken config re-pins as soon as
            # the config becomes readable, instead of keeping the first
            # observed route as "primary" for its whole lifetime.
            configured = configured_primary()
            if configured is not None:
                st["primary"] = configured
                st["primary_source"] = "config"
                if st["current"] is not None:
                    cur = st["current"]
                    st["in_fallback"] = not (
                        _norm_model(cur[0]) == _norm_model(configured[0])
                        and _norm_provider(cur[1]) == _norm_provider(configured[1])
                    )
            elif st["primary"] is None:
                st["primary"] = route
                st["primary_source"] = "observed"
        primary = st["primary"]
        is_primary = (
            _norm_model(route[0]) == _norm_model(primary[0])
            and _norm_provider(route[1]) == _norm_provider(primary[1])
        )
        if st["current"] is None:
            st["current"] = route
            st["in_fallback"] = not is_primary
            # A session that *starts* on a fallback route counts as announced:
            # returning to the primary later is a recovery, not a fresh switch.
            st["announced_fallback"] = not is_primary
            return
        if st["current"] == route:
            # A success on the same route closes a held error: report it as a
            # retry that worked, which is the only "error, no switch" evidence.
            pending = _take_pending(st)
            if pending:
                notice = _error_message(
                    route, pending, bool(pending.get("is_primary", True)), recovered=True
                )
        else:
            from_route, st["current"] = st["current"], route
            now = time.time()
            key = (from_route, route)
            dedupe = st["last_switch_key"] == key and now - st["last_switch_at"] < _DEDUPE_SECONDS
            st["last_switch_key"], st["last_switch_at"] = key, now
            pending = _take_pending(st)
            was_fallback = st["in_fallback"]
            st["in_fallback"] = not is_primary
            if dedupe:
                return
            if is_primary and was_fallback and st["announced_fallback"]:
                # A new episode must be able to report the same switch again.
                st["last_switch_key"] = None
                st["announced_fallback"] = False
                notice = _recovery_message(route)
            else:
                st["announced_fallback"] = True
                notice = _switch_message(from_route, route, pending)

    if notice:
        _dispatch(session_id, st, notice)


def on_api_request_error(**kwargs: Any) -> None:
    if not _enabled():
        return
    session_id = str(kwargs.get("session_id") or "")
    model, provider = kwargs.get("model"), kwargs.get("provider")
    if not session_id or not model:
        return
    route = (str(model), str(provider or ""))

    with _lock:
        st = _state(session_id)
        st["platform"] = str(kwargs.get("platform") or st.get("platform") or "")
        if st["current"] is None:
            st["current"] = route
        if st["current"] != route:
            return  # a different route (e.g. an auxiliary call) is not our business
        primary = st["primary"]
        is_primary = bool(primary) and (
            _norm_model(primary[0]) == _norm_model(route[0])
            and _norm_provider(primary[1]) == _norm_provider(route[1])
        )

        st["error_seq"] += 1
        seq = st["error_seq"]
        pending = st["pending_error"]
        if pending is None:
            pending = {"first_ts": time.time(), "count": 0, "seq": seq, "is_primary": is_primary}
            st["pending_error"] = pending
            # Remember the handle so a consuming switch/retry can cancel it;
            # the seq guard in _flush_error stays as the backstop.
            timer = threading.Timer(max(0.1, _hold_seconds()), _flush_error, args=(session_id, seq))
            pending["timer"] = timer
            timer.start()
        pending["count"] += 1
        pending["status"] = kwargs.get("status_code")
        pending["duration"] = kwargs.get("api_duration")
        pending["provider"] = route[1]
        pending["model"] = route[0]
        reason = kwargs.get("reason")
        if reason:
            pending["reason"] = re.sub(r"^[A-Za-z_]+\.", "", str(reason))
        pending["retryable"] = kwargs.get("retryable")
        pending["is_primary"] = is_primary


def register(ctx) -> None:
    ctx.register_hook("post_api_request", on_post_api_request)
    ctx.register_hook("api_request_error", on_api_request_error)
    logger.info("model-switch-notify: hooks registered")
