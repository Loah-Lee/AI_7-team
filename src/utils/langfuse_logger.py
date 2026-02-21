from __future__ import annotations

import os
from typing import Any, Dict


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
        # SDK v3(create_event) 우선, 구버전(v2)의 trace는 fallback으로만 사용한다.
        try:
            event_input = payload.get("query", payload.get("input"))
            event_output = payload.get("answer", payload.get("output"))
            create_event = getattr(self._client, "create_event", None)
            if callable(create_event):
                create_event(
                    name=name,
                    input=event_input,
                    output=event_output,
                    metadata=payload,
                )
                flush = getattr(self._client, "flush", None)
                if callable(flush):
                    flush()
                return

            trace_fn = getattr(self._client, "trace", None)
            if callable(trace_fn):
                trace = trace_fn(name=name, metadata=payload)
                trace_flush = getattr(trace, "flush", None)
                if callable(trace_flush):
                    trace_flush()
                    return
                flush = getattr(self._client, "flush", None)
                if callable(flush):
                    flush()
                return
        except Exception:
            return


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
