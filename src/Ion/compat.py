"""Model-provider compatibility helpers.

Handles provider-specific quirks (e.g. MiniMax rejects ``role="system"`` and
uses ``reasoning_details`` instead of ``reasoning_content``).
"""

from __future__ import annotations


def is_minimax(model_id: str) -> bool:
    """Return True when the configured model is a MiniMax endpoint."""
    return "minimax" in model_id.lower()


def adapt_messages_for_model(messages: list[dict], model_id: str) -> list[dict]:
    """Return a copy of *messages* with provider-specific adaptations applied.

    Current adaptations:
    - MiniMax: ``role="system"`` is rejected (error 2013).  Rewrite every
      ``system`` message to ``user``.
    """
    if not is_minimax(model_id):
        return list(messages)

    adapted: list[dict] = []
    for msg in messages:
        m = dict(msg)
        if m.get("role") == "system":
            m["role"] = "user"
        adapted.append(m)
    return adapted


def get_stream_create_kwargs(model_id: str) -> dict:
    """Return extra keyword args for ``client.chat.completions.create``.

    - OpenAI / DeepSeek: ``stream_options={"include_usage": True}``
    - MiniMax: ``extra_body={"reasoning_split": True}``
    """
    if is_minimax(model_id):
        return {"extra_body": {"reasoning_split": True}}
    return {"stream_options": {"include_usage": True}}
