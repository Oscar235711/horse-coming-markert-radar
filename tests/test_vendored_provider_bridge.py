"""Regression coverage for the Higress OpenAI-compatible Skill bridge."""

from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
VENDORED_SCRIPTS = PROJECT_ROOT / "vendor" / "last30days" / "scripts"
if str(VENDORED_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(VENDORED_SCRIPTS))

from lib import providers  # noqa: E402


def test_openai_compatible_bridge_sends_chat_completions_payload(monkeypatch) -> None:
    calls: list[tuple[str, dict]] = []

    def fake_post(url, payload, *, headers, timeout):
        calls.append((url, payload))
        return {"choices": [{"message": {"content": "{\"ok\": true}"}}]}

    monkeypatch.setenv("OPENAI_BASE_URL", "https://higress.example/gateway/v1")
    monkeypatch.setenv("LAST30DAYS_OPENAI_API_STYLE", "chat_completions")
    monkeypatch.setattr(providers.http, "post", fake_post)

    result = providers.OpenAIClient("test-token").generate_text(
        "deepseek-v4-flash",
        "Return JSON only.",
    )

    assert result == '{"ok": true}'
    assert calls == [
        (
            "https://higress.example/gateway/v1/chat/completions",
            {
                "model": "deepseek-v4-flash",
                "messages": [{"role": "user", "content": "Return JSON only."}],
                "temperature": 0,
            },
        )
    ]
