#!/usr/bin/env python3
"""HWP 로더."""

from __future__ import annotations

from pathlib import Path

import sys
sys.path.insert(0, 'src')

from src.utils.config import MAX_PAGES, MIN_SECTION_LENGTH
from src.utils.helpers import normalize_newlines, remove_josa


class HWPMarkdownConverter:
    """HWP 문서를 마크다운으로 변환하는 클래스."""

    def __init__(self) -> None:
        """HWP 변환기를 초기화합니다."""
        try:
            from hwp_to_pdf_converter import HybridDocumentLoader
            self.loader = HybridDocumentLoader()
        except ImportError:
            self.loader = None

    def convert(self, hwp_path: str | Path, org_name: str | None = None) -> str:
        """HWP를 마크다운으로 변환합니다."""
        path = Path(hwp_path)
        filename = path.name
        org_name = org_name or PDFMarkdownConverter.extract_org_name(filename)

        parts = [f"# {org_name}\n"]
        parts.append("## 원본 문서 정보\n")
        parts.append(f"- **파일명**: {filename}\n")
        parts.append("- **파일 형식**: HWP\n")

        text_content = ""
        if self.loader:
            try:
                pages = self.loader.load_document(str(hwp_path))
                parts.append(f"- **페이지 수**: {len(pages)}\n")
                for page in pages[:MAX_PAGES]:
                    if page.get('text'):
                        text_content += page['text'] + "\n\n"
            except Exception:
                text_content = "*문서 변환 중 오류 발생*"

        parts.append("\n## 문서 내용\n\n")

        if text_content:
            text_content = normalize_newlines(text_content)
            parts.append(text_content)
        else:
            parts.append("*텍스트 추출 실패 - 파일명 정보만 사용 가능*\n")

        return "".join(parts)

    # 재사용을 위한 static method
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
