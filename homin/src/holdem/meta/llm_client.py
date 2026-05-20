"""LLM 클라이언트 — OpenAI-호환 로컬 프록시.

엔드포인트: http://localhost:8317/v1 (기본), env 로 덮어쓰기.
인증: Bearer <HOLDEM_LLM_API_KEY>.

설계 원칙:
  - 모든 호출은 **fallback 보장**. 오류 시 `LLMResult(ok=False, reason=...)` 반환.
  - `temperature=0.0` 고정 — 재현성.
  - 봇 런타임에서는 tool-use 사용 안 함 (chat completions only).
  - timeout 은 모델별 파라미터 (llm.yaml). 초과 시 즉시 fallback.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from openai import APIError, AsyncOpenAI, AuthenticationError

from .._env import load_dotenv

log = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).resolve().parents[3] / "configs" / "llm.yaml"


@dataclass(frozen=True)
class ModelParams:
    max_tokens: int
    timeout_s: float
    temperature: float


@dataclass(frozen=True)
class LLMResult:
    ok: bool
    text: str = ""
    model: str = ""
    reason: str = ""
    latency_s: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0


class LLMConfig:
    def __init__(self, data: dict[str, Any]):
        self._data = data
        self.base_url = os.environ.get(
            data["endpoint"].get("env_var_base_url", "HOLDEM_LLM_BASE_URL"),
            data["endpoint"]["base_url"],
        )
        self._api_key_env = data["endpoint"]["env_var_key"]
        self.models: dict[str, str] = data["models"]  # role → model_id
        self.model_params: dict[str, ModelParams] = {
            name: ModelParams(**params) for name, params in data["model_params"].items()
        }
        self.fallback = data["fallback"]

    @property
    def api_key(self) -> str | None:
        return os.environ.get(self._api_key_env)

    def params_for(self, model_id: str) -> ModelParams:
        return self.model_params[model_id]


def load_config(path: Path = _CONFIG_PATH) -> LLMConfig:
    load_dotenv()
    with path.open() as f:
        return LLMConfig(yaml.safe_load(f))


class LLMClient:
    """엄격 모드 — chat completions 만 사용, tool-use 비활성."""

    def __init__(self, cfg: LLMConfig | None = None):
        self.cfg = cfg or load_config()
        self._client: AsyncOpenAI | None = None

    def _ensure_client(self) -> AsyncOpenAI | None:
        if self._client is not None:
            return self._client
        api_key = self.cfg.api_key
        if not api_key:
            return None
        self._client = AsyncOpenAI(base_url=self.cfg.base_url, api_key=api_key)
        return self._client

    def resolve_model(self, role: str = "default") -> str:
        try:
            return self.cfg.models[role]
        except KeyError as e:
            raise ValueError(f"unknown role: {role} (available: {list(self.cfg.models)})") from e

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        role: str = "default",
        system: str | None = None,
    ) -> LLMResult:
        model = self.resolve_model(role)
        params = self.cfg.params_for(model)
        client = self._ensure_client()
        if client is None:
            return LLMResult(ok=False, model=model, reason="auth_missing")

        full_messages: list[dict[str, str]] = []
        if system:
            full_messages.append({"role": "system", "content": system})
        full_messages.extend(messages)

        start = time.perf_counter()
        try:
            resp = await asyncio.wait_for(
                client.chat.completions.create(
                    model=model,
                    messages=full_messages,  # type: ignore[arg-type]
                    max_tokens=params.max_tokens,
                    temperature=params.temperature,
                ),
                timeout=params.timeout_s,
            )
        except asyncio.TimeoutError:
            return LLMResult(
                ok=False, model=model, reason="timeout",
                latency_s=time.perf_counter() - start,
            )
        except AuthenticationError:
            return LLMResult(ok=False, model=model, reason="auth_missing")
        except APIError as e:
            return LLMResult(ok=False, model=model, reason=f"api_error:{e.__class__.__name__}")
        except Exception as e:  # 보수적: 예상 외 예외도 fallback 으로 수렴
            log.exception("unexpected llm error")
            return LLMResult(ok=False, model=model, reason=f"error:{e.__class__.__name__}")

        latency = time.perf_counter() - start
        try:
            text = resp.choices[0].message.content or ""
            usage = resp.usage
            return LLMResult(
                ok=True, model=model, text=text, latency_s=latency,
                tokens_in=(usage.prompt_tokens if usage else 0),
                tokens_out=(usage.completion_tokens if usage else 0),
            )
        except (IndexError, AttributeError):
            return LLMResult(
                ok=False, model=model, reason="schema_violation", latency_s=latency,
            )
