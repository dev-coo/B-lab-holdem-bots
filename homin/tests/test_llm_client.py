"""LLMClient — 로드, fallback 경로, 성공 경로 테스트.

실제 프록시 호출은 하지 않음. OpenAI 클라이언트의 chat.completions.create 를
monkeypatch 로 대체하여 schema 와 fallback 동작 검증.
"""
from __future__ import annotations

import asyncio

import pytest

from holdem.meta.llm_client import LLMClient, load_config


def test_load_config_models():
    cfg = load_config()
    assert cfg.models["default"] == "claude-sonnet-4-5-20250929"
    assert cfg.models["standard"] == "claude-sonnet-4-5-20250929"
    assert cfg.models["critical"] == "claude-opus-4-6"
    assert cfg.base_url.startswith("http")


def test_resolve_model_unknown_role():
    client = LLMClient()
    with pytest.raises(ValueError):
        client.resolve_model("bogus")


def test_params_per_model():
    cfg = load_config()
    sonnet = cfg.params_for("claude-sonnet-4-5-20250929")
    opus = cfg.params_for("claude-opus-4-6")
    assert sonnet.timeout_s < opus.timeout_s
    assert sonnet.max_tokens <= opus.max_tokens
    assert sonnet.temperature == 0.0


async def test_auth_missing_returns_fallback(monkeypatch):
    monkeypatch.delenv("HOLDEM_LLM_API_KEY", raising=False)
    client = LLMClient()
    result = await client.complete([{"role": "user", "content": "hi"}])
    assert result.ok is False
    assert result.reason == "auth_missing"
    assert result.model == "claude-sonnet-4-5-20250929"


class _FakeMessage:
    def __init__(self, content: str):
        self.content = content


class _FakeChoice:
    def __init__(self, content: str):
        self.message = _FakeMessage(content)


class _FakeUsage:
    prompt_tokens = 42
    completion_tokens = 13


class _FakeResponse:
    def __init__(self, content: str):
        self.choices = [_FakeChoice(content)]
        self.usage = _FakeUsage()


class _FakeCompletions:
    def __init__(self, response: _FakeResponse | BaseException):
        self.response = response
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.response, BaseException):
            raise self.response
        return self.response


class _FakeChat:
    def __init__(self, completions):
        self.completions = completions


class _FakeClient:
    def __init__(self, completions):
        self.chat = _FakeChat(completions)


async def test_success_returns_text_and_usage(monkeypatch):
    monkeypatch.setenv("HOLDEM_LLM_API_KEY", "sk-test-token")
    client = LLMClient()
    fake_completions = _FakeCompletions(_FakeResponse("fold"))
    client._client = _FakeClient(fake_completions)  # type: ignore[assignment]

    result = await client.complete(
        [{"role": "user", "content": "best action?"}],
        system="you are a poker coach",
    )
    assert result.ok is True
    assert result.text == "fold"
    assert result.tokens_in == 42
    assert result.tokens_out == 13
    assert result.model == "claude-sonnet-4-5-20250929"

    call = fake_completions.calls[0]
    assert call["model"] == "claude-sonnet-4-5-20250929"
    assert call["max_tokens"] == 1024
    assert call["temperature"] == 0.0
    assert call["messages"][0] == {"role": "system", "content": "you are a poker coach"}
    assert call["messages"][1] == {"role": "user", "content": "best action?"}


async def test_timeout_returns_fallback(monkeypatch):
    monkeypatch.setenv("HOLDEM_LLM_API_KEY", "sk-test")
    client = LLMClient()

    class _SlowCompletions:
        async def create(self, **kwargs):
            await asyncio.sleep(5)

    client._client = _FakeClient(_SlowCompletions())  # type: ignore[assignment]

    result = await client.complete([{"role": "user", "content": "x"}], role="default")
    assert result.ok is False
    assert result.reason == "timeout"
    assert result.latency_s >= 1.0  # haiku timeout 1.0s


async def test_api_error_returns_fallback(monkeypatch):
    from openai import APIError

    monkeypatch.setenv("HOLDEM_LLM_API_KEY", "sk-test")
    client = LLMClient()
    err = APIError("proxy down", request=None, body=None)  # type: ignore[arg-type]
    client._client = _FakeClient(_FakeCompletions(err))  # type: ignore[assignment]

    result = await client.complete([{"role": "user", "content": "x"}])
    assert result.ok is False
    assert result.reason.startswith("api_error")


async def test_role_selects_critical_model(monkeypatch):
    monkeypatch.setenv("HOLDEM_LLM_API_KEY", "sk-test")
    client = LLMClient()
    fake = _FakeCompletions(_FakeResponse("opus says fold"))
    client._client = _FakeClient(fake)  # type: ignore[assignment]

    result = await client.complete(
        [{"role": "user", "content": "bubble decision"}],
        role="critical",
    )
    assert result.model == "claude-opus-4-6"
    assert fake.calls[0]["model"] == "claude-opus-4-6"
    assert fake.calls[0]["max_tokens"] == 2048
