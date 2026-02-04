from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterable, List, Tuple


def _iter_jsonl_files(input_dir: Path) -> Iterable[Path]:
    return (
        p
        for p in sorted(input_dir.rglob("*.jsonl"))
        if p.is_file()
    )


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _score(query: str, text: str) -> int:
    if not query:
        return 0
    q = _normalize(query)
    t = _normalize(text)
    if not t:
        return 0
    # 단순 점수: 정확한 구문 포함은 가중치, 단어 포함은 합산
    score = 0
    if q in t:
        score += len(q)
    for term in q.split(" "):
        if term and term in t:
            score += len(term)
    return score


def _preview(text: str, max_len: int = 200) -> str:
    preview = re.sub(r"\s+", " ", text).strip()
    if len(preview) > max_len:
        return preview[:max_len] + "..."
    return preview


def _search(
    input_dir: Path = Path("data_chunks"),
    *,
    top_k: int = 5,
) -> List[Tuple[int, dict]]:
    results: List[Tuple[int, dict]] = []
    for path in _iter_jsonl_files(input_dir):
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                text = str(record.get("text", ""))
                score = _score(_search.query, text)
                if score <= 0:
                    continue
                results.append((score, record))
    results.sort(key=lambda x: x[0], reverse=True)
    return results[:top_k]


def main() -> None:
    input_dir = Path("data_chunks")
    if not input_dir.exists():
        print(f"data_chunks not found: {input_dir}")
        return

    while True:
        try:
            query = input("검색어를 입력하세요 (종료: 빈 입력): ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not query:
            return

        _search.query = query  # type: ignore[attr-defined]
        results = _search(input_dir=input_dir, top_k=5)

        if not results:
            print("결과 없음")
            continue

        for score, record in results:
            source_path = record.get("source_path", "")
            chunk_index = record.get("chunk_index", "")
            text = str(record.get("text", ""))
            print(f"- score={score} | source_path={source_path} | chunk_index={chunk_index}")
            print(f"  text={_preview(text)}")


if __name__ == "__main__":
    main()
