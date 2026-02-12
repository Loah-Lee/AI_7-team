#!/usr/bin/env python3
"""HWP 로더 - LibreOffice를 통한 PDF 변환 후 텍스트 추출."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, 'src')

from src.utils.config import MAX_PAGES, MIN_SECTION_LENGTH
from src.utils.helpers import normalize_newlines, remove_josa
from src.parsers.pdf_loader import PDFMarkdownConverter


class HWPMarkdownConverter:
    """HWP 문서를 마크다운으로 변환하는 클래스."""

    def __init__(self) -> None:
        """HWP 변환기를 초기화합니다."""
        self.pdf_converter = PDFMarkdownConverter()
        self._check_libreoffice()

    def _check_libreoffice(self) -> None:
        """LibreOffice 가용성 확인."""
        self.libreoffice_path = self._find_libreoffice()

    def _find_libreoffice(self) -> str | None:
        """LibreOffice 실행 파일 경로를 찾습니다."""
        candidates = [
            '/usr/bin/libreoffice',
            '/usr/bin/soffice',
            '/usr/lib/libreoffice/program/soffice',
            'C:\\Program Files\\LibreOffice\\program\\soffice.exe',
            'C:\\Program Files (x86)\\LibreOffice\\program\\soffice.exe',
        ]

        for path in candidates:
            if os.path.exists(path):
                return path

        # which 명령으로 확인
        try:
            result = subprocess.run(
                ['which', 'libreoffice'],
                capture_output=True,
                text=True
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except Exception:
            pass

        return None

    def convert(self, hwp_path: str | Path, org_name: str | None = None) -> str:
        """HWP를 마크다운으로 변환합니다."""
        path = Path(hwp_path)
        filename = path.name
        org_name = org_name or self.extract_org_name(filename)

        parts = [f"# {org_name}\n"]
        parts.append("## 원본 문서 정보\n")
        parts.append(f"- **파일명**: {filename}\n")
        parts.append("- **파일 형식**: HWP\n")

        # LibreOffice를 사용한 PDF 변환 및 텍스트 추출
        text_content = self._extract_via_libreoffice(path)

        if text_content:
            lines = text_content.split('\n')
            parts.append(f"- **추출된 라인 수**: {len(lines)}\n")

        parts.append("\n## 문서 내용\n\n")

        if text_content:
            text_content = normalize_newlines(text_content)
            parts.append(text_content)
        else:
            parts.append("*텍스트 추출 실패 - 파일명 정보만 사용 가능*\n")

        return "".join(parts)

    def _extract_via_libreoffice(self, hwp_path: Path) -> str:
        """LibreOffice를 사용하여 HWP → PDF → 텍스트 추출."""
        if not self.libreoffice_path:
            return self._extract_fallback(hwp_path)

        temp_dir = tempfile.mkdtemp(prefix='hwp_convert_')

        try:
            # LibreOffice로 HWP → PDF 변환
            cmd = [
                self.libreoffice_path,
                '--headless',
                '--convert-to', 'pdf',
                '--outdir', temp_dir,
                str(hwp_path)
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
                env={**os.environ, 'DISPLAY': ''}  # headless 모드
            )

            # 변환된 PDF 파일 찾기
            pdf_files = list(Path(temp_dir).glob('*.pdf'))

            if not pdf_files:
                # 오류 메시지 확인
                if result.stderr:
                    print(f"  ⚠️ LibreOffice 변환 오류: {result.stderr[:200]}")
                return self._extract_fallback(hwp_path)

            pdf_path = pdf_files[0]

            # PDF에서 텍스트 추출
            markdown = self.pdf_converter.convert(pdf_path, org_name=None)

            # PDF 헤더/메타데이터 제거하고 텍스트만 반환
            if markdown:
                # "## 문서 내용" 이후 부분만 추출
                if "## 문서 내용" in markdown:
                    text_only = markdown.split("## 문서 내용")[-1].strip()
                else:
                    text_only = markdown

                # 불필요한 섹션 제거
                lines = []
                skip_header = False
                for line in text_only.split('\n'):
                    if line.startswith('##'):
                        skip_header = True
                        continue
                    if skip_header and line.strip() and not line.startswith('-'):
                        skip_header = False
                    if not skip_header:
                        lines.append(line)

                return '\n'.join(lines)

            return ""

        except subprocess.TimeoutExpired:
            print("  ⚠️ LibreOffice 변환 시간 초과")
            return self._extract_fallback(hwp_path)

        except Exception as e:
            print(f"  ⚠️ HWP 변환 실패: {e}")
            return self._extract_fallback(hwp_path)

        finally:
            # 임시 파일 정리
            try:
                import shutil
                shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception:
                pass

    def _extract_fallback(self, hwp_path: Path) -> str:
        """Fallback: 이진 데이터에서 텍스트 패턴 추출."""
        try:
            import olefile

            if not olefile.isOleFile(hwp_path):
                return ""

            ole = olefile.OleFileIO(hwp_path)
            text_parts = []

            # PrvText (미리보기 텍스트) 시도
            if ole.exists('PrvText'):
                try:
                    prv_text = ole.openstream('PrvText').read()
                    # UTF-16LE 디코딩
                    text = prv_text.decode('utf-16le', errors='ignore')
                    # 프린트 가능한 문자만 추출
                    clean = ''.join(c for c in text if c.isprintable() or c in '\n\t ')
                    if len(clean) > 20:
                        text_parts.append(clean)
                except Exception:
                    pass

            # DocInfo에서 요약 정보 추출
            if ole.exists('DocInfo'):
                try:
                    doc_info = ole.openstream('DocInfo').read()
                    # 문서 제목 등 메타데이터
                    text = doc_info.decode('utf-16le', errors='ignore')
                    clean = ''.join(c for c in text if c.isprintable() or c in '\n\t ')
                    if len(clean) > 20:
                        text_parts.append(clean)
                except Exception:
                    pass

            ole.close()

            if text_parts:
                return '\n\n'.join(text_parts)

        except Exception:
            pass

        return ""

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
