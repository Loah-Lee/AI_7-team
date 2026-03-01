#!/usr/bin/env python3
"""검색 결과 후처리 유틸.

workflow 오케스트레이터에서 사용하던 결과 병합/다양화/클러스터 페널티 로직을
리트리버 모듈로 분리한다.
"""

from __future__ import annotations

from typing import Any, Callable


def diversify_comparison_results(results: list[dict[str, Any]], top_window: int = 10) -> list[dict[str, Any]]:
    """비교 질의에서 상위 구간의 기관 편중을 완화한다."""
    if len(results) <= 2:
        return results

    buckets: dict[str, list[dict[str, Any]]] = {}
    for item in results:
        org = str((item.get("metadata", {}) or {}).get("org", "")).strip()
        key = org or str((item.get("metadata", {}) or {}).get("source", "")).strip()
        buckets.setdefault(key, []).append(item)

    if len(buckets) < 2:
        return results

    top_orgs = sorted(
        buckets.keys(),
        key=lambda k: len(buckets[k]),
        reverse=True,
    )[:2]
    selected: list[dict[str, Any]] = []
    used_ids: set[int] = set()
    round_limit = min(max(2, top_window), len(results))
    while len(selected) < round_limit:
        progressed = False
        for org in top_orgs:
            while buckets[org]:
                candidate = buckets[org].pop(0)
                cid = id(candidate)
                if cid in used_ids:
                    continue
                selected.append(candidate)
                used_ids.add(cid)
                progressed = True
                break
            if len(selected) >= round_limit:
                break
        if not progressed:
            break

    for item in results:
        cid = id(item)
        if cid in used_ids:
            continue
        selected.append(item)
        used_ids.add(cid)
    return selected


def extract_chunk_index_value(item: dict[str, Any]) -> int | None:
    md = item.get("metadata", {}) or {}
    for key in ("chunk_index", "chunk_order"):
        value = md.get(key)
        try:
            parsed = int(value)
        except Exception:
            continue
        if parsed >= 0:
            return parsed
    value = item.get("chunk_index")
    try:
        parsed = int(value)
    except Exception:
        return None
    return parsed if parsed >= 0 else None


def apply_source_cluster_penalty(
    scored: list[tuple[float, int, dict[str, Any]]],
    top_window: int,
    *,
    normalize_text_for_match: Callable[[str], str],
) -> list[tuple[float, int, dict[str, Any]]]:
    """동일 source의 인접 청크 과밀 노출을 완화한다."""
    if len(scored) <= 2:
        return scored

    scored_sorted = sorted(scored, key=lambda x: (x[0], -x[1]), reverse=True)
    window = min(max(4, top_window), len(scored_sorted))
    head = list(scored_sorted[:window])
    tail = list(scored_sorted[window:])
    selected: list[tuple[float, int, dict[str, Any]]] = []

    while head:
        best_idx = 0
        best_adjusted = float("-inf")
        for idx, (base_score, _original_idx, item) in enumerate(head):
            md = item.get("metadata", {}) or {}
            source_key = normalize_text_for_match(str(md.get("source", "") or ""))
            chunk_index = extract_chunk_index_value(item)
            penalty = 0.0
            for _s, _i, picked in selected[-6:]:
                pmd = picked.get("metadata", {}) or {}
                picked_source_key = normalize_text_for_match(str(pmd.get("source", "") or ""))
                if not source_key or source_key != picked_source_key:
                    continue
                picked_chunk_index = extract_chunk_index_value(picked)
                if chunk_index is not None and picked_chunk_index is not None:
                    distance = abs(chunk_index - picked_chunk_index)
                    if distance <= 2:
                        penalty += 1.6
                    elif distance <= 5:
                        penalty += 0.6
                    else:
                        penalty += 0.15
                else:
                    penalty += 0.25
            adjusted = base_score - penalty
            if adjusted > best_adjusted:
                best_adjusted = adjusted
                best_idx = idx
        selected.append(head.pop(best_idx))

    return selected + tail


def merge_results(
    base: list[dict[str, Any]],
    incoming: list[dict[str, Any]],
    top_k: int,
    *,
    result_key_fn: Callable[[dict[str, Any]], tuple[Any, ...]],
) -> list[dict[str, Any]]:
    """중복 제거하며 검색 결과를 병합한다."""
    merged: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for item in [*base, *incoming]:
        key = result_key_fn(item)
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
        if len(merged) >= top_k:
            break
    return merged
