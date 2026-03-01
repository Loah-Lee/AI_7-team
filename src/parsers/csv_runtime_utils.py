from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any


def first_non_empty(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def clean_csv_value(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    lowered = unicodedata.normalize("NFKC", text).lower()
    if lowered in {"nan", "none", "null", "-", "정보 없음", "정보없음"}:
        return ""
    return text


def normalize_csv_datetime_value(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""

    normalized = text.replace("T", " ").replace("Z", "").strip()
    normalized = re.sub(r"\s+", " ", normalized)
    patterns = [
        ("%Y-%m-%d %H:%M:%S", True),
        ("%Y-%m-%d %H:%M", True),
        ("%Y.%m.%d %H:%M:%S", True),
        ("%Y.%m.%d %H:%M", True),
        ("%Y/%m/%d %H:%M:%S", True),
        ("%Y/%m/%d %H:%M", True),
        ("%Y-%m-%d", False),
        ("%Y.%m.%d", False),
        ("%Y/%m/%d", False),
    ]
    for fmt, has_time in patterns:
        try:
            parsed = datetime.strptime(normalized, fmt)
        except ValueError:
            continue
        if has_time:
            if parsed.hour == 0 and parsed.minute == 0:
                return parsed.strftime("%Y-%m-%d")
            return parsed.strftime("%Y-%m-%d %H:%M")
        return parsed.strftime("%Y-%m-%d")
    return normalized


def extract_vat_note_from_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(text or "").lower())
    if not normalized:
        return ""
    vat_pattern = r"(부가가치세|부가세|vat)"
    include_patterns = [
        rf"{vat_pattern}.{{0,12}}(포함|포함금액|포함조건)",
        rf"(포함|포함금액|포함조건).{{0,12}}{vat_pattern}",
    ]
    exclude_patterns = [
        rf"{vat_pattern}.{{0,12}}(별도|제외|미포함)",
        rf"(별도|제외|미포함).{{0,12}}{vat_pattern}",
    ]
    if any(re.search(pattern, normalized) for pattern in include_patterns):
        return "부가가치세 포함"
    if any(re.search(pattern, normalized) for pattern in exclude_patterns):
        return "부가가치세 별도"
    if "면세" in normalized and re.search(vat_pattern, normalized):
        return "부가가치세 면세"
    return ""


def extract_markdown_meta_value(markdown: str, label: str) -> str:
    if not markdown or not label:
        return ""
    pattern = rf"-\s*\*\*{re.escape(label)}\*\*:\s*(.+)"
    match = re.search(pattern, markdown)
    if not match:
        return ""
    value = match.group(1).strip()
    if value.startswith("**") and value.endswith("**"):
        value = value[2:-2].strip()
    return value


def normalize_notice_number(value: Any) -> str:
    return re.sub(r"[^0-9]", "", str(value or ""))


def extract_metadata_source(metadata: dict[str, Any]) -> str:
    for key in ("source", "source_file", "filename", "파일명"):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def source_to_stem(source: str | None) -> str:
    raw = str(source or "").strip()
    if not raw:
        return ""
    normalized = unicodedata.normalize("NFC", raw)
    base_name = Path(normalized).name or normalized
    suffix = Path(base_name).suffix.lower()
    if suffix in {".pdf", ".hwp", ".hwpx", ".csv"}:
        return Path(base_name).stem.strip()
    return base_name.strip()


def extract_metadata_page(metadata: dict[str, Any]) -> int | None:
    for key in ("page", "page_start", "page_no"):
        value = metadata.get(key)
        try:
            page = int(value)
        except Exception:
            continue
        if page > 0:
            return page
    refs = metadata.get("page_refs")
    if isinstance(refs, list):
        for ref in refs:
            try:
                page = int(ref)
            except Exception:
                continue
            if page > 0:
                return page
    return None


def extract_metadata_org(metadata: dict[str, Any]) -> str:
    for key in ("org", "org_name", "institution", "발주 기관", "발주기관", "기관명"):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def query_requests_vat(query: str) -> bool:
    normalized = unicodedata.normalize("NFKC", (query or "").lower())
    return any(token in normalized for token in ["부가가치세", "부가세", "vat", "세금 포함", "세 포함"])


def query_requests_time_detail(query: str) -> bool:
    normalized = unicodedata.normalize("NFKC", (query or "").lower())
    return any(token in normalized for token in ["시간", "시각", "몇시", "몇 시", "오전", "오후", "시분"])


def format_csv_datetime_for_answer(value: Any, query: str = "") -> str:
    normalized = normalize_csv_datetime_value(value)
    if not normalized:
        return ""
    if not query_requests_time_detail(query):
        return normalized

    try:
        parsed = datetime.strptime(normalized, "%Y-%m-%d %H:%M")
    except ValueError:
        return normalized

    period = "오전" if parsed.hour < 12 else "오후"
    hour_12 = parsed.hour % 12 or 12
    if parsed.minute == 0:
        return f"{parsed.strftime('%Y-%m-%d')} {period} {hour_12}시"
    return f"{parsed.strftime('%Y-%m-%d')} {period} {hour_12}시 {parsed.minute}분"


def extract_notice_num_from_query(query: str) -> str:
    normalized = unicodedata.normalize("NFKC", (query or ""))
    matches = re.findall(r"\d{8,14}", normalized)
    if not matches:
        return ""
    return normalize_notice_number(matches[0])
