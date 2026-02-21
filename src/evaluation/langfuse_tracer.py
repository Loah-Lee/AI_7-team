from __future__ import annotations

from typing import Any, Dict

from ..utils.langfuse_logger import get_langfuse_logger


class _LangfuseTracer:
    def __init__(self) -> None:
        self._logger = get_langfuse_logger()

    def trace(self, name: str, payload: Dict[str, Any]) -> None:
        self._logger.log_trace(name=name, payload=payload)


def get_langfuse_tracer() -> _LangfuseTracer:
    return _LangfuseTracer()
