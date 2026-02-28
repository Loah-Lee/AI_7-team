#!/usr/bin/env python3
"""현재 Chroma DB 기준으로 eval_dataset의 GT chunk 라벨을 재동기화한다.

원칙:
- source-constrained: ground_truth.sources 안에서만 후보를 탐색
- non-leaky(runtime): retrieval 결과/생성답변은 사용하지 않음
- 평가용 라벨 동기화 전용(운영 파이프라인에는 미사용)
"""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from pathlib import Path
from typing import Any

import chromadb
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = PROJECT_ROOT / "eval_resources" / "eval_dataset.yaml"
DEFAULT_OUTPUT = PROJECT_ROOT / "eval_resources" / "eval_dataset_chunk_synced.yaml"
DEFAULT_REVIEW = PROJECT_ROOT / "eval_resources" / "chunk_label_candidates_source_constrained_sync.json"
DEFAULT_DB = PROJECT_ROOT / "data_index" / "chroma_B"
DEFAULT_COLLECTION = "chunks"

TOKEN_RE = re.compile(r"[0-9A-Za-z가-힣]+")
NUM_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")
SOURCE_EXT_RE = re.compile(r"\.(pdf|hwp|hwpx|csv)$", re.IGNORECASE)

STOPWORDS = {
    "사업", "시스템", "구축", "기능", "개선", "용역", "관련", "정보", "기관", "기준", "대한", "및", "에서",
    "what", "which", "where", "when", "with", "for", "the", "and", "of",
}


def _normalize_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).lower()
    return re.sub(r"\s+", " ", text).strip()


def _normalize_source_label(value: str | None) -> str:
    label = _normalize_text(value)
    if not label:
        return ""
    label = label.replace("\\", "/").rsplit("/", 1)[-1]
    return SOURCE_EXT_RE.sub("", label).strip()


def _normalize_source_key(value: str | None) -> str:
    label = _normalize_source_label(value)
    return re.sub(r"[^0-9a-zA-Z가-힣]+", "", label)


def _tokenize(value: str) -> set[str]:
    tokens = {
        t
        for t in TOKEN_RE.findall(_normalize_text(value))
        if len(t) >= 2 and t not in STOPWORDS
    }
    return tokens


def _extract_numbers(value: str) -> set[str]:
    nums: set[str] = set()
    for raw in NUM_RE.findall(_normalize_text(value)):
        nums.add(raw.replace(",", ""))
    return nums


def _parse_chunk_order(value: Any) -> int | None:
    if value is None:
        return None
    marker = str(value).strip()
    if not marker:
        return None
    if marker.isdigit():
        try:
            return int(marker)
        except Exception:
            return None
    if "_" in marker:
        tail = marker.rsplit("_", 1)[-1].strip()
        if tail.isdigit():
            try:
                return int(tail)
            except Exception:
                return None
    return None


def _iter_source_chunks(collection: Any, source_label: str, batch_size: int = 1000) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    offset = 0
    while True:
        payload = collection.get(
            where={"source": source_label},
            include=["documents", "metadatas"],
            limit=batch_size,
            offset=offset,
        )
        ids = payload.get("ids", []) or []
        docs = payload.get("documents", []) or []
        metas = payload.get("metadatas", []) or []
        if not ids:
            break
        for idx, doc_id in enumerate(ids):
            md = metas[idx] if idx < len(metas) and isinstance(metas[idx], dict) else {}
            text = str(docs[idx] if idx < len(docs) else "")
            chunk_id_raw = md.get("chunk_id") if md.get("chunk_id") is not None else md.get("uid")
            chunk_id = str(chunk_id_raw).strip() if chunk_id_raw is not None else str(doc_id)
            if not chunk_id:
                chunk_id = str(doc_id)
            chunk_index_raw = md.get("chunk_index") if md.get("chunk_index") is not None else md.get("chunk_order")
            try:
                chunk_index = int(chunk_index_raw) if chunk_index_raw is not None else None
            except Exception:
                chunk_index = None
            if chunk_index is None:
                chunk_index = _parse_chunk_order(chunk_id) or _parse_chunk_order(doc_id)

            rows.append(
                {
                    "id": str(doc_id),
                    "source": source_label,
                    "text": text,
                    "chunk_id": chunk_id,
                    "chunk_index": chunk_index,
                    "page": md.get("page"),
                }
            )
        offset += len(ids)
    return rows


