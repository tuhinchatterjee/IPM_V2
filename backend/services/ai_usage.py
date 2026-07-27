"""
AI usage logging to Postgres (ai_usage_log). Records provider/model, timing,
status, coarse size counts and — for audit — the tool NAMES and argument KEYS
invoked. Never records prompt text, tool result values, or borrower identifiers.
Failures to log are swallowed (a logging problem must not break chat).
"""

import logging

from backend.db.engine import get_session
from backend.db.models import AiUsageLog

logger = logging.getLogger(__name__)


def extract_tool_calls(appended: list) -> list | None:
    """Pull tool names + argument KEYS (never values) from the messages a backend
    appended this turn. Handles both Ollama (tool_calls) and Anthropic (tool_use
    content blocks)."""
    tools = []
    for msg in appended or []:
        # Ollama / OpenAI shape.
        for tc in (msg.get("tool_calls") or []) if isinstance(msg, dict) else []:
            fn = tc.get("function", {})
            args = fn.get("arguments") or {}
            tools.append({"name": fn.get("name"), "arg_keys": sorted(args.keys()) if isinstance(args, dict) else []})
        # Anthropic content-block shape.
        content = msg.get("content") if isinstance(msg, dict) else None
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    args = block.get("input") or {}
                    tools.append({"name": block.get("name"),
                                  "arg_keys": sorted(args.keys()) if isinstance(args, dict) else []})
    return tools or None


def log_usage(*, user_id, provider, model, status, latency_ms,
              prompt_chars=None, completion_chars=None,
              input_tokens=None, output_tokens=None, tool_calls=None) -> None:
    try:
        with get_session() as s:
            s.add(AiUsageLog(
                user_id=user_id, provider=provider, model=model, status=status,
                latency_ms=latency_ms, prompt_chars=prompt_chars, completion_chars=completion_chars,
                input_tokens=input_tokens, output_tokens=output_tokens, tool_calls=tool_calls,
            ))
    except Exception as e:  # noqa: BLE001 — logging must never break the chat path
        logger.warning("Failed to write ai_usage_log: %s", e)
