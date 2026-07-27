"""
Third chat backend for the IPM dashboard, branded in the UI as "GLM-5.2"
(actually Claude Haiku via the Anthropic API). Reuses the exact same tool
definitions and implementations as ai_chat.py (data_loader-backed, so answers
are grounded the same way) - only the wire format to the model provider
differs: Anthropic takes the system prompt as a top-level parameter (not a
message), and represents tool calls/results as content blocks rather than
OpenAI-style tool_calls/tool-role messages.
"""

import anthropic

from backend import ai_chat
from backend.config import settings
from backend.services import ai_common

# UI-facing label only. The actual model called (and recorded in ai_usage_log) is
# MODEL below — kept accurate so the audit trail never drifts from the display name.
DISPLAY_NAME = "GLM 5.2"
MODEL = "claude-haiku-4-5"
MAX_TOKENS = 2048
MAX_TOOL_ROUNDS = ai_chat.MAX_TOOL_ROUNDS

# Transient failures worth retrying (connection drop, 5xx, throttling).
_RETRYABLE = (anthropic.APIConnectionError, anthropic.InternalServerError, anthropic.RateLimitError)

_client = None


def _get_client():
    global _client
    if _client is None:
        if not settings.anthropic_api_key:
            return None
        _client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    return _client


@ai_common.anthropic_retry(_RETRYABLE)
def _create(client, **kwargs):
    return client.messages.create(**kwargs)


def _to_anthropic_tools() -> list:
    """Anthropic tools use {name, description, input_schema} - convert from
    our OpenAI/Ollama-shaped {type:"function", function:{name,description,parameters}}."""
    converted = []
    for t in ai_chat.TOOLS:
        fn = t["function"]
        converted.append({
            "name": fn["name"],
            "description": fn["description"],
            "input_schema": fn["parameters"],
        })
    return converted


_ANTHROPIC_TOOLS = _to_anthropic_tools()


def chat(messages: list) -> tuple:
    """Same contract as ai_chat.chat(): takes the full history incl. the new
    user message, returns (reply_text, new_messages_to_append)."""
    client = _get_client()
    if client is None:
        return (
            f"{DISPLAY_NAME} isn't configured - no ANTHROPIC_API_KEY found. "
            "Add one to the .env file to enable this model.",
            [],
        )

    # Claude takes the system prompt as a top-level request parameter, not a
    # message in the list - pull it out once.
    system_prompt = next((m["content"] for m in messages if m.get("role") == "system"), "")
    working = [m for m in messages if m.get("role") != "system"]
    appended = []

    try:
        for _ in range(MAX_TOOL_ROUNDS):
            response = _create(
                client,
                model=MODEL,
                max_tokens=MAX_TOKENS,
                system=system_prompt,
                messages=working,
                tools=_ANTHROPIC_TOOLS,
            )
            content_blocks = [block.model_dump() for block in response.content]
            assistant_msg = {"role": "assistant", "content": content_blocks}
            working.append(assistant_msg)
            appended.append(assistant_msg)

            if response.stop_reason != "tool_use":
                text = "".join(b["text"] for b in content_blocks if b["type"] == "text")
                return text or "(no response)", appended

            tool_results = []
            for block in content_blocks:
                if block["type"] != "tool_use":
                    continue
                name, args, tool_id = block["name"], block.get("input") or {}, block["id"]
                func = ai_chat.TOOL_FUNCS.get(name)
                try:
                    result = func(**args) if func else {"error": f"Unknown tool '{name}'"}
                    tool_results.append({
                        "type": "tool_result", "tool_use_id": tool_id,
                        "content": ai_common.format_tool_result(result),
                    })
                except Exception as exc:  # noqa: BLE001 - surface to the model, not a crash
                    tool_results.append({
                        "type": "tool_result", "tool_use_id": tool_id,
                        "content": str(exc), "is_error": True,
                    })
            tool_msg = {"role": "user", "content": tool_results}
            working.append(tool_msg)
            appended.append(tool_msg)

        # Ran out of tool-call rounds - ask once more for a final answer, no more tools.
        response = _create(
            client, model=MODEL, max_tokens=MAX_TOKENS, system=system_prompt, messages=working,
        )
        content_blocks = [block.model_dump() for block in response.content]
        appended.append({"role": "assistant", "content": content_blocks})
        text = "".join(b["text"] for b in content_blocks if b["type"] == "text")
        return text or "(no response)", appended

    except anthropic.AuthenticationError:
        return f"{DISPLAY_NAME}: authentication failed - check the API key in .env.", []
    except anthropic.PermissionDeniedError:
        return f"{DISPLAY_NAME}: the API key doesn't have access to this model.", []
    except anthropic.RateLimitError:
        return f"{DISPLAY_NAME} is rate-limited right now - try again in a moment.", []
    except anthropic.APIStatusError as exc:
        return f"{DISPLAY_NAME} request failed: {exc.message}", []
    except anthropic.APIConnectionError:
        return f"{DISPLAY_NAME} couldn't connect - check your network connection.", []


def is_configured() -> bool:
    return bool(settings.anthropic_api_key)
