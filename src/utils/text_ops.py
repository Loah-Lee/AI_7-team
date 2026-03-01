from __future__ import annotations

import re
import unicodedata


def normalize_text_for_match(text: str) -> str:
    normalized = unicodedata.normalize("NFC", unicodedata.normalize("NFKC", (text or "").lower()))
    return re.sub(r"[^0-9a-zA-Z가-힣]+", "", normalized)


def clip_text_safely(text: str, max_len: int = 360) -> str:
    """문장 경계를 최대한 보존하면서 긴 텍스트를 잘라냅니다."""
    value = unicodedata.normalize("NFKC", str(text or "")).strip()
    if not value:
        return ""
    if len(value) <= max_len:
        return value

    min_idx = max(20, int(max_len * 0.6))
    for idx in range(max_len, min_idx, -1):
        prev = value[idx - 1]
        nxt = value[idx] if idx < len(value) else ""
        if prev in ".!?;:)]}\"'”’":
            return value[:idx].rstrip()
        if prev in "다됨요함" and (not nxt or nxt.isspace()):
            return value[:idx].rstrip()
    return value[: max_len - 1].rstrip() + "…"


def looks_incomplete_clause(text: str) -> bool:
    value = unicodedata.normalize("NFKC", str(text or "")).strip()
    if not value:
        return False
    if re.search(r"(?:\bCD\b|\bDVD\b|\bUSB\b|파일|문서|자료)$", value, flags=re.IGNORECASE):
        return True
    if value.endswith(("…", "...", ".", "!", "?", "다", "다.", "입니다.", "합니다.", "됨.", "함.")):
        return False
    return bool(
        re.search(
            r"(하는|이며|하고|하여|되는|발생하는|경우|때|또는|및|으로|와|과|에서|에게|관련|대해)$",
            value,
        )
    )


def clean_extracted_line(line: str) -> str:
    """OCR/표 파편/반복 토큰을 제거해 답변 근거에 쓰기 좋은 한 줄로 정규화합니다."""
    cleaned = unicodedata.normalize("NFKC", (line or "").replace("\r", " ").replace("\t", " ").strip())
    if not cleaned:
        return ""

    cleaned = re.sub(r"^\s*(?:[-*•]\s*)+", "", cleaned)
    cleaned = re.sub(r"^\s*#+\s*", "", cleaned)
    cleaned = cleaned.replace("**", "")
    cleaned = re.sub(r"\bCol\s*\d+\s*:\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"요구\s*사항\s*(?:고유번호|상세설명)?\s*[:：]?\s*", "", cleaned)
    cleaned = re.sub(r"세부\s*내용\s*[:：]?\s*", "", cleaned)
    cleaned = re.sub(r"\b(?:상세\s*설명|세부\s*내용)\b\s*,?\s*", "", cleaned)
    cleaned = re.sub(r"\[\s*(\d{4})\s*\[\s*\1", r"[\1", cleaned)
    cleaned = re.sub(r"(\S+)\s+\1(\s+\1)+", r"\1", cleaned)
    cleaned = re.sub(r"[ᄀ-ᇿ]+", "", cleaned)
    cleaned = re.sub(r",\s*,+", ", ", cleaned)
    cleaned = re.sub(r"^[,;:]+\s*", "", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" -|;")
    return cleaned


def is_noise_line(line: str) -> bool:
    stripped = clean_extracted_line(line)
    if len(stripped) < 6:
        return True
    if re.match(r"^col\s*\d+\s*:\s*$", stripped, flags=re.IGNORECASE):
        return True
    valid_chars = len(re.findall(r"[0-9A-Za-z가-힣\s\.\,\-\:\;\(\)\/%_]", stripped))
    if len(stripped) >= 24 and valid_chars / max(1, len(stripped)) < 0.65:
        return True
    compact_no_space = stripped.replace(" ", "")
    if len(compact_no_space) > 140 and " " not in stripped and not re.search(r"\d{2,}", compact_no_space):
        return True
    if len(compact_no_space) > 80 and stripped.count(" ") <= 1 and re.search(r"[가-힣]{30,}", compact_no_space):
        return True
    metadata_markers = [
        "사업명",
        "사 업 명",
        "공고번호",
        "공고 번호",
        "발주기관",
        "발주 기관",
        "입찰마감",
        "입찰 마감",
        "과업명",
        "용역명",
        "파일명",
        "파일 형식",
        "사업 요약",
        "사업 개요",
        "추진배경",
        "기대효과",
    ]
    compact = stripped.replace(" ", "")
    if any(compact.startswith(marker.replace(" ", "")) for marker in metadata_markers):
        return True
    noise_prefixes = [
        "파일명",
        "사업명",
        "공고 번호",
        "공개 일자",
        "기본 정보",
        "원본 문서 정보",
        "파일 정보",
        "페이지",
        "□ 사업명",
        "○ 사업명",
        "가. 사업명",
        "나. 사업명",
    ]
    if any(stripped.startswith(prefix) for prefix in noise_prefixes):
        return True
    if re.match(r"^(파일명|파일 형식|사업 요약|사업 개요|추진배경|기대효과)\s*[:：]", stripped):
        return True
    lowered = stripped.lower()
    if lowered.startswith("source:") or "logical page" in lowered:
        return True
    if stripped.startswith("| ---"):
        return True
    if re.fullmatch(r"\|?\s*[:\-]+\s*(\|\s*[:\-]+\s*)+\|?", stripped):
        return True
    if stripped.count("|") >= 3:
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        non_empty = [c for c in cells if c]
        if non_empty and all(cell in {"-", "--", "---", ":"} for cell in non_empty):
            return True
    if stripped.count("  ") >= 4 and any(token in stripped for token in ["제안서", "제출", "목차"]):
        return True
    return False
