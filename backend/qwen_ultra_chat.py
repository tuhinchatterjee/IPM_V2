"""
Chat backend for Qwen 3.5 0.8B, branded in the UI as "Qwen Ultra".
Uses the same Ollama tool-calling loop as ai_chat.py but routes to
qwen3.5:0.8b instead of the larger qwen3:4b backend.
"""

import requests

from backend import ai_chat
from backend.services import ai_common

DISPLAY_NAME = "Qwen 3.5 0.8B"
MODEL = "qwen3.5:0.8b"
# 0.8B model is fast — use a tighter timeout than the larger backend
REQUEST_TIMEOUT = 90
MAX_TOOL_ROUNDS = ai_chat.MAX_TOOL_ROUNDS

UNAVAILABLE_MSG = (
    f"The {DISPLAY_NAME} assistant isn't reachable right now. Make sure Ollama is running "
    f"(`ollama serve`) with the `{MODEL}` model pulled (`ollama pull {MODEL}`)."
)

# Speed options: greedy decoding (temperature 0, top_k 1) + compact context window
_SPEED_OPTIONS = {
    "temperature": 0,
    "top_k": 1,
    "num_ctx": 4096,
}


@ai_common.retry_ollama
def _ollama_call(messages: list) -> dict:
    payload = {
        "model": MODEL,
        "messages": messages,
        "tools": ai_chat.TOOLS,
        "stream": False,
        "think": False,
        "options": _SPEED_OPTIONS,
    }
    resp = requests.post(ai_chat.OLLAMA_URL, json=payload, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def chat(messages: list) -> tuple:
    """Same contract as ai_chat.chat(): full history in, (reply_text, new_messages) out."""
    working = list(messages)
    appended = []

    try:
        for _ in range(MAX_TOOL_ROUNDS):
            data = _ollama_call(working)
            msg = data["message"]
            working.append(msg)
            appended.append(msg)

            tool_calls = msg.get("tool_calls")
            if not tool_calls:
                return msg.get("content") or "(no response)", appended

            for tc in tool_calls:
                name = tc["function"]["name"]
                args = tc["function"].get("arguments") or {}
                func = ai_chat.TOOL_FUNCS.get(name)
                try:
                    result = func(**args) if func else {"error": f"Unknown tool '{name}'"}
                except Exception as exc:  # noqa: BLE001 - surface to the model, not a crash
                    result = {"error": str(exc)}
                tool_msg = {"role": "tool", "content": ai_common.format_tool_result(result)}
                working.append(tool_msg)
                appended.append(tool_msg)

        data = _ollama_call(working)
        msg = data["message"]
        appended.append(msg)
        return msg.get("content") or "(no response)", appended

    except requests.exceptions.RequestException:
        return UNAVAILABLE_MSG, []
