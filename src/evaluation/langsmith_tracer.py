from __future__ import annotations

from typing import Any, Dict


class _NoOpLangSmithTracer:
    def trace(self, name: str, payload: Dict[str, Any]) -> None:
        return


def get_langsmith_tracer() -> _NoOpLangSmithTracer:
    # 현재 프로젝트에서는 LangSmith 연동 미사용. 인터페이스만 유지.
    return _NoOpLangSmithTracer()
