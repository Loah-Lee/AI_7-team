from __future__ import annotations

# 오프라인 스모크 테스트용 TF-IDF 입니다.
# 네트워크 다운로드 없이 동작합니다.

import json
import math
import re
from pathlib import Path
from typing import Iterable, List, Tuple

from sklearn.feature_extraction.text import TfidfVectorizer


def _iter_jsonl_files(input_dir: Path) -> Iterable[Path]:
    return (
        p
        for p in sorted(input_dir.rglob("*.jsonl"))
        if p.is_file()
    )


def _preview(text: str, max_len: int = 200) -> str:
    preview = re.sub(r"\s+", " ", text).strip()
    if len(preview) > max_len:
        return preview[:max_len] + "..."
    return preview


def _cosine(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / math.sqrt(na * nb)


def _load_records(input_dir: Path) -> List[dict]:
    records: List[dict] = []
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
                text = str(record.get("text", "")).strip()
                if not text:
                    continue
                records.append(record)
    return records


def main() -> None:
    input_dir = Path("data_chunks")
    if not input_dir.exists():
        print(f"data_chunks not found: {input_dir}")
        return

    vectorizer = TfidfVectorizer(
        analyzer="char_wb",
        ngram_range=(2, 5),
    )

    records = _load_records(input_dir)
    if not records:
        print("데이터가 없습니다.")
        return

    texts = [str(r.get("text", "")) for r in records]
    vectors = vectorizer.fit_transform(texts).toarray().tolist()

    while True:
        try:
            query = input("검색어를 입력하세요 (종료: 빈 입력): ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not query:
            return

        q_vec = vectorizer.transform([query]).toarray().tolist()[0]
        scored: List[Tuple[float, dict]] = []
        for vec, record in zip(vectors, records):
            score = _cosine(q_vec, vec)
            scored.append((score, record))
        scored.sort(key=lambda x: x[0], reverse=True)

        for score, record in scored[:5]:
            source_path = record.get("source_path", "")
            chunk_index = record.get("chunk_index", "")
            text = str(record.get("text", ""))
            print(f"- similarity={score:.4f} | source_path={source_path} | chunk_index={chunk_index}")
            print(f"  text={_preview(text)}")


if __name__ == "__main__":
    main()
