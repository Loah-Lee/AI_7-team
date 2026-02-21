from __future__ import annotations

import os
from typing import Any, Dict, Optional


class _NoOpLogger:
    def log_trace(self, name: str, payload: Dict[str, Any]) -> None:
        return


class _LangfuseLogger:
    def __init__(self, public_key: str, secret_key: str, base_url: str) -> None:
        try:
            from langfuse import Langfuse  # type: ignore
        except Exception as exc:  # pragma: no cover - optional dependency
            raise RuntimeError(
                "langfuse SDK가 설치되지 않았습니다. pip install langfuse 로 설치하세요."
            ) from exc

        self._client = Langfuse(
            public_key=public_key,
            secret_key=secret_key,
            host=base_url,
        )

    def log_trace(self, name: str, payload: Dict[str, Any]) -> None:
        trace = self._client.trace(name=name, metadata=payload)
        trace.flush()


def get_langfuse_logger() -> Any:
    public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
    secret_key = os.getenv("LANGFUSE_SECRET_KEY")
    base_url = os.getenv("LANGFUSE_BASE_URL")

    if not (public_key and secret_key and base_url):
        return _NoOpLogger()

    try:
        return _LangfuseLogger(public_key, secret_key, base_url)
    except Exception:
        return _NoOpLogger()
