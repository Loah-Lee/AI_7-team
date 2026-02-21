from __future__ import annotations

import re
import unicodedata
from typing import Dict, List, Tuple


def normalize(text: str) -> str:
    return unicodedata.normalize("NFC", text or "")


def tokenize(text: str) -> List[str]:
    return re.findall(r"[0-9A-Za-z가-힣]+", (text or "").lower())


def extract_org_prefix(query: str) -> str:
    tokens = query.strip().split()
    return normalize(tokens[0]) if tokens else ""


def org_candidates(query: str) -> List[str]:
    org = extract_org_prefix(query)
    if not org:
        return []
    cands = {org.lower()}
    if org.startswith("한국") and len(org) > 3:
        cands.add(org[2:].lower())
    cands.add(org.replace("(주)", "").replace("주식회사", "").lower())
    out: set[str] = set()
    for c in cands:
        c_n = normalize(c)
        out.add(c_n)
        out.add(re.sub(r"\s+", "", c_n))
    return [c for c in out if c and len(c) >= 2]


def metadata_text(metadata: Dict[str, object] | None) -> str:
    if not isinstance(metadata, dict):
        return ""
    parts: List[str] = []
    for key in ("doc_id", "section_title"):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
    nested = metadata.get("meta")
    if isinstance(nested, dict):
        for key in ("사업명", "발주 기관", "파일명", "사업 요약"):
            value = nested.get(key)
            if isinstance(value, str) and value.strip():
                parts.append(value.strip())
    return " ".join(parts)


def org_blob(source_path: str, text: str, metadata: Dict[str, object] | None, *, meta_only: bool) -> str:
    parts: List[str] = [source_path]
    if not meta_only:
        parts.append((text or "")[:200])
    if isinstance(metadata, dict):
        for key in ("doc_id", "section_title", "source_path"):
            value = metadata.get(key)
            if isinstance(value, str) and value.strip():
                parts.append(value)
        nested = metadata.get("meta")
        if isinstance(nested, dict):
            for key in ("발주 기관", "사업명", "파일명"):
                value = nested.get(key)
                if isinstance(value, str) and value.strip():
                    parts.append(value)
    merged = normalize(" ".join(parts).lower())
    compact = re.sub(r"\s+", "", merged)
    return f"{merged} {compact}"


def org_match(query: str, source_path: str, text: str, metadata: Dict[str, object] | None, *, meta_only: bool) -> bool:
    cands = org_candidates(query)
    if not cands:
        return True
    blob = org_blob(source_path, text, metadata, meta_only=meta_only)
    return any(c in blob for c in cands)


def required_signals(query: str) -> List[str]:
    q = query
    signals: List[str] = []
    if re.search(r"(예산|금액|사업비|기초금액|소요예산|얼마)", q):
        signals.append("money")
    if re.search(r"(비율|평가비율|퍼센트|%)", q):
        signals.append("percent")
    if re.search(r"(기간|몇\s*개월|며칠|언제부터|언제까지|마감일|제출)", q):
        signals.append("period_or_date")
    if re.search(r"(문의|연락처|전화|이메일|담당자)", q):
        signals.append("contact")
    if re.search(r"(과업|업무|범위)", q):
        signals.append("scope")
    return signals


def has_signal(text: str, signal: str) -> bool:
    t = text
    if signal == "money":
        return bool(re.search(r"\d[\d,]*\s*(원|만원|천원|억원)", t))
    if signal == "percent":
        return bool(re.search(r"\d+(\.\d+)?\s*%|\d+(\.\d+)?\s*퍼센트", t))
    if signal == "period_or_date":
        return bool(
            re.search(r"\d{4}[./-]\d{1,2}[./-]\d{1,2}", t)
            or re.search(r"\d{1,2}\s*월\s*\d{1,2}\s*일", t)
            or re.search(r"\d+\s*(일|개월|월)", t)
            or re.search(r"(기간|계약\s*후)", t)
        )
    if signal == "contact":
        return bool(
            re.search(r"(전화|연락처|담당자|이메일|e-mail)", t, re.IGNORECASE)
            or re.search(r"\b\d{2,4}-\d{3,4}-\d{4}\b", t)
            or re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", t)
        )
    if signal == "scope":
        return bool(re.search(r"(과업|업무|범위|수행\s*내용|주요\s*업무)", t))
    return True


def passes_required_signals(query: str, text: str) -> bool:
    sigs = required_signals(query)
    if not sigs:
        return True
    return all(has_signal(text, s) for s in sigs)


def pattern_bonus(query: str, text: str) -> float:
    score = 0.0
    if re.search(r"\d{4}[./-]\d{1,2}[./-]\d{1,2}", query) and re.search(
        r"\d{4}[./-]\d{1,2}[./-]\d{1,2}", text
    ):
        score += 0.2
    if re.search(r"\d+%|\d+\s*퍼센트", query) and re.search(r"\d+%|\d+\s*퍼센트", text):
        score += 0.2
    if re.search(r"\d[\d,]*\s*(원|만원|천원|억원)", query) and re.search(
        r"\d[\d,]*\s*(원|만원|천원|억원)", text
    ):
        score += 0.2
    return score


def gold_bonus(query: str, source_path: str, text: str, metadata: Dict[str, object] | None) -> Tuple[float, bool]:
    source = normalize(source_path or "")
    text_n = normalize(text or "")
    meta = normalize(metadata_text(metadata))
    merged = f"{text_n} {meta}"

    is_org_match = org_match(query, source, text_n, metadata, meta_only=False)
    score = 0.0
    if extract_org_prefix(query):
        if not is_org_match:
            return 0.0, False
        score += 0.6

    query_tokens = set(tokenize(query))
    token_overlap = len(query_tokens & set(tokenize(meta)))
    if token_overlap > 0:
        score += min(0.05 * token_overlap, 0.3)

    if not passes_required_signals(query, merged):
        return 0.0, False

    score += pattern_bonus(query, merged)
    return score, True
