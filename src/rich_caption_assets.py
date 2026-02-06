from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Dict, List, Tuple


def _log_start(input_path: Path, output_path: Path) -> None:
    print(f"INGEST START | input={input_path} | output={output_path}")


def _log_ok(stage: str, input_path: Path, output_path: Path) -> None:
    print(f"INGEST OK | {stage} | {input_path} -> {output_path}")


def _log_fail(stage: str, input_path: Path, exc: Exception) -> None:
    print(f"INGEST FAIL | {stage} | {input_path} | {type(exc).__name__}: {exc}")


def _get_client():
    _load_env()
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY 환경변수가 설정되지 않았습니다.")

    try:
        from openai import OpenAI  # type: ignore
    except Exception as exc:  # pragma: no cover - optional dependency
        raise RuntimeError("openai SDK가 설치되지 않았습니다. pip install openai 로 설치하세요.") from exc

    return OpenAI(api_key=api_key)


def _load_env() -> None:
    """Load .env from repo root if available, without exposing contents."""
    try:
        from dotenv import load_dotenv  # type: ignore

        load_dotenv()
        return
    except Exception:
        pass

    env_path = Path(".env")
    if not env_path.exists():
        return

    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _encode_image(path: Path) -> str:
    data = path.read_bytes()
    b64 = base64.b64encode(data).decode("utf-8")
    return f"data:image/png;base64,{b64}"


def _extract_text(response) -> str:
    if hasattr(response, "output_text"):
        return (response.output_text or "").strip()
    text_parts: List[str] = []
    for item in getattr(response, "output", []) or []:
        if getattr(item, "type", "") == "message":
            for content in getattr(item, "content", []) or []:
                if getattr(content, "type", "") in {"output_text", "text"}:
                    text_parts.append(getattr(content, "text", ""))
    return "\n".join(p.strip() for p in text_parts if p.strip()).strip()


def _caption_prompt(is_table: bool) -> str:
    if is_table:
        return (
            "다음 이미지는 표로 추정됩니다. 표의 셀 텍스트를 최대한 정확히 추출해 주세요. "
            "반환은 반드시 JSON 형식으로 하세요. 키는 caption, table_text 입니다. "
            "caption은 표의 제목/요약, table_text는 표 내용입니다."
        )
    return (
        "다음 이미지를 보고 한국어로 간결한 캡션을 작성하세요. "
        "표가 아니면 table_text는 빈 문자열로 해주세요. "
        "반환은 반드시 JSON 형식으로 하세요. 키는 caption, table_text 입니다."
    )


def _is_table_like_heuristic(image_path: Path) -> bool | None:
    name = image_path.name.lower()
    if any(token in name for token in ["table", "tbl", "표", "sheet", "grid"]):
        return True
    if any(token in name for token in ["chart", "graph", "plot", "fig"]):
        return False
    return None


def _classify_table_llm(client, image_path: Path) -> bool:
    payload = [
        {
            "role": "user",
            "content": [
                {
                    "type": "input_text",
                    "text": "이 이미지는 표인가요? 표면 table, 아니면 other 로만 답하세요.",
                },
                {"type": "input_image", "image_url": _encode_image(image_path)},
            ],
        }
    ]
    response = client.responses.create(model="gpt-5-nano", input=payload)
    text = _extract_text(response).strip().lower()
    return "table" in text and "other" not in text


def _is_table_like(client, image_path: Path) -> bool:
    guess = _is_table_like_heuristic(image_path)
    if guess is not None:
        return guess
    try:
        return _classify_table_llm(client, image_path)
    except Exception:
        return False


def _request_caption(client, image_path: Path) -> Tuple[str, str]:
    max_attempts = 2
    is_table = _is_table_like(client, image_path)
    payload = [
        {
            "role": "user",
            "content": [
                {
                    "type": "input_text",
                    "text": _caption_prompt(is_table),
                },
                {"type": "input_image", "image_url": _encode_image(image_path)},
            ],
        }
    ]

    response = None
    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            response = client.responses.create(
                model="gpt-5-mini",
                input=payload,
            )
            break
        except Exception as exc:
            last_exc = exc
            if attempt >= max_attempts or not _is_retryable_error(exc):
                break
            time.sleep(0.5 * attempt)

    if response is None:
        if last_exc is not None:
            raise last_exc
        raise RuntimeError("응답을 생성하지 못했습니다.")

    text = _extract_text(response)

    try:
        data = json.loads(text)
        caption = str(data.get("caption", "")).strip()
        table_text = str(data.get("table_text", "")).strip()
        return caption, table_text
    except Exception:
        return text.strip(), ""


