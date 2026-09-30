"""
The Full LLM Exchange Recorder: what CreditProbe actually sent, and what came back.

One recorder for every model call in CreditProbe -- the Advanced Cockpit
analyst, What-If turns (which ARE Cockpit turns), Lenses prompt handling and the
AI Model Lab. It persists the sanitized, model-visible exchange of each call:

* the CANONICAL request -- the exact keyword arguments CreditProbe handed its
  provider adapter: system blocks, the ordered message history (prior
  assistant blocks, tool calls, tool results, validator feedback), full tool
  definitions and schemas, tool choice, output configuration, token limits,
  model, purpose, timeout;
* the ADAPTER request -- the provider-native payload the adapter built from it
  (for Anthropic this is the `messages.create` body; for an open-weight
  OpenAI-compatible endpoint it is the translated chat-completions body);
* the RAW provider response, where the SDK exposes it safely;
* the NORMALIZED response CreditProbe continued with: assistant blocks, text,
  tool calls with exact arguments, stop reason, usage, timing, model identity.

What it refuses to be
---------------------
It is PASSIVE. It never reassembles a prompt, never re-orders a message, never
adds a model call and never alters the arguments or the result: the proxy hands
the provider the very objects it was given and returns the very object it got
back. Recording happens on deep copies, and any failure to record is logged and
swallowed -- observability that can break a run is not observability.

It never persists a secret. API keys, bearer tokens, authorization headers,
passwords, cookies and credential-shaped strings are redacted by key and by
value before anything is written. Ordinary telemetry -- `input_tokens`,
`max_tokens`, `cache_read_input_tokens` -- is NOT a secret and stays visible:
redacting every key containing "token" would blind the very review this exists
for.

It never records hidden reasoning. It records what the application sent and
what the provider returned in the response body; a provider's private
chain-of-thought is not part of either, and a `thinking` content block, if a
provider ever returns one, is replaced by a marker stating its type and size.

Records are immutable: one INSERT per call once the call has finished, never an
UPDATE, and every record carries SHA-256 hashes of its sanitized parts so a
later reader can prove what they are looking at is what was stored.
"""

from __future__ import annotations

import contextvars
import copy
import dataclasses
import hashlib
import json
import logging
import os
import re
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

logger = logging.getLogger(__name__)

#: The environment switch. OFF restores the accepted behaviour exactly: `bind`
#: returns the provider object it was given, untouched.
FLAG = "COCKPIT_V4_LLM_EXCHANGE_TRACE"

#: Bumped when the stored shape changes. A reader refuses a version it does not
#: know rather than guessing at fields.
RECORD_VERSION = 1

REDACTED = "[REDACTED]"

#: Keys whose VALUE is a secret, whatever it looks like. Matched on the
#: normalised key (lower case, `-` -> `_`).
_SECRET_KEYS = frozenset({
    "api_key", "apikey", "x_api_key", "authorization", "proxy_authorization",
    "password", "passwd", "secret", "client_secret", "access_token",
    "refresh_token", "id_token", "session_token", "auth_token", "bearer",
    "cookie", "set_cookie", "credential", "credentials", "private_key",
    "aws_secret_access_key", "aws_session_token", "anthropic_api_key",
    "openai_api_key", "cockpit_anthropic_api_key", "authorization_header",
})

#: Keys that merely CONTAIN a secret word but are telemetry, not secrets.
_TELEMETRY_KEYS = frozenset({
    "input_tokens", "output_tokens", "max_tokens", "max_output_tokens",
    "cache_read_input_tokens", "cache_creation_input_tokens",
    "cache_read_tokens", "cache_write_tokens", "total_tokens",
    "prompt_tokens", "completion_tokens", "counted_tokens",
    "estimated_tokens", "tokens", "token_count",
})

