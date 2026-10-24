"""标准 OpenAI 兼容接口实现（只用标准库 urllib，零额外依赖）。"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any

from ..config.settings import ProviderConfig
from .base import ChatMessage, Provider, ProviderError


class OpenAICompatProvider(Provider):
    """任何 OpenAI 兼容网关（官方 / 中转 / 免费池）。"""

    def __init__(self, config: ProviderConfig) -> None:
        self.config = config
        self.name = config.name
        self.model = config.model
        self._endpoint = config.base_url.rstrip("/") + "/chat/completions"

    # ---- 内部 ----
    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "ShiningWorld/1.0",
        }
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        headers.update(self.config.extra_headers)
        return headers

    def _payload(
        self,
        messages: list[ChatMessage],
        temperature: float,
        max_tokens: int,
        *,
        stream: bool = False,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [m.to_payload() for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream,
        }
        payload.update(self.config.params)
        return payload

    @staticmethod
    def _extract_text(body: dict[str, Any]) -> str:
        choices = body.get("choices") or []
        if not choices:
            raise ProviderError("服务商返回缺少 choices", retryable=True, detail={"body": body})
        message = choices[0].get("message") or {}
        content = message.get("content")
        if isinstance(content, list):  # 部分网关返回分段结构
            content = "".join(
                str(part.get("text", "")) for part in content if isinstance(part, dict)
            )
        text = str(content or "").strip()
        if not text:
            raise ProviderError("服务商返回空文本", retryable=True)
        return text

    # ---- 对外 ----
    def complete(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.85,
        max_tokens: int = 800,
    ) -> str:
        if not self.config.base_url:
            raise ProviderError(f"服务商 {self.name} 未配置 base_url", retryable=False)

        data = json.dumps(
            self._payload(messages, temperature, max_tokens),
            ensure_ascii=False,
        ).encode("utf-8")
        request = urllib.request.Request(
            self._endpoint,
            data=data,
            headers=self._headers(),
            method="POST",
        )
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout_s) as response:
                raw = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")[:400]
            retryable = exc.code in {408, 409, 425, 429, 500, 502, 503, 504}
            raise ProviderError(
                f"{self.name} HTTP {exc.code}",
                retryable=retryable,
                detail={"status": exc.code, "body": body},
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ProviderError(
                f"{self.name} 连接失败：{exc}",
                retryable=True,
            ) from exc
        finally:
            self._last_latency_ms = int((time.perf_counter() - started) * 1000)

        try:
            body = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ProviderError(
                f"{self.name} 返回非 JSON",
                retryable=True,
                detail={"body": raw[:400]},
            ) from exc
        return self._extract_text(body)

    def health_check(self) -> dict[str, Any]:
        started = time.perf_counter()
        result = super().health_check()
        result["latency_ms"] = int((time.perf_counter() - started) * 1000)
        result["model"] = self.model
        result["base_url"] = self.config.base_url
        return result