def _update_markdown(md_path: Path, image_rel: str, caption: str, table_text: str) -> None:
    content = md_path.read_text(encoding="utf-8")
    pattern = re.compile(rf"!\[PLACEHOLDER\]\({re.escape(image_rel)}\)")
    replacement = f"![{caption}](%s)" % image_rel

    if not pattern.search(content):
        return

    content = pattern.sub(replacement, content, count=1)
    if table_text:
        content = content.replace(
            replacement,
            replacement + "\n\n```\n" + table_text.strip() + "\n```",
            1,
        )

    md_path.write_text(content, encoding="utf-8")


def caption_assets(
    assets_root: Path = Path("notebooks") / "data_assets",
    rich_root: Path = Path("notebooks") / "data_rich",
    only_failed: bool = False,
) -> Dict[str, int]:
    _log_start(assets_root, rich_root)

    if not assets_root.exists():
        exc = FileNotFoundError(f"Assets directory not found: {assets_root}")
        _log_fail("scan", assets_root, exc)
        raise exc

    client = _get_client()

    images = [p for p in sorted(assets_root.rglob("*.png")) if p.is_file()]
    summary = {"processed": 0, "succeeded": 0, "failed": 0}

    for img_path in images:
        summary["processed"] += 1
        doc_id = img_path.parent.name
        md_path = rich_root / f"{doc_id}.md"
        manifest_path = rich_root / f"{doc_id}.manifest.json"
        if not md_path.exists():
            exc = FileNotFoundError(f"Markdown not found for doc_id={doc_id}")
            _log_fail("caption", img_path, exc)
            summary["failed"] += 1
            continue

        try:
            image_rel = (Path("..") / "data_assets" / doc_id / img_path.name).as_posix()
            if only_failed and not _needs_caption(md_path, manifest_path, image_rel):
                continue

            caption, table_text = _request_caption(client, img_path)
            _update_markdown(md_path, image_rel, caption or "이미지", table_text)
            _log_ok("caption", img_path, md_path)
            summary["succeeded"] += 1
            time.sleep(0.2)
        except Exception as exc:
            if _is_connection_error(exc):
                _log_fail("caption", img_path, exc)
                raise
            _log_fail("caption", img_path, exc)
            summary["failed"] += 1

    return summary


def _needs_caption(md_path: Path, manifest_path: Path, image_rel: str) -> bool:
    if _has_placeholder(md_path, image_rel):
        return True
    if manifest_path.exists() and _manifest_marks_missing(manifest_path, image_rel):
        return True
    return False


def _has_placeholder(md_path: Path, image_rel: str) -> bool:
    content = md_path.read_text(encoding="utf-8")
    pattern = re.compile(rf"!\[PLACEHOLDER\]\({re.escape(image_rel)}\)")
    return bool(pattern.search(content))


def _manifest_marks_missing(manifest_path: Path, image_rel: str) -> bool:
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return False

    target_name = Path(image_rel).name
    keys = {
        "caption_missing",
        "missing_captions",
        "caption_failed",
        "failed_captions",
        "missing_assets",
        "failed_assets",
    }

    for key, value in data.items():
        if key not in keys or not isinstance(value, list):
            continue
        for item in value:
            if not isinstance(item, str):
                continue
            if item == image_rel or Path(item).name == target_name:
                return True
    return False


def _is_retryable_error(exc: Exception) -> bool:
    name = type(exc).__name__
    return name in {"APIConnectionError", "APITimeoutError", "TimeoutError"}


def _is_connection_error(exc: Exception) -> bool:
    return type(exc).__name__ == "APIConnectionError"


def _healthcheck() -> int:
    endpoint = Path("openai")
    try:
        client = _get_client()
        client.models.list()
        _log_ok("healthcheck", endpoint, endpoint)
        return 0
    except Exception as exc:
        _log_fail("healthcheck", endpoint, exc)
        return 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--healthcheck", action="store_true")
    parser.add_argument("--only-failed", action="store_true")
    args = parser.parse_args()

    if args.healthcheck:
        raise SystemExit(_healthcheck())

    caption_assets(only_failed=args.only_failed)