#: Value shapes that are credentials wherever they appear, including inside
#: free text a user typed or a tool returned.
_SECRET_VALUES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("anthropic_key", re.compile(r"sk-ant-[A-Za-z0-9_\-]{8,}")),
    ("openai_key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_\-]{20,}")),
    ("bearer_token", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=\-]{12,}")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("slack_token", re.compile(r"\bxox[abpors]-[A-Za-z0-9\-]{10,}")),
    ("private_key_block",
     re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*"
                r"PRIVATE KEY-----")),
    ("password_assignment",
     re.compile(r"(?i)\b(password|passwd|api[_-]?key|secret)\s*[=:]\s*"
                r"[^\s,;\"']{6,}")),
)


# ---- sanitisation -----------------------------------------------------------

def _norm_key(key: Any) -> str:
    return str(key).strip().lower().replace("-", "_")


def is_secret_key(key: Any) -> bool:
    name = _norm_key(key)
    if name in _TELEMETRY_KEYS:
        return False
    if name in _SECRET_KEYS:
        return True
    return name.endswith(("_api_key", "_secret", "_password", "_bearer"))


def scrub_text(text: str, path: str, found: list[dict[str, str]]) -> str:
    """Replace every credential-shaped substring, recording where, never what."""
    out = text
    for reason, pattern in _SECRET_VALUES:
        if pattern.search(out):
            out = pattern.sub(REDACTED, out)
            found.append({"path": path, "reason": reason})
    return out


def sanitize(value: Any, *, path: str = "$",
             found: list[dict[str, str]] | None = None) -> Any:
    """A JSON-safe deep copy with every secret replaced by `[REDACTED]`.

    Order is preserved -- dict insertion order and list order are exactly the
    order the request was built in, because the order IS part of what the
    model saw. Non-JSON objects (SDK blocks) are converted through their own
    `model_dump`/`to_dict` or dataclass fields, never through `repr`, so a
    redaction cannot be bypassed by an object that stringifies its key.
    """
    if found is None:
        found = []
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return scrub_text(value, path, found)
    if isinstance(value, bytes):
        return f"<{len(value)} bytes>"
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            child = f"{path}.{key}"
            if is_secret_key(key):
                out[str(key)] = REDACTED
                found.append({"path": child, "reason": "secret_key"})
                continue
            out[str(key)] = sanitize(item, path=child, found=found)
        return out
    if isinstance(value, (list, tuple)):
        return [sanitize(item, path=f"{path}[{i}]", found=found)
                for i, item in enumerate(value)]
    plain = to_plain(value)
    if plain is value:  # nothing better than a string representation
        return scrub_text(str(value), path, found)
    return sanitize(plain, path=path, found=found)


def to_plain(value: Any) -> Any:
    """An SDK object as plain data, without going through `repr`."""
    for attribute in ("model_dump",):
        method = getattr(value, attribute, None)
        if callable(method):
            try:
                return method(mode="json")
            except TypeError:
                return method()
            except Exception:  # noqa: BLE001 - fall through to the next shape
                pass
    for attribute in ("to_dict", "dict"):
        method = getattr(value, attribute, None)
        if callable(method):
            try:
                return method()
            except Exception:  # noqa: BLE001
                pass
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: getattr(value, f.name)
                for f in dataclasses.fields(value)}
    if hasattr(value, "__dict__") and not isinstance(value, type):
        return {k: v for k, v in vars(value).items() if not k.startswith("_")}
    return value


def strip_hidden_reasoning(blocks: Any) -> Any:
    """Replace a `thinking` block's content by a marker naming its type and size.

    CreditProbe does not request extended thinking; this exists so that a
    future provider or model setting cannot make the recorder the place hidden
    reasoning gets persisted and displayed.
    """
    if not isinstance(blocks, list):
        return blocks
    out = []
    for block in blocks:
        if isinstance(block, dict) and block.get("type") in (
                "thinking", "redacted_thinking", "reasoning"):
            size = len(json.dumps(block, ensure_ascii=False, default=str))
            out.append({"type": block.get("type"),
                        "withheld": "hidden reasoning is never recorded",
                        "bytes": size})
        else:
            out.append(block)
    return out


