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
        # SDK v3에서는 trace 레벨 input/output 표시를 위해 current span + trace update를 사용한다.
        # 구버전(v2)의 trace는 마지막 fallback으로만 사용한다.
        try:
            event_input = payload.get("input")
            if event_input is None and "query" in payload:
                event_input = {"query": payload.get("query")}

            event_output = payload.get("output")
            if event_output is None:
                if any(k in payload for k in ("answer", "status", "top1", "citations", "response_time_sec")):
                    event_output = {
                        "answer": payload.get("answer"),
                        "status": payload.get("status"),
                        "top1": payload.get("top1"),
                        "citations": payload.get("citations"),
                        "response_time_sec": payload.get("response_time_sec"),
                    }
                elif any(k in payload for k in ("metrics", "qual_score_top1", "qual_reason_top1")):
                    event_output = {
                        "metrics": payload.get("metrics"),
                        "qual_score_top1": payload.get("qual_score_top1"),
                        "qual_reason_top1": payload.get("qual_reason_top1"),
                    }
                elif "answer" in payload:
                    event_output = payload.get("answer")

            level = payload.get("level")
            status = str(payload.get("status", "")).lower().strip()
            if not level:
                if status in {"error", "fail", "failed"}:
                    level = "ERROR"
                elif status in {"warn", "warning"}:
                    level = "WARNING"
                else:
                    level = "DEFAULT"
            status_message = payload.get("status_message", payload.get("status"))
            version = payload.get("version")
            user_id = payload.get("user_id")
            session_id = payload.get("session_id")
            public = payload.get("public")

            tags = payload.get("tags")
            if isinstance(tags, str):
                tags = [tags]
            if not isinstance(tags, list):
                tags = [name]
            if status:
                tags.append(f"status:{status}")
            if payload.get("variant"):
                tags.append(f"variant:{payload.get('variant')}")
            if payload.get("retriever"):
                tags.append(f"retriever:{payload.get('retriever')}")
            tags = [str(t) for t in tags if str(t).strip()]
            # 순서 보존 중복 제거
            tags = list(dict.fromkeys(tags))

            metadata = dict(payload)
            for key in (
                "input",
                "output",
                "query",
                "answer",
                "level",
                "status",
                "status_message",
                "version",
                "user_id",
                "session_id",
                "public",
                "tags",
            ):
                metadata.pop(key, None)

            start_as_current_span = getattr(self._client, "start_as_current_span", None)
            if callable(start_as_current_span):
                with start_as_current_span(
                    name=name,
                    input=event_input,
                    output=event_output,
                    metadata=metadata,
                    level=level,
                    status_message=status_message,
                    version=version,
                ):
                    update_current_trace = getattr(self._client, "update_current_trace", None)
                    if callable(update_current_trace):
                        update_current_trace(
                            name=name,
                            input=event_input,
                            output=event_output,
                            metadata=metadata,
                            user_id=user_id,
                            session_id=session_id,
                            version=version,
                            tags=tags,
                            public=public,
                        )
                flush = getattr(self._client, "flush", None)
                if callable(flush):
                    flush()
                return

            create_event = getattr(self._client, "create_event", None)
            if callable(create_event):
                create_event(
                    name=name,
                    input=event_input,
                    output=event_output,
                    metadata=metadata,
                    level=level,
                    status_message=status_message,
                    version=version,
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
