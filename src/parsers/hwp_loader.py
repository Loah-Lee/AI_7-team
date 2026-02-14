#!/usr/bin/env python3
"""HWP 로더 - LibreOffice를 통한 PDF 변환 후 텍스트 추출."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from typing import Any
from pathlib import Path

sys.path.insert(0, 'src')

from src.utils.config import MIN_SECTION_LENGTH
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

    def _build_libreoffice_env(self, work_dir: Path) -> dict[str, str]:
        """headless 변환에 필요한 LibreOffice 실행 환경을 구성합니다."""
        runtime_dir = work_dir / "runtime"
        runtime_dir.mkdir(parents=True, exist_ok=True)

        env = dict(os.environ)
        env["HOME"] = str(work_dir)
        env["XDG_RUNTIME_DIR"] = str(runtime_dir)
        env["SAL_USE_VCLPLUGIN"] = "svp"
        env["DISPLAY"] = ""
        return env

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

    def _convert_with_libreoffice(self, hwp_path: Path, output_dir: Path) -> Path | None:
        """LibreOffice로 HWP/HWPX를 PDF로 변환합니다."""
        if not self.libreoffice_path:
            return None

        output_dir.mkdir(parents=True, exist_ok=True)
        work_dir = output_dir / ".lo_runtime"
        work_dir.mkdir(parents=True, exist_ok=True)
        profile_dir = work_dir / "profile"
        profile_dir.mkdir(parents=True, exist_ok=True)

        cmd = [
            self.libreoffice_path,
            f"-env:UserInstallation={profile_dir.as_uri()}",
            '--headless',
            '--convert-to', 'pdf',
            '--outdir', str(output_dir),
            str(hwp_path)
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60,
                env=self._build_libreoffice_env(work_dir)
            )
        except Exception:
            return None

        converted = output_dir / f"{hwp_path.stem}.pdf"
        if converted.exists():
            return converted

        for candidate in output_dir.glob("*.pdf"):
            if candidate.stem == hwp_path.stem:
                return candidate

        if result.stderr:
            print(f"  ⚠️ LibreOffice 변환 오류: {result.stderr[:200]}")
        return None

    def convert_to_pdf(
        self,
        hwp_path: str | Path,
        output_dir: str | Path,
        overwrite: bool = False
    ) -> Path | None:
        """HWP/HWPX 파일을 PDF로 변환해 저장합니다."""
        hwp_file = Path(hwp_path)
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        output_pdf = out_dir / f"{hwp_file.stem}.pdf"
        if output_pdf.exists() and not overwrite:
            return output_pdf

        return self._convert_with_libreoffice(hwp_file, out_dir)

    @staticmethod
    def _split_logical_pages(text: str, max_chars: int = 2200) -> list[str]:
        """텍스트를 길이 기준으로 논리 페이지 단위로 분할합니다."""
        raw_lines = [line.strip() for line in text.splitlines()]
        lines = [line for line in raw_lines if line]
        if not lines:
            return []

        pages: list[str] = []
        current: list[str] = []
        current_len = 0

        for line in lines:
            line_len = len(line) + 1
            if current and current_len + line_len > max_chars:
                pages.append("\n".join(current))
                current = []
                current_len = 0
            current.append(line)
            current_len += line_len

        if current:
            pages.append("\n".join(current))
        return pages

    def extract_pages(self, hwp_path: str | Path) -> list[dict[str, Any]]:
        """HWP/HWPX 문서를 페이지 단위 텍스트/표 정보로 추출합니다."""
        source_path = Path(hwp_path)

        with tempfile.TemporaryDirectory(prefix='hwp_convert_') as tmp:
            tmp_dir = Path(tmp)
            pdf_path = self._convert_with_libreoffice(source_path, tmp_dir)
            if not pdf_path:
                fallback_text = self._extract_fallback(source_path).strip()
                if not fallback_text:
                    return []
                logical_pages = self._split_logical_pages(fallback_text)
                if not logical_pages:
                    logical_pages = [fallback_text]
                return [
                    {
                        "page": idx,
                        "text": page_text,
                        "tables": [],
                        "table_count": 0,
                        "content": page_text,
                    }
                    for idx, page_text in enumerate(logical_pages, 1)
                ]

            return self.pdf_converter.extract_pages(pdf_path, include_tables=True)

    def convert(self, hwp_path: str | Path, org_name: str | None = None) -> str:
        """HWP를 마크다운으로 변환합니다."""
        path = Path(hwp_path)
        filename = path.name
        org_name = org_name or self.extract_org_name(filename)

        parts = [f"# {org_name}\n"]
        parts.append("## 원본 문서 정보\n")
        parts.append(f"- **파일명**: {filename}\n")
        parts.append("- **파일 형식**: HWP\n")

        pages = self.extract_pages(path)
        if pages:
            total_lines = sum(len((p.get("content") or "").splitlines()) for p in pages)
            total_tables = sum(int(p.get("table_count", 0)) for p in pages)
            parts.append(f"- **추출 페이지 수**: {len(pages)}\n")
            parts.append(f"- **추출된 라인 수**: {total_lines}\n")
            parts.append(f"- **추출된 표 수**: {total_tables}\n")

        parts.append("\n## 문서 내용\n\n")

        if pages:
            for page in pages:
                page_no = page.get("page", "?")
                content = normalize_newlines(str(page.get("content", ""))).strip()
                if content:
                    parts.append(f"### 페이지 {page_no}\n")
                    parts.append(f"{content}\n\n")
        else:
            parts.append("*텍스트 추출 실패 - 파일명 정보만 사용 가능*\n")

        return "".join(parts)

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
                return normalize_newlines('\n\n'.join(text_parts))

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