def _build_source_name_index(collection: Any, batch_size: int = 2000) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """DB의 실제 source 값을 정규화 키로 인덱싱한다."""
    by_label: dict[str, list[str]] = {}
    by_key: dict[str, list[str]] = {}

    total = int(collection.count())
    offset = 0
    while offset < total:
        payload = collection.get(include=["metadatas"], limit=batch_size, offset=offset)
        ids = payload.get("ids", []) or []
        metas = payload.get("metadatas", []) or []
        if not ids:
            break

        for md in metas:
            if not isinstance(md, dict):
                continue
            raw_source = str(md.get("source") or "").strip()
            if not raw_source:
                continue
            label = _normalize_source_label(raw_source)
            key = _normalize_source_key(raw_source)
            if label:
                by_label.setdefault(label, [])
                if raw_source not in by_label[label]:
                    by_label[label].append(raw_source)
            if key:
                by_key.setdefault(key, [])
                if raw_source not in by_key[key]:
                    by_key[key].append(raw_source)
        offset += len(ids)
    return by_label, by_key


def _score_candidate(
    chunk_text: str,
    question_tokens: set[str],
    expected_tokens: set[str],
    expected_numbers: set[str],
    expected_phrases: list[str],
) -> tuple[float, dict[str, Any]]:
    text_norm = _normalize_text(chunk_text)
    text_tokens = _tokenize(text_norm)
    if not text_tokens and not text_norm:
        return 0.0, {
            "ov_q": 0.0,
            "ov_e": 0.0,
            "num_hit": 0,
            "phrase_hit": 0,
        }

    ov_q = len(question_tokens & text_tokens) / max(len(question_tokens), 1)
    ov_e = len(expected_tokens & text_tokens) / max(len(expected_tokens), 1)

    text_nums = _extract_numbers(text_norm)
    num_hit = len(expected_numbers & text_nums)

    phrase_hit = 0
    for phrase in expected_phrases:
        if phrase and phrase in text_norm:
            phrase_hit += 1

    score = (
        1.8 * ov_q
        + 3.2 * ov_e
        + 1.4 * float(num_hit)
        + 1.6 * float(min(phrase_hit, 2))
    )
    details = {
        "ov_q": round(ov_q, 4),
        "ov_e": round(ov_e, 4),
        "num_hit": num_hit,
        "phrase_hit": phrase_hit,
    }
    return score, details


def _passes_hard_constraints(
    question: str,
    query_type: str,
    chunk_text: str,
    details: dict[str, Any],
    expected_numbers: set[str],
) -> bool:
    q = _normalize_text(question)
    t = _normalize_text(chunk_text)
    ov_q = float(details.get("ov_q", 0.0) or 0.0)
    ov_e = float(details.get("ov_e", 0.0) or 0.0)
    phrase_hit = int(details.get("phrase_hit", 0) or 0)
    num_hit = int(details.get("num_hit", 0) or 0)

    # 숫자만 맞아서 뜨는 테이블 노이즈를 차단한다.
    min_overlap = 0.02 if str(query_type).strip().lower() == "multi_doc" else 0.05
    if (ov_q + ov_e) < min_overlap and phrase_hit == 0:
        return False

    # 가이드 질의는 실제 guide/guideline 키워드 포함 청크만 허용한다.
    if any(token in q for token in ("가이드", "guideline", "guide", "economic analysis", "cost-benefit")):
        if not any(marker in t for marker in ("guideline", "guide to", "guidelines for", "adb", "european commission")):
            return False

    # 도면/치수 질의는 수치+단위/구조 표현이 있는 청크만 허용한다.
    if any(token in q for token in ("치수", "규격", "가로", "세로", "도면", "mm", "분할")):
        has_mm = "mm" in t
        has_layout = any(marker in t for marker in ("도면", "평면도", "가운데 문", "최소규격", "최대규격"))
        has_numeric_pattern = bool(re.search(r"\d[\d,]*\s*/\s*\d[\d,]*\s*/\s*\d[\d,]*", t))
        # expected 숫자가 있으면 최소 2개 이상 매칭되어야 신뢰.
        if expected_numbers and num_hit < 2:
            return False
        if not (has_mm or has_layout or has_numeric_pattern):
            return False

    return True


