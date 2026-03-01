#!/usr/bin/env python3
"""입찰메이트 v17 - 헬퍼 함수."""

from __future__ import annotations

import re
import sys
sys.path.insert(0, 'src')

from src.utils.config import AMOUNT_UNITS, JOSA_LIST


def remove_josa(name: str) -> str:
    """기관명에서 한국어 조사를 제거합니다."""
    for josa in JOSA_LIST:
        if name.endswith(josa) and len(name) > 2:
            return name[:-1]
    return name


def format_amount(amount_value: float) -> str:
    """금액을 읽기 쉬운 한국어 형식으로 포맷팅합니다."""
    if amount_value >= AMOUNT_UNITS["억"]:
        eok = amount_value / AMOUNT_UNITS["억"]
        return f"약 {eok:.1f}억 원 ({amount_value:,.0f}원)"
    elif amount_value >= AMOUNT_UNITS["만"]:
        man = amount_value / AMOUNT_UNITS["만"]
        return f"약 {man:,.0f}만 원 ({amount_value:,.0f}원)"
    else:
        return f"{amount_value:,.0f}원"


def parse_amount(amount_str: str) -> int:
    """문자열 금액을 정수로 변환합니다."""
    if not amount_str:
        return 0

    cleaned = amount_str.replace(',', '').strip()

    try:
        amount_float = float(cleaned)
        return int(amount_float)
    except ValueError:
        numbers = re.findall(r'\d+', cleaned)
        return int(''.join(numbers)) if numbers else 0


def extract_amount_from_text(text: str) -> tuple[str, int]:
    """PDF/HWP 텍스트에서 사업비 금액을 추출합니다."""
    if not text:
        return "", 0

    patterns = [
        r'사\s*업\s*비\s*[:：]\s*금([\(]?[\d,]+[\)]?)원',
        r'금\s*액\s*[:：]\s*([\d,]+)원',
        r'금([\d,]+)원',
        r'사\s*업\s*비\s*[:：]?\s*([\d,]+)원',
        r'계약\s*금\s*액\s*[:：]\s*([\d,]+)원',
        r'예\s*산\s*[:：]\s*([\d,]+)원',
        r'총\s*사\s*업\s*비\s*[:：]\s*([\d,]+)원',
    ]

    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            amount_str = match.group(1).replace(',', '').replace('(', '').replace(')', '')
            try:
                amount_int = int(amount_str)
                formatted = f"{amount_int:,}원"
                return formatted, amount_int
            except ValueError:
                continue

    unit_pattern = r'사\s*업\s*비\s*[:：]?\s*([\d.]+)\s*(억|만)\s*원'
    match = re.search(unit_pattern, text)
    if match:
        value = float(match.group(1))
        unit = match.group(2)
        if unit == '억':
            amount_int = int(value * 100_000_000)
        else:
            amount_int = int(value * 10_000)
        return f"{value}{unit}원", amount_int

    return "", 0
