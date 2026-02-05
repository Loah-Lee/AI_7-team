from __future__ import annotations

import json
import os
import re
from typing import Dict, List, Tuple


def _log_fail(stage: str, input_desc: str, exc: Exception) -> None:
    print(f"INGEST FAIL | {stage} | {input_desc} | {type(exc).__name__}: {exc}")


def _get_client():
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY 환경변수가 설정되지 않았습니다.")
    from openai import OpenAI  # type: ignore

    return OpenAI(api_key=api_key)


def _normalize_ids(value: object, n: int) -> List[int] | None:
    if not isinstance(value, list):
        return None
    indices: List[int] = []
    for item in value:
        if isinstance(item, int):
            if 0 <= item < n:
                indices.append(item)
            else:
                return None
        elif isinstance(item, str) and item.isdigit():
            idx = int(item)
            if 0 <= idx < n:
                indices.append(idx)
            else:
                return None
        else:
            return None
    return indices if len(indices) == n else None


def rerank_openai(
    query: str,
    candidates: List[Dict[str, object]],
    *,
    model: str = "gpt-5-nano",
) -> Tuple[List[Dict[str, object]], float]:
    if not candidates:
        return candidates, 0.0

    try:
        client = _get_client()
        items = []
        for idx, cand in enumerate(candidates):
            text = str(cand.get("text", ""))
            snippet = re.sub(r"\s+", " ", text.strip())[:240]
            items.append(
                {
                    "index": idx,
                    "source_path": str(cand.get("source_path", "")),
                    "chunk_id": str(cand.get("chunk_id", "")),
                    "text": snippet,
                }
            )

        payload = {
            "query": query,
            "candidates": items,
            "instruction": "Return JSON with key 'order' as a list of indexes in best-first order.",
        }

        response = client.responses.create(
            model=model,
            input=[
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": json.dumps(payload, ensure_ascii=False)},
                    ],
                }
            ],
        )

        text = getattr(response, "output_text", None) or ""
        if not text:
            text_parts = []
            for item in getattr(response, "output", []) or []:
                if getattr(item, "type", "") == "message":
                    for content in getattr(item, "content", []) or []:
                        if getattr(content, "type", "") in {"output_text", "text"}:
                            text_parts.append(getattr(content, "text", ""))
            text = "\n".join(text_parts).strip()

        data = json.loads(text)
        order = data.get("order")
        indices = _normalize_ids(order, len(candidates))
        if indices is None:
            raise ValueError("Invalid rerank order")

        reranked = [candidates[i] for i in indices]
        return reranked, 0.0
    except Exception as exc:
        _log_fail("rerank_llm", "openai", exc)
        return candidates, 0.0
