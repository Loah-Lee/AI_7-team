from __future__ import annotations

import re
from typing import Dict, List

_STOPWORDS = {
    "의",
    "가",
    "이",
    "은",
    "는",
    "을",
    "를",
    "에",
    "에서",
    "으로",
    "로",
    "와",
    "과",
    "도",
    "및",
    "또는",
    "그리고",
    "대한",
    "대해",
    "위한",
    "관련",
    "관한",
    "중",
    "내",
    "수",
    "등",
}


def _tokenize(text: str) -> List[str]:
    tokens = re.findall(r"[0-9A-Za-z가-힣]+", text.lower())
    return [tok for tok in tokens if tok not in _STOPWORDS and len(tok) > 1]


def _collect_meta_text(metadata: object) -> str:
    if not isinstance(metadata, dict):
        return ""

    parts: List[str] = []
    direct_keys = ["doc_id", "section_title", "source_path"]
    for key in direct_keys:
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
    page_refs = metadata.get("page_refs")
    if isinstance(page_refs, list):
        nums = [str(x) for x in page_refs if isinstance(x, (int, float, str))]
        if nums:
            parts.append(" ".join(nums))

    nested = metadata.get("meta")
    if isinstance(nested, dict):
        nested_keys = [
            "사업명",
            "발주 기관",
            "공고 번호",
            "파일명",
            "파일형식",
            "사업 요약",
            "사업 금액",
            "입찰 참여 마감일",
        ]
        for key in nested_keys:
            value = nested.get(key)
            if isinstance(value, str) and value.strip():
                parts.append(value.strip())
            elif isinstance(value, (int, float)):
                parts.append(str(value))

    return " ".join(parts)


def _extract_org_prefix(query: str) -> str:
    parts = query.strip().split()
    return parts[0] if parts else ""


def _extract_focus_tokens(query: str) -> List[str]:
    toks = _tokenize(query)
    # 질의 핵심 토큰만 사용(기관명 제외, 상위 6개 제한)
    if not toks:
        return []
    org = toks[0]
    out: List[str] = []
    for tok in toks:
        if tok == org:
            continue
        if tok not in out:
            out.append(tok)
        if len(out) >= 6:
            break
    return out


def _score_candidate(query: str, text: str, metadata: object = None) -> float:
    q_tokens = set(_tokenize(query))
    c_tokens = set(_tokenize(text))
    overlap = len(q_tokens & c_tokens)

    score = overlap * 2.0

    q_lower = query.lower().strip()
    t_lower = text.lower()
    if q_lower and q_lower in t_lower:
        score += 3.0

    if re.search(r"\d{4}[-/.]\d{1,2}[-/.]\d{1,2}", query) and re.search(
        r"\d{4}[-/.]\d{1,2}[-/.]\d{1,2}", text
    ):
        score += 2.0

    if re.search(r"\d+%|\d+\s*퍼센트", query) and re.search(r"\d+%|\d+\s*퍼센트", text):
        score += 1.5

    if re.search(r"\d", query) and re.search(r"\d", text):
        score += 0.5

    meta_text = _collect_meta_text(metadata)
    if meta_text:
        m_lower = meta_text.lower()
        m_tokens = set(_tokenize(meta_text))
        meta_overlap = len(q_tokens & m_tokens)
        score += meta_overlap * 0.8
        q_lower = query.lower().strip()
        if q_lower and q_lower in m_lower:
            score += 2.0
        if re.search(r"\d", query) and re.search(r"\d", meta_text):
            score += 0.5

    # 본작업 보정: 기관명/사업명 exact 매칭을 강하게 우대
    org = _extract_org_prefix(query)
    if org:
        source_path = ""
        meta_org = ""
        meta_doc_id = ""
        meta_title = ""
        if isinstance(metadata, dict):
            source_path = str(metadata.get("source_path", ""))
            meta_doc_id = str(metadata.get("doc_id", ""))
            nested = metadata.get("meta")
            if isinstance(nested, dict):
                meta_org = str(nested.get("발주 기관", ""))
                meta_title = str(nested.get("사업명", ""))

        if org and (
            org in source_path
            or org in meta_org
            or org in meta_doc_id
            or org in meta_title
            or org in text
        ):
            score += 4.0

    focus_tokens = _extract_focus_tokens(query)
    if focus_tokens:
        merged = " ".join([text, meta_text]).lower()
        matched = sum(1 for tok in focus_tokens if tok and tok in merged)
        score += min(matched * 0.6, 2.4)

    score -= min(len(text), 5000) * 0.0001
    return score


def rerank_rule(query: str, candidates: List[Dict[str, object]]) -> List[Dict[str, object]]:
    scored = []
    for idx, cand in enumerate(candidates):
        text = str(cand.get("text", ""))
        score = _score_candidate(query, text, cand.get("metadata"))
        scored.append((score, idx, cand))

    scored.sort(key=lambda x: (x[0], -x[1]), reverse=True)
    return [cand for _, _, cand in scored]
