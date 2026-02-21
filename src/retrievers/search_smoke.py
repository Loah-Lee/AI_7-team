from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Iterable, List, Tuple


def _iter_jsonl_files(input_dir: Path) -> Iterable[Path]:
    return (
        p
        for p in sorted(input_dir.rglob("*.jsonl"))
        if p.is_file()
    )


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    return re.sub(r"\s+", " ", text).strip().lower()


def _normalize_compact(text: str) -> str:
    return re.sub(r"\s+", "", _normalize(text))


def _extract_org_prefix(query: str) -> str | None:
    toks = query.strip().split()
    if not toks:
        return None
    cand = unicodedata.normalize("NFC", toks[0].strip())
    if len(cand) < 2:
        return None
    # 운영용 간단 규칙: 기관명형 접미/표식
    if re.search(r"(공사|공단|재단|재단법인|공단|대학교|대학|병원|정보원|공단|주식회사|\(주\)|원)$", cand):
        return cand
    if cand.startswith("한국"):
        return cand
    return None


def _record_matches_org(record: dict, org: str | None) -> bool:
    if not org:
        return True
    org_n = _normalize(org)
    org_c = _normalize_compact(org)
    source_path = _normalize(str(record.get("source_path", "")))
    source_compact = _normalize_compact(str(record.get("source_path", "")))
    return org_n in source_path or org_c in source_compact


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
    input_dir: Path = Path("notebooks") / "data_chunks_rich",
    *,
    top_k: int = 5,
    org_filter: str | None = None,
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
                if not _record_matches_org(record, org_filter):
                    continue
                score = _score(_search.query, text)
                if score <= 0:
                    continue
                results.append((score, record))
    results.sort(key=lambda x: x[0], reverse=True)
    return results[:top_k]


def main() -> None:
    input_dir = Path("notebooks") / "data_chunks_rich"
    if not input_dir.exists():
        print(f"data_chunks_rich not found: {input_dir}")
        return

    session_org: str | None = None
    while True:
        try:
            query = input("검색어를 입력하세요 (종료: 빈 입력): ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not query:
            return

        detected_org = _extract_org_prefix(query)
        if detected_org:
            if session_org != detected_org:
                session_org = detected_org
                print(f"[ORG] 기관 컨텍스트 설정: {session_org}")
            effective_query = query
        else:
            effective_query = f"{session_org} {query}".strip() if session_org else query
            if session_org:
                print(f"[ORG] 기관 컨텍스트 유지: {session_org}")

        _search.query = query  # type: ignore[attr-defined]
        _search.query = effective_query  # type: ignore[attr-defined]
        results = _search(input_dir=input_dir, top_k=5, org_filter=session_org)

        if not results:
            print("문서에 해당 정보가 없습니다.")
            continue

        for score, record in results:
            source_path = record.get("source_path", "")
            chunk_index = record.get("chunk_index", "")
            text = str(record.get("text", ""))
            print(f"- score={score} | source_path={source_path} | chunk_index={chunk_index}")
            print(f"  text={_preview(text)}")


if __name__ == "__main__":
    main()
