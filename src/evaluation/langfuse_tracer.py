from __future__ import annotations

from typing import Any, Dict

from ..utils.langfuse_logger import get_langfuse_logger


class _LangfuseTracer:
    def __init__(self) -> None:
        self._logger = get_langfuse_logger()

    def trace(self, name: str, payload: Dict[str, Any]) -> None:
        try:
            self._logger.log_trace(name=name, payload=payload)
        except Exception:
            return

    def start_span(self, name: str, payload: Dict[str, Any]) -> Any:
        try:
            start_span = getattr(self._logger, "start_span", None)
            if callable(start_span):
                return start_span(name=name, payload=payload)
        except Exception:
            return None
        return None

    def end_span(self, span: Any, name: str, payload: Dict[str, Any]) -> None:
        try:
            end_span = getattr(self._logger, "end_span", None)
            if callable(end_span):
                end_span(span=span, name=name, payload=payload)
                return
        except Exception:
            return


def get_langfuse_tracer() -> _LangfuseTracer:
    return _LangfuseTracer()