def canonical_bytes(value: Any) -> bytes:
    """The one serialisation hashes are taken over: insertion order kept."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"),
                      default=str).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


# ---- context composition --------------------------------------------------

#: Local token estimates are labelled estimates. Four bytes per token is the
#: conventional rough figure for English + JSON; the exact billed number is
#: the provider's `input_tokens`, reported beside it.
BYTES_PER_TOKEN_ESTIMATE = 4.0


def _size(value: Any) -> int:
    if isinstance(value, str):
        return len(value.encode("utf-8"))
    return len(canonical_bytes(value))


def composition(request: dict[str, Any]) -> dict[str, Any]:
    """Where the bytes of one request sit: system, tools, and each message kind.

    Every figure is a MEASURED byte count of the sanitized request. Token
    figures per component are ESTIMATES and say so; the provider does not
    break its count down by component.
    """
    parts: list[dict[str, Any]] = []

    def add(component: str, detail: str, size: int) -> None:
        parts.append({"component": component, "detail": detail, "bytes": size,
                      "estimated_tokens": int(round(
                          size / BYTES_PER_TOKEN_ESTIMATE)),
                      "token_basis": "ESTIMATE (bytes / 4)"})

    system = request.get("system")
    if isinstance(system, list):
        for i, block in enumerate(system):
            text = block.get("text", "") if isinstance(block, dict) else block
            add("system", f"system block {i + 1}", _size(text))
    elif system:
        add("system", "system text", _size(system))
    for tool in request.get("tools") or []:
        name = tool.get("name", "?") if isinstance(tool, dict) else "?"
        add("tool_schema", name, _size(tool))
    for i, message in enumerate(request.get("messages") or []):
        role = message.get("role", "?") if isinstance(message, dict) else "?"
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(content, str):
            add(f"{role}_text", f"message {i + 1}", _size(content))
            continue
        for block in content or []:
            kind = block.get("type", "?") if isinstance(block, dict) else "?"
            label = {"text": f"{role}_text", "tool_use": "tool_call",
                     "tool_result": "tool_result"}.get(kind, f"{role}_{kind}")
            add(label, f"message {i + 1}", _size(block))
    for key in ("tool_choice", "output_config"):
        if request.get(key):
            add(key, key, _size(request[key]))
    totals: dict[str, int] = {}
    for part in parts:
        totals[part["component"]] = totals.get(part["component"], 0) + \
            part["bytes"]
    return {"parts": parts, "totals_bytes": totals,
            "total_bytes": sum(totals.values()),
            "message_count": len(request.get("messages") or []),
            "tool_count": len(request.get("tools") or [])}


# ---- transmitted-data measurement ------------------------------------------

def transmitted_rows(request: dict[str, Any]) -> dict[str, Any]:
    """How much PORTFOLIO DATA actually reached the model in this request.

    Tool results are where rows travel. Each one is parsed (when it is JSON)
    and every list of row objects under a `rows`/`sample`/`preview` key is
    counted. Bytes are measured whatever the payload is.
    """
    results = []
    for message in request.get("messages") or []:
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, list):
            continue
        for block in content:
            if not (isinstance(block, dict)
                    and block.get("type") == "tool_result"):
                continue
            body = block.get("content")
            text = body if isinstance(body, str) else json.dumps(
                body, ensure_ascii=False, default=str)
            rows = 0
            try:
                parsed = json.loads(text) if isinstance(text, str) else text
            except ValueError:
                parsed = None
            rows = _count_rows(parsed)
            results.append({"tool_use_id": block.get("tool_use_id", ""),
                            "bytes": _size(text), "rows": rows})
    return {"tool_results": len(results),
            "rows": sum(r["rows"] for r in results),
            "bytes": sum(r["bytes"] for r in results),
            "detail": results}


def _count_rows(value: Any, depth: int = 0) -> int:
    if depth > 6:
        return 0
    if isinstance(value, dict):
        total = 0
        for key, item in value.items():
            if (key in ("rows", "sample", "preview", "records", "data")
                    and isinstance(item, list)
                    and all(isinstance(r, (dict, list)) for r in item)):
                total += len(item)
            else:
                total += _count_rows(item, depth + 1)
        return total
    if isinstance(value, list):
        return sum(_count_rows(item, depth + 1) for item in value)
    return 0


# ---- the store ----------------------------------------------------------------

_DDL = """
CREATE TABLE IF NOT EXISTS llm_exchanges (
    exchange_id      TEXT PRIMARY KEY,
    record_version   INTEGER NOT NULL,
    run_id           TEXT NOT NULL DEFAULT '',
    thread_id        TEXT NOT NULL DEFAULT '',
    tenant_id        TEXT NOT NULL DEFAULT '',
    domain_id        TEXT NOT NULL DEFAULT '',
    surface          TEXT NOT NULL DEFAULT '',
    seq              INTEGER NOT NULL DEFAULT 0,
    purpose          TEXT NOT NULL DEFAULT '',
    role             TEXT NOT NULL DEFAULT '',
    provider         TEXT NOT NULL DEFAULT '',
    adapter          TEXT NOT NULL DEFAULT '',
    requested_model  TEXT NOT NULL DEFAULT '',
    resolved_model   TEXT NOT NULL DEFAULT '',
    status           TEXT NOT NULL,
    error            TEXT NOT NULL DEFAULT '',
    stop_reason      TEXT NOT NULL DEFAULT '',
    request_id       TEXT NOT NULL DEFAULT '',
    started_at       REAL NOT NULL,
    ended_at         REAL NOT NULL,
    provider_ms      INTEGER NOT NULL DEFAULT 0,
    replay_of        TEXT NOT NULL DEFAULT '',
    body             TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS llm_exchanges_run ON llm_exchanges(run_id, seq);
CREATE INDEX IF NOT EXISTS llm_exchanges_model
    ON llm_exchanges(resolved_model, started_at);
CREATE TRIGGER IF NOT EXISTS llm_exchanges_immutable
    BEFORE UPDATE ON llm_exchanges
    BEGIN SELECT RAISE(ABORT, 'llm exchange records are immutable'); END;
"""


class ExchangeStore:
    """SQLite, one INSERT per finished call. Immutable by trigger, not by habit."""

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False,
                                     isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        if self.path != ":memory:":
            self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_DDL)

    def insert(self, record: dict[str, Any]) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO llm_exchanges (exchange_id, record_version, "
                "run_id, thread_id, tenant_id, domain_id, surface, seq, "
                "purpose, role, provider, adapter, requested_model, "
                "resolved_model, status, error, stop_reason, request_id, "
                "started_at, ended_at, provider_ms, replay_of, body) VALUES "
                "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (record["exchange_id"], RECORD_VERSION, record["run_id"],
                 record["thread_id"], record["tenant_id"],
                 record["domain_id"], record["surface"], record["seq"],
                 record["purpose"], record["role"], record["provider"],
                 record["adapter"], record["requested_model"],
                 record["resolved_model"], record["status"], record["error"],
                 record["stop_reason"], record["request_id"],
                 record["started_at"], record["ended_at"],
                 record["provider_ms"], record.get("replay_of", ""),
                 json.dumps(record, ensure_ascii=False, default=str)))

    def next_seq(self, run_id: str) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COALESCE(MAX(seq), 0) AS n FROM llm_exchanges "
                "WHERE run_id = ?", (run_id,)).fetchone()
        return int(row["n"]) + 1

    def for_run(self, run_id: str, *, tenant_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT body FROM llm_exchanges WHERE run_id = ? AND "
                "tenant_id = ? ORDER BY seq, started_at",
                (run_id, tenant_id)).fetchall()
        return [json.loads(r["body"]) for r in rows]

    def get(self, exchange_id: str, *, tenant_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT body FROM llm_exchanges WHERE exchange_id = ? AND "
                "tenant_id = ?", (exchange_id, tenant_id)).fetchone()
        return json.loads(row["body"]) if row else None

    def search(self, *, tenant_id: str, model: str = "", purpose: str = "",
               run_id: str = "", limit: int = 200) -> list[dict[str, Any]]:
        sql = ("SELECT exchange_id, run_id, thread_id, surface, seq, purpose, "
               "role, provider, adapter, requested_model, resolved_model, "
               "status, stop_reason, started_at, provider_ms, replay_of, "
               "domain_id FROM llm_exchanges WHERE tenant_id = ?")
        args: list[Any] = [tenant_id]
        for column, value in (("resolved_model", model), ("purpose", purpose),
                              ("run_id", run_id)):
            if value:
                sql += f" AND {column} = ?"
                args.append(value)
        sql += " ORDER BY started_at DESC LIMIT ?"
        args.append(max(1, min(int(limit), 1000)))
        with self._lock:
            rows = self._conn.execute(sql, args).fetchall()
        return [dict(r) for r in rows]

    def count(self) -> int:
        with self._lock:
            return int(self._conn.execute(
                "SELECT COUNT(*) FROM llm_exchanges").fetchone()[0])


_STORES: dict[str, ExchangeStore] = {}
_STORES_LOCK = threading.Lock()


def store_at(path: str | Path) -> ExchangeStore:
    key = str(path)
    with _STORES_LOCK:
        if key not in _STORES:
            _STORES[key] = ExchangeStore(key)
        return _STORES[key]


def store_path_for(cfg: Any) -> Path:
    """Beside the V4 state database, in the runtime directory the launcher owns."""
    state = Path(str(getattr(cfg, "state_database", "") or ""))
    if str(state) in ("", ".", ":memory:"):
        runtime = Path(str(getattr(cfg, "runtime_dir", "") or ".")).expanduser()
        return runtime / "state" / "llm_exchange.sqlite3"
    return state.with_name("llm_exchange.sqlite3")


def enabled() -> bool:
    return os.environ.get(FLAG, "").strip().lower() in ("1", "true", "yes",
                                                        "on")


# ---- the in-flight record -------------------------------------------------

@dataclasses.dataclass
class _Pending:
    """One call being observed. Adapters attach their stage through it."""

    adapter_requests: list[Any] = dataclasses.field(default_factory=list)
    raw_responses: list[Any] = dataclasses.field(default_factory=list)
    adapter: str = ""
    provider: str = ""
    translation: list[str] = dataclasses.field(default_factory=list)


_CURRENT: contextvars.ContextVar[_Pending | None] = contextvars.ContextVar(
    "creditprobe_llm_exchange", default=None)


def adapter_stage(*, adapter: str, provider: str = "",
                  request: Any = None, raw_response: Any = None,
                  translation: str = "") -> None:
    """Called by a provider adapter to attach what IT built and received.

    A no-op outside a recorded call, and it never raises: an adapter must not
    fail because observability is off or broken.
    """
    try:
        pending = _CURRENT.get()
        if pending is None:
            return
        pending.adapter = adapter or pending.adapter
        pending.provider = provider or pending.provider
        if request is not None:
            pending.adapter_requests.append(_snapshot(request))
        if raw_response is not None:
            pending.raw_responses.append(_snapshot(raw_response))
        if translation:
            pending.translation.append(translation)
    except Exception:  # noqa: BLE001 - observability never breaks a call
        logger.exception("could not attach an adapter stage")


def _snapshot(value: Any) -> Any:
    """A deep, detached copy taken NOW, before a caller can mutate the object."""
    plain = to_plain(value) if not isinstance(
        value, (dict, list, str, int, float, bool, type(None))) else value
    try:
        return copy.deepcopy(plain)
    except Exception:  # noqa: BLE001
        return json.loads(json.dumps(plain, default=str))


# ---- the proxy -------------------------------------------------------------

@dataclasses.dataclass
class Binding:
    run_id: str = ""
    thread_id: str = ""
    tenant_id: str = ""
    domain_id: str = ""
    surface: str = "advanced_cockpit"
    #: Set when this call replays an earlier recorded call (AI Model Lab).
    replay_of: str = ""


class RecordingProvider:
    """A pass-through provider that records every `converse` it forwards.

    Everything except `converse` is delegated untouched through `__getattr__`
    -- `count_tokens`, `status`, `configured`, `name`, `model`. `converse`
    receives the caller's keyword arguments and forwards THE SAME OBJECTS to
    the wrapped provider; the recorder only reads deep copies.
    """

    def __init__(self, inner: Any, store: ExchangeStore,
                 binding: Binding) -> None:
        self._inner = inner
        self._store = store
        self._binding = binding

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    @property
    def wrapped(self) -> Any:
        return self._inner

    def converse(self, **kwargs: Any) -> Any:
        started = time.time()
        clock = time.perf_counter()
        try:
            canonical = _snapshot(kwargs)
        except Exception:  # noqa: BLE001
            canonical = None
        pending = _Pending()
        token = _CURRENT.set(pending)
        try:
            result = self._inner.converse(**kwargs)
        except BaseException as exc:
            _CURRENT.reset(token)
            self._write(canonical, pending, started, clock, result=None,
                        error=exc)
            raise
        _CURRENT.reset(token)
        self._write(canonical, pending, started, clock, result=result,
                    error=None)
        return result

    def _write(self, canonical: Any, pending: _Pending, started: float,
               clock: float, *, result: Any, error: BaseException | None
               ) -> None:
        try:
            record = build_record(
                canonical=canonical, pending=pending, result=result,
                error=error, started=started,
                elapsed_ms=int((time.perf_counter() - clock) * 1000),
                binding=self._binding,
                provider=str(getattr(self._inner, "name", "") or
                             type(self._inner).__name__),
                seq=self._store.next_seq(self._binding.run_id),
                replay_of=self._binding.replay_of)
            self._store.insert(record)
        except Exception:  # noqa: BLE001 - never break the call it observed
            logger.exception("could not record an LLM exchange")


def normalized(result: Any) -> dict[str, Any]:
    """The `ConverseResult` CreditProbe continued with, as plain data."""
    if result is None:
        return {}
    blocks = [to_plain(b) if not isinstance(b, dict) else b
              for b in (getattr(result, "assistant_blocks", None) or [])]
    return {
        "assistant_blocks": strip_hidden_reasoning(blocks),
        "text": getattr(result, "text", ""),
        "tool_calls": list(getattr(result, "tool_calls", None) or []),
        "stop_reason": getattr(result, "stop_reason", ""),
        "model": getattr(result, "model", ""),
        "duration_ms": getattr(result, "duration_ms", 0),
        "usage": {
            "input_tokens": getattr(result, "input_tokens", 0),
            "output_tokens": getattr(result, "output_tokens", 0),
            "cache_read_input_tokens": getattr(result, "cache_read_tokens", 0),
            "cache_creation_input_tokens": getattr(
                result, "cache_write_tokens", 0)},
        "attempts": getattr(result, "attempts", 1),
        "request_id": getattr(result, "request_id", ""),
    }


def build_record(*, canonical: Any, pending: _Pending, result: Any,
                 error: BaseException | None, started: float, elapsed_ms: int,
                 binding: Binding, provider: str, seq: int,
                 replay_of: str = "") -> dict[str, Any]:
    redactions: list[dict[str, str]] = []
    request = sanitize(canonical or {}, path="$.canonical_request",
                       found=redactions)
    adapter_requests = [sanitize(r, path=f"$.adapter_request[{i}]",
                                 found=redactions)
                        for i, r in enumerate(pending.adapter_requests)]
    raw = [sanitize(r, path=f"$.raw_response[{i}]", found=redactions)
           for i, r in enumerate(pending.raw_responses)]
    raw = [dict(r, content=strip_hidden_reasoning(r.get("content")))
           if isinstance(r, dict) and isinstance(r.get("content"), list)
           else r for r in raw]
    norm = sanitize(normalized(result), path="$.normalized_response",
                    found=redactions)
    usage = norm.get("usage", {}) if isinstance(norm, dict) else {}
    requested_model = str((canonical or {}).get("model", "") or "")
    resolved_model = str(norm.get("model") or "") if isinstance(
        norm, dict) else ""
    if raw and isinstance(raw[-1], dict) and raw[-1].get("model"):
        resolved_model = str(raw[-1]["model"])
    comp = composition(request) if isinstance(request, dict) else {}
    sent = transmitted_rows(request) if isinstance(request, dict) else {}
    error_text = ""
    if error is not None:
        error_text = scrub_text(f"{type(error).__name__}: {error}",
                                "$.error", redactions)[:2000]
    hashes = {
        "system": digest(request.get("system")) if isinstance(
            request, dict) else "",
        "messages": digest(request.get("messages")) if isinstance(
            request, dict) else "",
        "tools": digest(request.get("tools")) if isinstance(
            request, dict) else "",
        "canonical_request": digest(request),
        "adapter_request": digest(adapter_requests),
        "raw_response": digest(raw),
        "normalized_response": digest(norm),
        "model_profile": digest({"provider": provider,
                                 "adapter": pending.adapter,
                                 "requested_model": requested_model,
                                 "resolved_model": resolved_model}),
    }
    return {
        "record_version": RECORD_VERSION,
        "exchange_id": "llmx-" + uuid.uuid4().hex,
        "run_id": binding.run_id, "thread_id": binding.thread_id,
        "tenant_id": binding.tenant_id, "domain_id": binding.domain_id,
        "surface": binding.surface, "seq": seq,
        "purpose": str((canonical or {}).get("purpose", "") or ""),
        "role": str((canonical or {}).get("role", "") or ""),
        "provider": pending.provider or provider,
        "adapter": pending.adapter or provider,
        "requested_model": requested_model,
        "resolved_model": resolved_model or requested_model,
        "status": "ERROR" if error is not None else "OK",
        "error": error_text,
        "stop_reason": str(norm.get("stop_reason", "") if isinstance(
            norm, dict) else ""),
        "request_id": str(norm.get("request_id", "") if isinstance(
            norm, dict) else ""),
        "started_at": started, "ended_at": started + elapsed_ms / 1000.0,
        "provider_ms": elapsed_ms,
        "replay_of": replay_of,
        "settings": {k: request.get(k) for k in (
            "max_tokens", "timeout", "allow_retry", "effort", "tool_choice",
            "output_config") if isinstance(request, dict) and k in request},
        "canonical_request": request,
        "adapter_request": adapter_requests,
        "adapter_translation": list(pending.translation),
        "raw_response": raw,
        "raw_response_available": bool(raw),
        "normalized_response": norm,
        "usage": usage,
        "context_composition": comp,
        "transmitted_data": sent,
        "hashes": hashes,
        "redactions": redactions,
        "hidden_reasoning_recorded": False,
    }


def bind(provider: Any, *, runtime: Any = None, run: Any = None,
         surface: str = "advanced_cockpit",
         store: ExchangeStore | None = None) -> Any:
    """The provider to hand the analyst: the same object when the flag is off.

    `runtime.cfg` locates the store beside the V4 state database; `run` names
    the run, thread and tenant the calls belong to.
    """
    if provider is None or not enabled():
        return provider
    try:
        target = store or store_at(store_path_for(getattr(runtime, "cfg",
                                                          None)))
        binding = Binding(
            run_id=str(getattr(run, "run_id", "") or ""),
            thread_id=str(getattr(run, "thread_id", "") or ""),
            tenant_id=str(getattr(run, "tenant_id", "") or ""),
            domain_id=str(getattr(run, "domain_id", "") or ""),
            surface=surface)
        return RecordingProvider(provider, target, binding)
    except Exception:  # noqa: BLE001 - never stop a run over observability
        logger.exception("the LLM exchange recorder could not bind; the run "
                         "continues unrecorded")
        return provider


@contextmanager
def recording(provider: Any, store: ExchangeStore, binding: Binding
              ) -> Iterator[RecordingProvider]:
    """For non-worker surfaces (AI Model Lab replay): always records."""
    yield RecordingProvider(provider, store, binding)


__all__ = ["Binding", "ExchangeStore", "FLAG", "REDACTED", "RecordingProvider",
           "adapter_stage", "bind", "build_record", "canonical_bytes",
           "composition", "digest", "enabled", "is_secret_key", "normalized",
           "recording", "sanitize", "store_at", "store_path_for",
           "strip_hidden_reasoning", "transmitted_rows"]
