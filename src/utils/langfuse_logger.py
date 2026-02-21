from __future__ import annotations

import os
from typing import Any, Dict


class _NoOpLogger:
    def log_trace(self, name: str, payload: Dict[str, Any]) -> None:
        return

    def start_span(self, name: str, payload: Dict[str, Any]) -> Any:
        return None

    def end_span(self, span: Any, name: str, payload: Dict[str, Any]) -> None:
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

    def _prepare_fields(self, name: str, payload: Dict[str, Any]) -> Dict[str, Any]:
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

        return {
            "event_input": event_input,
            "event_output": event_output,
            "metadata": metadata,
            "level": level,
            "status_message": status_message,
            "version": version,
            "user_id": user_id,
            "session_id": session_id,
            "public": public,
            "tags": tags,
        }

    def start_span(self, name: str, payload: Dict[str, Any]) -> Any:
        try:
            fields = self._prepare_fields(name, payload)
            start_as_current_span = getattr(self._client, "start_as_current_span", None)
            if callable(start_as_current_span):
                # active span context를 유지해 end_span에서 update_current_trace(tags 등) 호출이 가능하도록 한다.
                cm = start_as_current_span(
                    name=name,
                    input=fields["event_input"],
                    metadata=fields["metadata"],
                    level=fields["level"],
                    status_message=fields["status_message"],
                    version=fields["version"],
                    end_on_exit=False,
                )
                span = cm.__enter__()
                return {"span": span, "context_manager": cm}

            start_span = getattr(self._client, "start_span", None)
            if callable(start_span):
                return start_span(
                    name=name,
                    input=fields["event_input"],
                    metadata=fields["metadata"],
                    level=fields["level"],
                    status_message=fields["status_message"],
                    version=fields["version"],
                )

            start_observation = getattr(self._client, "start_observation", None)
            if callable(start_observation):
                return start_observation(
                    name=name,
                    as_type="span",
                    input=fields["event_input"],
                    metadata=fields["metadata"],
                    level=fields["level"],
                    status_message=fields["status_message"],
                    version=fields["version"],
                )
        except Exception:
            return None
        return None

    def end_span(self, span: Any, name: str, payload: Dict[str, Any]) -> None:
        try:
            fields = self._prepare_fields(name, payload)
            span_obj = span
            context_manager = None
            if isinstance(span, dict):
                span_obj = span.get("span")
                context_manager = span.get("context_manager")

            if span_obj is not None:
                update = getattr(span_obj, "update", None)
                if callable(update):
                    # start_span/end_span 경로에서는 current span context가 없을 수 있으므로
                    # trace 전용 API(update_current_trace)를 쓰지 않고 span 자체를 업데이트한다.
                    span_metadata = dict(fields["metadata"])
                    span_metadata["session_id"] = fields["session_id"]
                    span_metadata["user_id"] = fields["user_id"]
                    span_metadata["tags"] = fields["tags"]
                    span_metadata["public"] = fields["public"]
                    update(
                        output=fields["event_output"],
                        metadata=span_metadata,
                        level=fields["level"],
                        status_message=fields["status_message"],
                        version=fields["version"],
                    )
                # active context가 살아있는 경우에만 trace-level 필드를 업데이트한다.
                if context_manager is not None:
                    update_current_trace = getattr(self._client, "update_current_trace", None)
                    if callable(update_current_trace):
                        update_current_trace(
                            name=name,
                            input=fields["event_input"],
                            output=fields["event_output"],
                            metadata=fields["metadata"],
                            user_id=fields["user_id"],
                            session_id=fields["session_id"],
                            version=fields["version"],
                            tags=fields["tags"],
                            public=fields["public"],
                        )

                end = getattr(span_obj, "end", None)
                if callable(end):
                    end()
                if context_manager is not None:
                    context_manager.__exit__(None, None, None)
            flush = getattr(self._client, "flush", None)
            if callable(flush):
                flush()
        except Exception:
            return

    def log_trace(self, name: str, payload: Dict[str, Any]) -> None:
        # SDK v3에서는 trace 레벨 input/output 표시를 위해 current span + trace update를 사용한다.
        # 구버전(v2)의 trace는 마지막 fallback으로만 사용한다.
        try:
            fields = self._prepare_fields(name, payload)

            start_as_current_span = getattr(self._client, "start_as_current_span", None)
            if callable(start_as_current_span):
                with start_as_current_span(
                    name=name,
                    input=fields["event_input"],
                    output=fields["event_output"],
                    metadata=fields["metadata"],
                    level=fields["level"],
                    status_message=fields["status_message"],
                    version=fields["version"],
                ):
                    update_current_trace = getattr(self._client, "update_current_trace", None)
                    if callable(update_current_trace):
                        update_current_trace(
                            name=name,
                            input=fields["event_input"],
                            output=fields["event_output"],
                            metadata=fields["metadata"],
                            user_id=fields["user_id"],
                            session_id=fields["session_id"],
                            version=fields["version"],
                            tags=fields["tags"],
                            public=fields["public"],
                        )
                flush = getattr(self._client, "flush", None)
                if callable(flush):
                    flush()
                return

            create_event = getattr(self._client, "create_event", None)
            if callable(create_event):
                create_event(
                    name=name,
                    input=fields["event_input"],
                    output=fields["event_output"],
                    metadata=fields["metadata"],
                    level=fields["level"],
                    status_message=fields["status_message"],
                    version=fields["version"],
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
