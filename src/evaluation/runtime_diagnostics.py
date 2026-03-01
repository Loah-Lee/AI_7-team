from __future__ import annotations

import re
import unicodedata
from typing import Any, Callable


def estimate_slot_fill_rate(
    required_slots: list[str],
    answer: str,
    evidence_spans: list[Any],
) -> float:
    if not required_slots:
        return 1.0 if answer.strip() else 0.0

    lowered = unicodedata.normalize("NFKC", answer.lower())
    filled = 0
    for slot in required_slots:
        if slot in {"value", "unit"}:
            has_number = bool(re.search(r"\d", answer))
            has_unit = any(u in answer for u in ["원", "억", "만", "명", "건", "개", "일", "시간", "MB", "GB", "%", "회"])
            if slot == "value" and has_number:
                filled += 1
            if slot == "unit" and has_unit:
                filled += 1
            continue
        if slot == "owner":
            if any(k in lowered for k in ["발주", "제안", "수급", "계약상대", "사업자", "주관기관"]):
                filled += 1
            continue
        if slot in {"docA_claim", "docB_claim"}:
            has_a = any(k in answer for k in ["A 문서", "문서 A", "첫 번째"])
            has_b = any(k in answer for k in ["B 문서", "문서 B", "두 번째"])
            if slot == "docA_claim" and has_a:
                filled += 1
            if slot == "docB_claim" and has_b:
                filled += 1
            continue
        if slot == "comparison_point":
            if any(k in lowered for k in ["차이", "공통", "반면", "각각", "비교"]):
                filled += 1
            continue
        if slot == "evidence":
            if evidence_spans:
                filled += 1
            continue
        if slot == "key_points":
            if len(answer.strip()) >= 24:
                filled += 1
            continue

    return min(1.0, max(0.0, filled / max(1, len(required_slots))))


def estimate_confidence(
    slot_fill_rate: float,
    evidence_spans: list[Any],
    answer_mode: str,
) -> float:
    base = 0.35
    base += slot_fill_rate * 0.45
    base += min(0.2, len(evidence_spans) * 0.06)
    if answer_mode == "extractive":
        base += 0.05
    if answer_mode == "hybrid":
        base += 0.03
    return round(min(1.0, max(0.0, base)), 3)


def collect_answer_content_lines(answer: str) -> list[str]:
    text = unicodedata.normalize("NFKC", str(answer or ""))
    content_lines: list[str] = []
    for raw_line in text.splitlines():
        line = re.sub(r"^\s*[-*•]\s*", "", str(raw_line or "")).strip()
        if not line:
            continue
        lowered = line.lower()
        if re.match(r"^\[[^\]]+\]$", line):
            continue
        if re.match(r"^(근거|출처|source)\s*[:：]?$", line, flags=re.IGNORECASE):
            continue
        if re.match(r"^#?\d+\s+.+\.(pdf|hwp|docx?)\b", lowered):
            continue
        content_lines.append(line)
    return content_lines


def looks_uncertain_answer(answer: str) -> bool:
    if not answer:
        return True
    lowered = answer.lower()
    signals = [
        "문서에 명시되어 있지",
        "찾지 못했",
        "확인되지 않",
        "단정할 수 없",
        "직접 명시한 조항을 찾지 못",
        "명시적 언급이 없",
        "본문 미제공",
        "첨부된 hwp",
        "파일 본문 텍스트가 전달되지",
        "원문(또는 해당 조항 텍스트)을 붙여",
    ]
    return any(sig in lowered for sig in signals)


def should_fallback_to_extractive_draft(
    query: str,
    generated_answer: str,
    extractive_draft: str,
    is_summary_focus_query_fn: Callable[[str], bool],
    looks_uncertain_answer_fn: Callable[[str], bool] = looks_uncertain_answer,
    collect_answer_content_lines_fn: Callable[[str], list[str]] = collect_answer_content_lines,
) -> bool:
    if not is_summary_focus_query_fn(query):
        return False
    draft = str(extractive_draft or "").strip()
    if not draft:
        return False
    generated = str(generated_answer or "").strip()
    if not generated:
        return True
    if looks_uncertain_answer_fn(generated) and not looks_uncertain_answer_fn(draft):
        return True

    draft_lines = collect_answer_content_lines_fn(draft)
    generated_lines = collect_answer_content_lines_fn(generated)
    if not draft_lines:
        return False
    if not generated_lines:
        return True
    # 요약 질의에서 생성 답변이 단문 1줄로 수렴하면 정보 누락 가능성이 커서
    # 다중 라인 draft(항목형)로 복구한다.
    if len(draft_lines) >= 3 and len(generated_lines) <= 1:
        return True
    if len(draft_lines) >= 4 and len(generated_lines) < max(2, len(draft_lines) // 2):
        return True

    stop_tokens = {
        "문서",
        "기준",
        "관련",
        "질문",
        "답변",
        "다음",
        "있습니다",
        "합니다",
        "대한",
        "사업",
        "내용",
        "확인",
        "요약",
        "개요",
        "배경",
        "범위",
        "효과",
        "목표",
    }

    def _token_set(lines: list[str]) -> set[str]:
        merged = unicodedata.normalize("NFKC", " ".join(lines).lower())
        return {
            tok
            for tok in re.findall(r"[0-9a-zA-Z가-힣]{2,}", merged)
            if tok and not tok.isdigit() and tok not in stop_tokens
        }

    draft_tokens = _token_set(draft_lines)
    generated_tokens = _token_set(generated_lines)
    if draft_tokens:
        overlap_ratio = len(draft_tokens & generated_tokens) / max(len(draft_tokens), 1)
        min_overlap = 0.35 if len(draft_tokens) >= 6 else 0.25
        if overlap_ratio < min_overlap and len(generated_lines) < len(draft_lines):
            return True

    draft_numbers: set[str] = set()
    for value in re.findall(r"\d{2,}(?:[.,]\d+)?", " ".join(draft_lines)):
        digits = re.sub(r"[^0-9]", "", value)
        if len(digits) >= 2:
            draft_numbers.add(digits)
    if draft_numbers:
        generated_digits = re.sub(r"[^0-9]", "", generated)
        matched = sum(1 for digits in draft_numbers if digits and digits in generated_digits)
        required = max(1, (len(draft_numbers) + 1) // 2)
        if matched < required:
            return True

    generated_len = len(re.sub(r"\s+", "", " ".join(generated_lines)))
    draft_len = len(re.sub(r"\s+", "", " ".join(draft_lines)))
    if generated_len < max(18, draft_len // 3):
        return True
    return False
