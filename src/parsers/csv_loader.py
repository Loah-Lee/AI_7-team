#!/usr/bin/env python3
"""CSV 로더."""

from __future__ import annotations

import csv
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any

import sys
sys.path.insert(0, 'src')

from src.utils.config import MAX_TEXT_LENGTH, MIN_SECTION_LENGTH, AMOUNT_UNITS
from src.utils.helpers import remove_josa, parse_amount
from src.prompts.templates import MARKDOWN_TEMPLATE
from src.graph.state import MarkdownData


class CSVMarkdownConverter:
    """CSV 데이터를 마크다운으로 변환하는 클래스."""

    @staticmethod
    def extract_org_name(filename: str) -> str:
        """파일명에서 기관명을 추출합니다."""
        parts = filename.replace('.hwp', '').replace('.pdf', '').replace('.hwpx', '').split('_')
        if parts:
            return remove_josa(parts[0].strip())
        return Path(filename).stem

    @staticmethod
    def split_markdown_sections(markdown: str) -> list[str]:
        """마크다운을 섹션 단위로 분할합니다."""
        return markdown.split('## ')

    @staticmethod
    def filter_valid_sections(sections: list[str]) -> list[str]:
        """유효한 섹션만 필터링합니다."""
        return [s for s in sections if len(s.strip()) > MIN_SECTION_LENGTH]

    def convert_row(self, row: dict[str, str]) -> MarkdownData:
        """CSV 한 행을 마크다운으로 변환합니다."""
        notice_num = row.get('공고 번호', '')
        notice_round = row.get('공고 차수', '')
        project_name = row.get('사업명', '')
        amount = row.get('사업 금액', '')
        org_name = remove_josa(row.get('발주 기관', ''))
        open_date_raw = row.get('공개 일자', '')
        start_date_raw = row.get('입찰 참여 시작일', '')
        end_date_raw = row.get('입찰 참여 마감일', '')
        open_date = self._format_date(open_date_raw)
        start_date = self._format_date(start_date_raw)
        end_date = self._format_date(end_date_raw)
        summary = self._format_summary(row.get('사업 요약', ''))
        file_format = row.get('파일형식', '')
        filename = row.get('파일명', '')
        original_text = row.get('텍스트', '')
        vat_note = self._extract_vat_note(original_text=original_text, summary=summary, amount=amount)

        amount_str = self._format_amount_value(amount)
        original_text = self._truncate_text(original_text)

        markdown = MARKDOWN_TEMPLATE.format(
            notice_num=notice_num or '정보 없음',
            notice_round=notice_round or '0',
            project_name=project_name or '사업명 없음',
            org_name=org_name,
            amount=amount_str,
            open_date=open_date,
            start_date=start_date,
            end_date=end_date,
            summary=summary,
            file_format=file_format.upper() if file_format else 'HWP',
            filename=filename,
            original_text=original_text
        )

        return MarkdownData(
            markdown=markdown,
            org_name=org_name,
            project_name=project_name,
            amount=amount,
            summary=summary,
            filename=filename,
            file_format=file_format,
            metadata={
                "notice_num": notice_num,
                "notice_round": notice_round,
                "amount_raw": amount,
                "open_date_raw": open_date_raw,
                "start_date_raw": start_date_raw,
                "end_date_raw": end_date_raw,
                "vat_note": vat_note,
                "vat_included": bool(vat_note and "포함" in vat_note),
            },
        )

    def convert_file(self, csv_path: str | Path) -> list[MarkdownData]:
        """CSV 파일 전체를 마크다운으로 변환합니다."""
        markdowns: list[MarkdownData] = []

        try:
            with open(csv_path, 'r', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)

                for row_num, row in enumerate(reader, 1):
                    try:
                        data = self.convert_row(row)
                        markdowns.append(data)
                    except ValueError as e:
                        print(f"  행 {row_num} 변환 실패: {e}")
                    except Exception as e:
                        print(f"  행 {row_num} 알 수 없는 오류: {e}")

        except FileNotFoundError:
            print(f"CSV 파일을 찾을 수 없습니다: {csv_path}")
        except Exception as e:
            print(f"CSV 변환 실패: {e}")

        return markdowns

    @staticmethod
    def _format_date(date_str: str) -> str:
        """날짜 문자열을 포맷팅합니다."""
        if not date_str:
            return "정보 없음"
        raw = str(date_str).strip()
        if not raw:
            return "정보 없음"

        normalized = raw.replace("T", " ").replace("Z", "")
        normalized = re.sub(r"\s+", " ", normalized).strip()
        parse_candidates = [
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%Y.%m.%d %H:%M:%S",
            "%Y.%m.%d %H:%M",
            "%Y/%m/%d %H:%M:%S",
            "%Y/%m/%d %H:%M",
            "%Y-%m-%d",
            "%Y.%m.%d",
            "%Y/%m/%d",
        ]
        for fmt in parse_candidates:
            try:
                parsed = datetime.strptime(normalized, fmt)
            except ValueError:
                continue
            if "%H" in fmt:
                if parsed.hour == 0 and parsed.minute == 0:
                    return parsed.strftime("%Y-%m-%d")
                return parsed.strftime("%Y-%m-%d %H:%M")
            return parsed.strftime("%Y-%m-%d")

        return normalized

    @staticmethod
    def _format_summary(summary: str) -> str:
        """사업 요약을 포맷팅합니다."""
        if not summary:
            return "사업 요약 정보가 없습니다."
        if '- ' in summary:
            return summary.replace('- ', '\n- ').strip()
        return summary

    @staticmethod
    def _format_amount_value(amount: str) -> str:
        """금액 문자열을 포맷팅합니다."""
        if not amount:
            return "정보 없음"
        try:
            amount_float = float(amount)
            if amount_float >= AMOUNT_UNITS["억"]:
                return f"{amount_float:,.0f}원 ({amount_float/AMOUNT_UNITS['억']:.2f}억원)"
            return f"{amount_float:,.0f}원"
        except ValueError:
            return str(amount)

    @staticmethod
    def _truncate_text(text: str) -> str:
        """텍스트가 너무 길면 자릅니다."""
        if text and len(text) > MAX_TEXT_LENGTH:
            return text[:MAX_TEXT_LENGTH] + "\n\n...(생략)"
        return text

    @staticmethod
    def _extract_vat_note(original_text: str, summary: str, amount: str) -> str:
        """텍스트에서 부가가치세 포함/별도 정보를 추출합니다."""
        combined = " ".join([str(amount or ""), str(summary or ""), str(original_text or "")]).strip()
        if not combined:
            return ""

        normalized = unicodedata.normalize("NFKC", combined.lower())
        vat_keywords = r"(부가가치세|부가세|vat)"

        include_patterns = [
            rf"{vat_keywords}.{{0,12}}(포함|포함금액|포함조건)",
            rf"(포함|포함금액|포함조건).{{0,12}}{vat_keywords}",
        ]
        exclude_patterns = [
            rf"{vat_keywords}.{{0,12}}(별도|제외|미포함)",
            rf"(별도|제외|미포함).{{0,12}}{vat_keywords}",
        ]

        if any(re.search(pattern, normalized) for pattern in include_patterns):
            return "부가가치세 포함"
        if any(re.search(pattern, normalized) for pattern in exclude_patterns):
            return "부가가치세 별도"
        if "면세" in normalized and re.search(vat_keywords, normalized):
            return "부가가치세 면세"
        return ""