def _build_expected_phrases(expected_answer: str) -> list[str]:
    # 너무 긴 문장 전체 매칭 대신, 정보량 있는 구절만 사용한다.
    parts = re.split(r"[,\n;:()]+", _normalize_text(expected_answer))
    phrases = []
    for part in parts:
        p = part.strip(" -•\t")
        if len(p) < 8:
            continue
        if len(_tokenize(p)) < 2:
            continue
        phrases.append(p)
    # 중복 제거 + 상위 6개만
    return list(dict.fromkeys(phrases))[:6]


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync GT chunk labels in eval dataset against current Chroma DB.")
    parser.add_argument("--dataset", type=str, default=str(DEFAULT_DATASET))
    parser.add_argument("--output", type=str, default=str(DEFAULT_OUTPUT))
    parser.add_argument("--review-json", type=str, default=str(DEFAULT_REVIEW))
    parser.add_argument("--db-path", type=str, default=str(DEFAULT_DB))
    parser.add_argument("--collection", type=str, default=DEFAULT_COLLECTION)
    parser.add_argument("--batch-size", type=int, default=1000)
    parser.add_argument("--min-score", type=float, default=0.85)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    dataset_path = Path(args.dataset).resolve()
    output_path = Path(args.output).resolve()
    review_path = Path(args.review_json).resolve()

    if not dataset_path.exists():
        raise FileNotFoundError(f"dataset not found: {dataset_path}")

    data = yaml.safe_load(dataset_path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("dataset must be list[dict]")

    client = chromadb.PersistentClient(path=str(Path(args.db_path).resolve()))
    collection = client.get_collection(args.collection)

    cache_by_source: dict[str, list[dict[str, Any]]] = {}
    source_index_by_label, source_index_by_key = _build_source_name_index(collection)
    review_rows: list[dict[str, Any]] = []

    changed = 0
    unresolved = 0

    for item in data:
        if not isinstance(item, dict):
            continue
        gt = item.get("ground_truth", {})
        if not isinstance(gt, dict):
            continue
        sources = gt.get("sources", []) or []
        if not isinstance(sources, list) or not sources:
            continue

        # CSV 질의는 chunk GT를 쓰지 않으므로 skip.
        source_labels = [_normalize_source_label(src) for src in sources]
        source_labels = [s for s in source_labels if s and s != "data_list"]
        if not source_labels:
            continue

        question = str(item.get("question", "") or "")
        query_type = str(item.get("query_type", "") or "")
        expected_answer = str(item.get("expected_answer", "") or "")
        q_tokens = _tokenize(question)
        e_tokens = _tokenize(expected_answer)
        e_numbers = _extract_numbers(expected_answer)
        e_phrases = _build_expected_phrases(expected_answer)

        existing_orders = gt.get("chunk_orders", []) or []
        existing_uids = gt.get("chunk_uids", []) or []
        target_n = max(1, len(source_labels), len(existing_orders), len(existing_uids))

        by_source_top: list[dict[str, Any]] = []
        all_scored: list[dict[str, Any]] = []

        for source in source_labels:
            actual_sources = source_index_by_label.get(source, [])
            if not actual_sources:
                actual_sources = source_index_by_key.get(_normalize_source_key(source), [])
            if not actual_sources:
                # 마지막 fallback: 부분문자열 기반 느슨한 매칭
                key = _normalize_source_key(source)
                if key:
                    fuzzy_hits = [
                        raw
                        for raw_list in source_index_by_label.values()
                        for raw in raw_list
                        if key and key in _normalize_source_key(raw)
                    ]
                    actual_sources = list(dict.fromkeys(fuzzy_hits))[:3]

            source_candidates: list[dict[str, Any]] = []
            for actual_source in actual_sources:
                if actual_source not in cache_by_source:
                    cache_by_source[actual_source] = _iter_source_chunks(
                        collection,
                        source_label=actual_source,
                        batch_size=max(1, int(args.batch_size)),
                    )
                source_candidates.extend(cache_by_source[actual_source])

            candidates = source_candidates

            scored_rows: list[dict[str, Any]] = []
            for row in candidates:
                score, details = _score_candidate(
                    chunk_text=row.get("text", ""),
                    question_tokens=q_tokens,
                    expected_tokens=e_tokens,
                    expected_numbers=e_numbers,
                    expected_phrases=e_phrases,
                )
                scored_rows.append(
                    {
                        "source": row.get("source") or source,
                        "chunk_id": row.get("chunk_id"),
                        "chunk_index": row.get("chunk_index"),
                        "score": float(score),
                        "acceptable": _passes_hard_constraints(
                            question=question,
                            query_type=query_type,
                            chunk_text=row.get("text", ""),
                            details=details,
                            expected_numbers=e_numbers,
                        ),
                        "details": details,
                        "snippet": _normalize_text(row.get("text", ""))[:260],
                    }
                )
            scored_rows.sort(key=lambda x: x.get("score", 0.0), reverse=True)
            all_scored.extend(scored_rows[:20])
            if scored_rows:
                by_source_top.append(scored_rows[0])

        selected: list[dict[str, Any]] = []
        seen_ids: set[str] = set()

        # 1) source 다양성 확보: source별 top1 우선 선택
        for row in sorted(by_source_top, key=lambda x: x.get("score", 0.0), reverse=True):
            cid = str(row.get("chunk_id") or "").strip()
            if not cid or cid in seen_ids:
                continue
            if not bool(row.get("acceptable", False)):
                continue
            if float(row.get("score", 0.0)) < float(args.min_score):
                continue
            selected.append(row)
            seen_ids.add(cid)

        # 2) 부족분은 전체 상위 후보로 채움
        all_scored.sort(key=lambda x: x.get("score", 0.0), reverse=True)
        for row in all_scored:
            if len(selected) >= target_n:
                break
            cid = str(row.get("chunk_id") or "").strip()
            if not cid or cid in seen_ids:
                continue
            if not bool(row.get("acceptable", False)):
                continue
            if float(row.get("score", 0.0)) < float(args.min_score):
                continue
            selected.append(row)
            seen_ids.add(cid)

        selected_uids: list[str] = []
        selected_orders: list[int] = []
        for row in selected:
            cid = str(row.get("chunk_id") or "").strip()
            if not cid:
                continue
            selected_uids.append(cid)
            order = _parse_chunk_order(cid)
            if order is None:
                order = _parse_chunk_order(row.get("chunk_index"))
            if order is not None:
                selected_orders.append(order)

        selected_uids = list(dict.fromkeys(selected_uids))
        selected_orders = list(dict.fromkeys(selected_orders))

        review_rows.append(
            {
                "id": item.get("id"),
                "query_type": item.get("query_type"),
                "sources": source_labels,
                "target_n": target_n,
                "selected_chunk_uids": selected_uids,
                "selected_chunk_orders": selected_orders,
                "top_candidates": all_scored[:8],
            }
        )

        if not selected_uids:
            unresolved += 1
            continue

        old_uids = [str(x) for x in existing_uids]
        old_orders = [int(x) for x in existing_orders if str(x).strip().isdigit()]
        if old_uids != selected_uids or old_orders != selected_orders:
            gt["chunk_uids"] = selected_uids
            gt["chunk_orders"] = selected_orders
            changed += 1

    review_path.parent.mkdir(parents=True, exist_ok=True)
    review_path.write_text(
        json.dumps(review_rows, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    if args.dry_run:
        print(
            f"[DRY-RUN] changed={changed}, unresolved={unresolved}, "
            f"review_json={review_path}"
        )
        return

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    print(
        f"[APPLY] changed={changed}, unresolved={unresolved}, "
        f"output={output_path}, review_json={review_path}"
    )


if __name__ == "__main__":
    main()
