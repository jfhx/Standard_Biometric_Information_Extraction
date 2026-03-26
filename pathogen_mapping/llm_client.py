from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


@dataclass
class LLMResponse:
    content: str
    raw: dict[str, Any]


class LLMClient:
    def __init__(
        self,
        endpoint: str,
        model_name: str,
        timeout_seconds: int,
        max_retries: int,
    ) -> None:
        self.endpoint = endpoint
        self.model_name = model_name
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.logger = logging.getLogger(self.__class__.__name__)

    def chat_completion(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.0,
        max_tokens: int = 400,
    ) -> LLMResponse:
        payload = {
            "model": self.model_name,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        raw = self._post_json(payload)
        choices = raw.get("choices") or []
        if not choices:
            raise RuntimeError("模型响应缺少 choices 字段")
        message = choices[0].get("message") or {}
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("模型响应缺少 message.content")
        return LLMResponse(content=content, raw=raw)

    def test_connection(self) -> str:
        response = self.chat_completion(
            messages=[
                {
                    "role": "system",
                    "content": "你是一个只返回 JSON 的助手。",
                },
                {
                    "role": "user",
                    "content": '{"ping": "请返回 pong"}',
                },
            ],
            temperature=0.0,
            max_tokens=50,
        )
        return response.content

    def _post_json(self, payload: dict[str, Any]) -> dict[str, Any]:
        request = Request(
            url=self.endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                with urlopen(request, timeout=self.timeout_seconds) as response:
                    body = response.read().decode("utf-8")
                return json.loads(body)
            except HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                last_error = RuntimeError(
                    f"模型请求失败，HTTP {exc.code}，响应内容：{body}"
                )
            except URLError as exc:
                last_error = RuntimeError(f"无法连接模型接口：{exc}")
            except TimeoutError as exc:
                last_error = RuntimeError(f"模型请求超时：{exc}")
            except json.JSONDecodeError as exc:
                last_error = RuntimeError(f"模型返回的不是合法 JSON：{exc}")
            except Exception as exc:
                last_error = RuntimeError(f"模型请求异常：{exc}")

            self.logger.warning(
                "模型请求失败，准备重试：attempt=%s/%s error=%s",
                attempt,
                self.max_retries,
                last_error,
            )
            if attempt < self.max_retries:
                time.sleep(min(attempt, 3))

        if last_error is None:
            raise RuntimeError("模型请求失败，但没有捕获到具体异常")
        raise last_error
